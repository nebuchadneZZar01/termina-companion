"""Background planning and evaluation workers plus their task state."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field

import streamlit as st

from app.evaluation.models import EvaluationReport, ScenarioResult
from app.evaluation.runner import run_scenarios
from app.evaluation.scenarios import SCENARIOS_BY_ID
from app.evaluation.storage import save_report
from app.graph import build_graph
from app.phoenix import publish_plan_validation
from app.state import PlanningState
from app.trace import pipeline_span

logger = logging.getLogger(__name__)


@st.cache_resource
def _graph():
    """Build (and cache) the compiled LangGraph once per session.

    args:
        (none)

    returns:
        object: the compiled graph.
    """
    return build_graph()


_PLANNING_TASK_KEY = "_planning_task"
_EVALUATION_TASK_KEY = "_evaluation_task"
_EVALUATION_REPORT_KEY = "_evaluation_report"
_ACTIVE_STATUSES = frozenset({"running", "stopping"})
_STOP_SENTINEL = object()
_NO_MESSAGE = object()

# Idle wait used by the live progress loop. It only bounds how long we block on
# the worker queue before emitting an invisible yield point, so a queued Stop
# click is handled promptly. It never triggers a redraw on its own.
_IDLE_WAIT = 0.25
# The reasoning title rotates on a wall-clock timer, independent of agent
# updates, so a long LLM call still shows fresh activity.
_TICK_SECONDS = 3.0


@dataclass(frozen=True)
class _Progress:
    """A custom progress event drained from the worker stream."""

    payload: dict


@dataclass
class _PlanningTask:
    """Background planning run kept in Streamlit session state."""

    events: queue.Queue[object] = field(default_factory=queue.Queue)
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    status: str = "running"
    result: dict = field(default_factory=dict)
    updates: list[tuple[str, dict]] = field(default_factory=list)
    # Ordered streaming log the agent registry replays: ("start", node),
    # ("progress", payload) and ("update", node, data) entries.
    log: list[tuple] = field(default_factory=list)
    # Wall-clock start per node and the duration of each finished update,
    # keyed by the update's index in ``log``. Kept out of the log tuples so
    # replay and tests see the same stable shape.
    node_started: dict[str, float] = field(default_factory=dict)
    timings: dict[int, float] = field(default_factory=dict)
    error: str = ""


def _task_is_active(task: _PlanningTask | None) -> bool:
    """Return whether a planning task is still running or stopping."""
    return task is not None and task.status in _ACTIVE_STATUSES


@dataclass
class _EvaluationTask:
    """Background evaluation sweep kept in Streamlit session state.

    The sweep runs the whole pipeline once per scenario, so it takes minutes:
    it lives in a worker thread and reports every finished scenario back
    through a queue, exactly like the planning task.
    """

    events: queue.Queue[object] = field(default_factory=queue.Queue)
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    status: str = "running"
    results: list[ScenarioResult] = field(default_factory=list)
    total: int = 0
    current: str = ""
    error: str = ""


def _save_evaluation_report(results: list[ScenarioResult], rag_on: bool, planner: str) -> None:
    """Persist the outcome of a sweep.

    The report is written from the worker thread, so it survives a closed
    browser tab. An empty sweep is not saved: it carries no check and would
    overwrite a previous report with nothing.

    args:
        results (list[ScenarioResult]): the evaluated scenarios.
        rag_on (bool): whether the supplemental wiki retrieval ran.
        planner (str): the planner engine the sweep used.

    returns:
        None: writes the report, logging a warning on failure.
    """
    if not results:
        return
    try:
        path = save_report(EvaluationReport(results=results, rag_on=rag_on, planner=planner))
    except Exception as exc:  # noqa: BLE001 - a failed save must not kill the sweep
        logger.warning("Could not save the evaluation report: %s", exc)
        return
    logger.info("Evaluation report saved to %s", path)


def _run_evaluation(scenarios, rag_on: bool, planner: str, task: _EvaluationTask) -> None:
    """Run the evaluation sweep in the worker thread.

    Every finished scenario is pushed to the task queue so the UI can show
    the progress live; the sentinel closes the stream. The outcome is also
    written to disk, so the checks outlive the browser session.

    args:
        scenarios (list[PlanScenario]): the scenarios to run.
        rag_on (bool): whether the supplemental wiki retrieval runs.
        planner (str): the planner engine (``"llm"`` or ``"deterministic"``).
        task (_EvaluationTask): the task collecting the results.

    returns:
        None: runs in the background.
    """
    collected: list[ScenarioResult] = []

    def _on_progress(scenario, result: ScenarioResult) -> None:
        """Queue a finished scenario and keep it for the saved report.

        args:
            scenario (PlanScenario): the evaluated scenario.
            result (ScenarioResult): its outcome.

        returns:
            None: queues the result.
        """
        collected.append(result)
        task.events.put((scenario, result))

    try:
        run_scenarios(
            scenarios,
            rag_on=rag_on,
            planner=planner,
            on_progress=_on_progress,
            should_stop=task.stop_event.is_set,
        )
    except Exception as exc:  # noqa: BLE001 - the UI shows the failure
        task.events.put(exc)
    finally:
        _save_evaluation_report(collected, rag_on=rag_on, planner=planner)
        task.events.put(None)


def _drain_evaluation_task(task: _EvaluationTask, wait: float = 0.0) -> bool:
    """Apply queued sweep messages to an evaluation task.

    args:
        task (_EvaluationTask): the task to update in place.
        wait (float, default 0.0): seconds to block waiting for the first
            message before draining. Use it to idle without redrawing.

    returns:
        bool: True when at least one message changed the task, so the caller
        knows whether a redraw is needed.
    """
    first: object = _NO_MESSAGE
    if wait > 0:
        try:
            first = task.events.get(timeout=wait)
        except queue.Empty:
            pass
    progressed = first is not _NO_MESSAGE
    while True:
        if first is not _NO_MESSAGE:
            item, first = first, _NO_MESSAGE
        else:
            try:
                item = task.events.get_nowait()
            except queue.Empty:
                break
        progressed = True
        if item is None:
            if task.status == "stopping" or task.stop_event.is_set():
                task.status = "stopped"
            elif task.status == "running":
                task.status = "done"
        elif isinstance(item, Exception):
            task.status = "error"
            task.error = str(item)
        elif isinstance(item, tuple) and len(item) == 2:
            scenario, result = item
            task.results.append(result)
            task.current = getattr(scenario, "id", "")
    return progressed


def _start_evaluation_task(scenario_ids: list[str], rag_on: bool, planner: str) -> _EvaluationTask:
    """Create, register and start one background evaluation sweep."""
    scenarios = [SCENARIOS_BY_ID[sid] for sid in scenario_ids if sid in SCENARIOS_BY_ID]
    task = _EvaluationTask(total=len(scenarios))
    task.thread = threading.Thread(
        target=_run_evaluation,
        args=(scenarios, rag_on, planner, task),
        daemon=True,
        name="termina-evaluation",
    )
    st.session_state[_EVALUATION_TASK_KEY] = task
    task.thread.start()
    return task


def _plan_controls_disabled(task: _PlanningTask | None) -> tuple[bool, bool]:
    """Return the ``(generate, stop)`` disabled flags for the planning controls.

    args:
        task (_PlanningTask | None): the session planning task, if any.

    returns:
        tuple[bool, bool]: Generate is disabled while a run is active; Stop
        is enabled only while a run is running, not while a stop request is
        already pending.
    """
    active = _task_is_active(task)
    stopping = task is not None and task.status == "stopping"
    return active, stopping or not active


def _run_stream(
    events: queue.Queue[object],
    graph,
    initial: dict,
    stop_event: threading.Event,
) -> None:
    """Stream graph updates until completion or a cooperative stop request."""
    if stop_event.is_set():
        events.put(_STOP_SENTINEL)
        return
    goal = initial.get("goal")
    goal_text = getattr(goal, "description", "") if goal is not None else ""
    # Node updates are merged here as the stream yields them (the same merge
    # the task drain applies), so the final state can be rebuilt for the
    # Phoenix annotation without a second graph query.
    merged: dict = dict(initial)
    try:
        with pipeline_span(goal_text):
            for item in graph.stream(initial, stream_mode=["updates", "custom"]):
                if stop_event.is_set():
                    events.put(_STOP_SENTINEL)
                    return
                mode, chunk = item
                if mode == "updates" and isinstance(chunk, dict):
                    # Stream updates arrive as {"node": {...fields...}}; unwrap
                    # them exactly like the task drain does, or a node whose
                    # name collides with a state field (e.g. "plan") would
                    # overwrite it with its whole update dict.
                    for _node, data in chunk.items():
                        if isinstance(data, dict):
                            merged.update(data)
                events.put(_Progress(chunk) if mode == "custom" else chunk)
        # After the with: the root span is closed and this worker thread's
        # context still holds its ids, so the Critic's verdict can be posted
        # onto the trace in Phoenix (best-effort; same as run_pipeline).
        try:
            publish_plan_validation(PlanningState.model_validate(merged))
        except Exception as exc:  # noqa: BLE001 - telemetry must not fail the run
            logger.warning("Phoenix: plan validation not published: %s", exc)
        events.put(_STOP_SENTINEL if stop_event.is_set() else None)
    except Exception as exc:
        if stop_event.is_set():
            events.put(_STOP_SENTINEL)
        else:
            events.put(exc)
            events.put(None)


def _drain_planning_task(task: _PlanningTask, wait: float = 0.0) -> bool:
    """Apply queued worker messages to a planning task.

    args:
        task (_PlanningTask): the task to update in place.
        wait (float, default 0.0): seconds to block waiting for the first
            message before draining. Use it to idle without redrawing.

    returns:
        bool: True when at least one message changed the task, so the caller
        knows whether a redraw is needed.
    """
    first: object = _NO_MESSAGE
    if wait > 0:
        try:
            first = task.events.get(timeout=wait)
        except queue.Empty:
            pass
    progressed = first is not _NO_MESSAGE
    while True:
        if first is not _NO_MESSAGE:
            item, first = first, _NO_MESSAGE
        else:
            try:
                item = task.events.get_nowait()
            except queue.Empty:
                break
        progressed = True
        if item is _STOP_SENTINEL:
            if task.status != "error":
                task.status = "done" if task.result.get("validation") is not None else "stopped"
        elif item is None:
            if task.status == "running":
                task.status = "done"
            elif task.status == "stopping":
                task.status = "done" if task.result.get("validation") is not None else "stopped"
        elif isinstance(item, Exception):
            task.status = "error"
            task.error = str(item)
        elif isinstance(item, _Progress):
            _record_progress(task, item.payload)
        elif isinstance(item, dict):
            for node, data in item.items():
                if not isinstance(data, dict):
                    continue
                task.result.update(data)
                task.updates.append((node, data))
                started = task.node_started.pop(node, None)
                if started is not None:
                    task.timings[len(task.log)] = time.monotonic() - started
                task.log.append(("update", node, data))
    if _task_is_active(task) and task.thread is not None and not task.thread.is_alive():
        task.status = "stopped" if task.stop_event.is_set() else "error"
        if not task.error:
            task.error = "planning worker exited before completing the run"
    return progressed


def _start_planning_task(initial: dict, graph) -> _PlanningTask:
    """Create, register and start one background planning run."""
    task = _PlanningTask()
    task.thread = threading.Thread(
        target=_run_stream,
        args=(task.events, graph, initial, task.stop_event),
        daemon=True,
        name="termina-planning",
    )
    st.session_state[_PLANNING_TASK_KEY] = task
    task.thread.start()
    return task


def _record_progress(task: _PlanningTask, payload: dict) -> None:
    """Append one custom progress event to the task's replayable log."""
    node = payload.get("node", "")
    if not node:
        return
    if payload.get("phase") == "start":
        task.node_started[node] = time.monotonic()
        task.log.append(("start", node))
    else:
        task.log.append(("progress", payload))
