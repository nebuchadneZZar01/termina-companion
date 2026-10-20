"""Minimal Streamlit UI for Termina Companion.

Entry points: ``uv run streamlit run main.py`` (preferred) or
``uv run streamlit run app/ui.py``.
"""

from __future__ import annotations

import datetime
import os
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import streamlit as st

from app.data.mock_knowledge import MASKS, build_default_knowledge
from app.domain import ClockTime, GameState, Goal, TimeWindow
from app.graph import MAX_PLANNING_ATTEMPTS, build_graph
from app.i18n import DEFAULT_LANG, spinner_lines, t, tr, tr_msg
from app.trace import current_run, pipeline_span


@st.cache_resource
def _graph():
    """Build (and cache) the compiled LangGraph once per session.

    args:
        (none)

    returns:
        object: the compiled graph.
    """
    return build_graph()


_LANGS = {"en": "\U0001f1ec\U0001f1e7 English", "it": "\U0001f1ee\U0001f1f9 Italiano"}

_PLANNING_TASK_KEY = "_planning_task"
_ACTIVE_STATUSES = frozenset({"running", "stopping"})
_STOP_SENTINEL = object()
_NO_MESSAGE = object()


def _phoenix_ui_url() -> str:
    """Derive the Phoenix UI URL from the OTLP endpoint.

    Phoenix serves the web UI and the OTLP/HTTP trace receiver on the same
    port (``:6006``), so the UI origin is scheme + host of the configured
    endpoint with the port forced to 6006 — no extra configuration.

    args:
        (none)

    returns:
        str: the Phoenix UI base URL, e.g. ``http://localhost:6006``.
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return "http://localhost:6006"
    parsed = urlsplit(endpoint)
    if not parsed.scheme or not parsed.hostname:
        return "http://localhost:6006"
    return f"{parsed.scheme}://{parsed.hostname}:6006"


PHOENIX_UI_URL = _phoenix_ui_url()
# The Phoenix link is shown only when tracing actually exports somewhere.
PHOENIX_ENABLED = bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())
# Idle wait used by the live progress loop. It only bounds how long we block on
# the worker queue before emitting an invisible yield point, so a queued Stop
# click is handled promptly. It never triggers a redraw on its own.
_IDLE_WAIT = 0.25
# The reasoning title rotates on a wall-clock timer, independent of agent
# updates, so a long LLM call still shows fresh activity.
_TICK_SECONDS = 2.0

# Agent nodes in execution order; the stepper shows a step only once it starts.
_AGENT_NODES = ("memory", "state", "knowledge", "plan", "critic")
_AGENT_LABEL_KEY = {
    "memory": "agent_memory",
    "state": "agent_state",
    "knowledge": "agent_knowledge",
    "plan": "agent_planning",
    "critic": "agent_critic",
}
# Section caption drawn above each agent's detail card, so the card content is
# not confused with the activity log above it.
_RESULT_LABEL_KEY = {
    "memory": "result_memory",
    "state": "result_state",
    "knowledge": "result_knowledge",
    "plan": "result_plan",
    "critic": "result_critic",
}
# Progress phases the UI knows how to render; anything else is ignored so a
# future agent event never renders a raw i18n key.
_PROGRESS_PHASES = frozenset(
    {
        "objectives",
        "mcp_data",
        "cache_search",
        "cache_hit",
        "revalidate",
        "wiki_search",
        "wiki_refs",
        "wiki_fetch",
        "wiki_indexed",
        "reretrieve",
        "context",
        "retrieve",
        "store",
        "llm",
        "llm_done",
    }
)


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
    # Ordered streaming log the stepper replays: ("start", node),
    # ("progress", payload) and ("update", node, data) entries.
    log: list[tuple] = field(default_factory=list)
    error: str = ""


def _task_is_active(task: _PlanningTask | None) -> bool:
    """Return whether a planning task is still running or stopping."""
    return task is not None and task.status in _ACTIVE_STATUSES


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
    try:
        with pipeline_span(goal_text):
            for item in graph.stream(initial, stream_mode=["updates", "custom"]):
                if stop_event.is_set():
                    events.put(_STOP_SENTINEL)
                    return
                mode, chunk = item
                events.put(_Progress(chunk) if mode == "custom" else chunk)
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
        task.log.append(("start", node))
    else:
        task.log.append(("progress", payload))


def _progress_label(tick: int) -> str:
    """Return the reasoning title for a wall-clock tick (rotates every 2s)."""
    phrases = spinner_lines()
    if not phrases:
        return t("planning")
    return f"{phrases[tick % len(phrases)]}..."


def _outer_status(task: _PlanningTask, tick: int) -> tuple[str, str]:
    """Return the ``(state, label)`` for the outer stepper container."""
    validation = task.result.get("validation")
    if task.status == "done":
        valid = bool(getattr(validation, "valid", False))
        if valid:
            return "complete", t("planning_complete")
        return "error", t("planning_gave_up", max=MAX_PLANNING_ATTEMPTS)
    if task.status == "error":
        return "error", t("planning_error", error=task.error or "unknown error")
    if task.status == "stopped":
        return "error", t("planning_stopped")
    if task.status == "stopping":
        return "running", t("planning_stopping")
    return "running", _progress_label(tick)


def _progress_line(payload: dict) -> str:
    """Format one agent progress event, or "" for unknown phases or steps."""
    phase = payload.get("phase")
    if phase not in _PROGRESS_PHASES:
        return ""
    params: dict[str, str] = {}
    for key, value in payload.items():
        if key in {"node", "phase"}:
            continue
        if isinstance(value, (list, tuple)):
            items = [str(item) for item in value]
            value = ", ".join(items[:3]) + ("\u2026" if len(items) > 3 else "")
        if isinstance(value, str) and len(value) > 80:
            value = value[:77] + "\u2026"
        params[key] = value
    return t(f"prog_{phase}", **params)


def _activity_md(events: list[str], running: bool) -> str:
    """Render an agent's activity log: a labelled, bulleted, dimmed timeline.

    Completed events are dimmed with grayscale markdown; while the step is
    still running its last event is highlighted as the current phase. Bullets
    are markdown list items, so Streamlit indents them slightly under the label
    and they line up with the detail card below the divider.

    args:
        events (list[str]): already-formatted event lines, oldest first.
        running (bool): True while the agent is still working.

    returns:
        str: the markdown body for the step's activity block.
    """
    parts = [f"**{t('activity')}**", ""]
    for index, event in enumerate(events):
        current = running and index == len(events) - 1
        marker = "\u23f3" if current else "\u2713"
        item = f"{marker} {event}"
        parts.append(f"- {item}" if current else f"- :gray[{item}]")
    if not running:
        parts.extend(["", "---"])
    return "\n".join(parts)


@dataclass
class _Step:
    """One agent step in the live stepper: its status box and event lines."""

    node: str
    status: object
    live: object
    events: list[str] = field(default_factory=list)


class _PlanStepper:
    """Progressive live stepper: one step per agent, shown when it starts.

    The outer status box is created once and its title rotates on a timer; a
    child step is appended only when its agent starts, so the tree never shows
    future agents. This keeps the widget tree stable (no stacked re-renders) and
    preserves the user's expand/collapse state.
    """

    def __init__(self, tick: int = 0) -> None:
        self.outer = st.status(_progress_label(tick), state="running", expanded=True)
        self._open: dict[str, _Step] = {}

    def start(self, node: str) -> None:
        """Append a running step for an agent as soon as it starts."""
        with (
            self.outer,
            st.status(
                f"\u23f3 {t(_AGENT_LABEL_KEY[node])}", state="running", expanded=True
            ) as status,
        ):
            pass
        self._open[node] = _Step(node=node, status=status, live=status.empty())

    def progress(self, payload: dict) -> None:
        """Append a progress line to the agent's open step, if any."""
        step = self._open.get(payload.get("node", ""))
        if step is None:
            return
        line = _progress_line(payload)
        if not line:
            return
        step.events.append(line)
        step.live.markdown(_activity_md(step.events, running=True))

    def finish(self, node: str, result: dict) -> None:
        """Close an agent's step and draw its full detail card from merged state."""
        step = self._open.pop(node, None)
        if step is None:
            self.start(node)
            step = self._open.pop(node)
        if step.events:
            step.live.markdown(_activity_md(step.events, running=False))
        step.status.update(label=self._step_label(node, result), state="complete", expanded=True)
        _append_step(step.status, node, result)

    @staticmethod
    def _step_label(node: str, result: dict) -> str:
        name = t(_AGENT_LABEL_KEY[node])
        engine, model = _engine_for(node, result)
        name += _engine_badge(engine, model)
        if node == "plan":
            attempt = result.get("replan_attempts", 1)
            name += f" \u2014 {t('step_attempt', n=attempt, max=MAX_PLANNING_ATTEMPTS)}"
        return f"\u2713 {name}"

    def set_outer(self, state: str, label: str) -> None:
        """Update the outer status box label and state in place."""
        self.outer.update(label=label, state=state, expanded=True)


def _apply_log(stepper: _PlanStepper, task: _PlanningTask, cursor: int) -> int:
    """Replay streamed log entries from ``cursor``; return the new cursor."""
    for entry in task.log[cursor:]:
        kind = entry[0]
        if kind == "start":
            if entry[1] not in _AGENT_LABEL_KEY:
                continue
            stepper.start(entry[1])
        elif kind == "progress":
            stepper.progress(entry[1])
        elif kind == "update":
            if entry[1] == "memory_store":
                continue
            stepper.finish(entry[1], task.result)
    return len(task.log)


def _render_planning_progress(task: _PlanningTask) -> None:
    """Render the finished stepper statically by replaying the whole log."""
    stepper = _PlanStepper()
    _apply_log(stepper, task, 0)
    stepper.set_outer(*_outer_status(task, 0))
    if task.status == "error":
        st.error(t("planning_error", error=task.error or "unknown error"))
    elif task.status == "stopped":
        st.warning(t("planning_stopped"))


def _planning_live(task: _PlanningTask) -> None:
    """Drive the live stepper until the run reaches a terminal state.

    The loop blocks on the worker queue (no busy timer), repainting only when an
    agent update arrives or the 2s reasoning-title tick rolls over. The single
    empty placeholder is an invisible yield point, which is what lets Streamlit
    process a queued Stop click while this script is still running.
    """
    stepper = _PlanStepper()
    yield_point = st.empty()
    started = time.monotonic()
    cursor = _apply_log(stepper, task, 0)
    last_tick = 0
    stepper.set_outer(*_outer_status(task, last_tick))
    while _task_is_active(task):
        progressed = _drain_planning_task(task, wait=_IDLE_WAIT)
        if progressed:
            cursor = _apply_log(stepper, task, cursor)
        tick = int((time.monotonic() - started) // _TICK_SECONDS)
        if progressed or tick != last_tick:
            last_tick = tick
            stepper.set_outer(*_outer_status(task, tick))
        yield_point.empty()


def _render_planning_result(task: _PlanningTask, kb) -> None:
    """Render a completed plan or a terminal planning failure."""
    if task.status in {"error", "stopped"}:
        return
    result = task.result
    validation = result.get("validation")
    if validation is None:
        st.warning(t("planning_incomplete"))
        return

    _section(t("your_plan"))
    if validation.valid:
        st.success(t("plan_valid"))
    else:
        st.error(t("plan_not_valid"))

    plan_model = result.get("plan_model")
    if plan_model:
        st.caption(t("plan_model_caption", model=plan_model))

    _render_plan(result.get("plan"))

    tab_why, tab_sources, tab_trace = st.tabs([t("tab_why"), t("tab_sources"), t("tab_trace")])

    with tab_why:
        st.caption(t("tab_why_caption"))
        _render_why(result.get("plan"))
    with tab_sources:
        st.caption(t("tab_sources_caption"))
        _render_sources(result["relevant_objectives"], kb)
        _render_rag_evidence(
            evidence=result.get("retrieved_evidence", []),
            engine=result.get("retrieval_engine", ""),
            status=result.get("retrieval_status", ""),
            warning=result.get("retrieval_warning", ""),
            wiki_unreachable=result.get("retrieval_wiki_unreachable", False),
            indexed_sources=result.get("retrieval_indexed_sources", []),
            ingested_pages=result.get("retrieval_ingested_pages", []),
        )
    with tab_trace:
        st.caption(t("tab_trace_caption"))
        _render_run_audit(result)
        _render_trace_state(result["game_state"])
        _render_memory(result.get("relevant_episodes", []))
        _render_trace_attempts(result["replan_attempts"])
        _render_trace_issues(validation)


def _render_run_audit(result: dict) -> None:
    """Render the run header, node timeline and errors (errors only).

    args:
        result (dict): the final workflow state of this run.

    returns:
        None: draws into the current tab.
    """
    run = current_run()
    if run is None:
        return
    validation = result.get("validation")
    attempts = result.get("replan_attempts", 1)
    outcome = t("audit_valid") if getattr(validation, "valid", False) else t("audit_invalid")
    header = t(
        "audit_header",
        run_id=run.run_id,
        seconds=f"{run.duration_s():.1f}",
        attempts=attempts,
        max=MAX_PLANNING_ATTEMPTS,
        outcome=outcome,
    )
    if PHOENIX_ENABLED:
        header = f"{header} \u00b7 [Open Phoenix \u2197]({PHOENIX_UI_URL})"
    st.markdown(header)
    if run.nodes:
        st.markdown(f"**{t('audit_timeline')}**")
        st.table(
            [
                {
                    t("audit_step"): node["name"],
                    t("audit_duration"): f"{node['duration_s'] * 1000:.0f} ms",
                    t("audit_status"): "\u2705" if node["status"] == "ok" else "\u274c",
                    t("audit_detail"): node["detail"],
                }
                for node in run.nodes
            ]
        )
    if run.errors:
        st.markdown(f"**{t('audit_errors')}**")
        for error in run.errors:
            block = f"[{error['source']}] {error['message']}"
            if error["detail"]:
                block = f"{block}\n{error['detail']}"
            st.code(block, language="text")


def _append_step(status, node: str, result: dict) -> None:
    """Render the trace line for one streamed agent update.

    args:
        status (streamlit.delta_generator.DeltaGenerator): the status
        container to write step details into.
        node (str): the agent node name ("state", "knowledge", "plan",
        "critic").
        result (dict): the node's output dict.

    returns:
        None: draws into the status container.
    """
    if node == "state":
        _step_state(status, result)
    elif node == "memory":
        _step_memory(status, result)
    elif node == "knowledge":
        _step_knowledge(status, result)
    elif node == "plan":
        _step_plan(status, result)
    elif node == "critic":
        _step_critic(status, result)


def _engine_badge(engine: str | None, model: str = "") -> str:
    """Format an engine name as a parenthesised badge suffix.

    args:
        engine (str | None): the engine label, e.g. "llm".
        model (str, default ""): the model name, shown when present.

    returns:
        str: " (engine)" or " (engine · model)" or "" when empty.
    """
    if not engine:
        return ""
    suffix = f" \u00b7 {model}" if model else ""
    return f" ({engine}{suffix})"


def _engine_for(node: str, result: dict) -> tuple[str | None, str]:
    """Return the ``(engine, model)`` pair for an agent node's badge."""
    if node == "plan":
        return result.get("plan_engine"), result.get("plan_model") or ""
    return result.get(f"{node}_engine"), ""


def _result_label(node: str) -> str:
    """Return the bold section caption shown above an agent's detail card."""
    return t(_RESULT_LABEL_KEY[node])


_WINDOW_RE = re.compile(r"\[(Day \d, \d{2}:\d{2} \u2192 Day \d, \d{2}:\d{2})\]")


def _markdown_windows(s: str) -> str:
    """Wraps embedded TimeWindow strings in backticks for markdown rendering."""
    return _WINDOW_RE.sub(lambda m: f"`[{m.group(1)}]`", s)


def _step_state(status, result: dict) -> None:
    """Render the State Agent's trace card.

    args:
        status (DeltaGenerator): the trace container.
        result (dict): the state node output with location and summary.

    returns:
        None: draws into the status container.
    """
    c = status.container()
    c.markdown(f"**{_result_label('state')}**")
    gs = result["game_state"]
    _state_fields(c, gs)
    # The summary's field line is now redundant; keep the quest-progress tail.
    progress = str(result.get("state_summary", "")).partition("\n")[2]
    if progress:
        c.caption(progress)


def _state_fields(scope, gs) -> None:
    """Render the game state as one bulleted markdown block.

    A single markdown list keeps the four fields tight and indented exactly
    like the agent activity timelines and the other detail-card lists. Shared
    by the live State Agent card and the trace tab.

    args:
        scope: the container to draw into.
        gs: the canonicalised game state.

    returns:
        None: draws into the scope container.
    """
    items = ", ".join(tr(item) for item in gs.inventory) or t("trace_none")
    masks = ", ".join(tr(mask) for mask in gs.masks) or t("trace_none")
    scope.markdown(
        "\n".join(
            [
                f"- **{t('trace_where')}** {tr(gs.location)}",
                f"- **{t('trace_when')}** {tr(_fmt_clock(gs.time))}",
                f"- **{t('trace_items')}** {items}",
                f"- **{t('trace_masks')}** {masks}",
            ]
        )
    )


def _step_memory(status, result: dict) -> None:
    """Render the Memory Agent's trace card."""
    c = status.container()
    c.markdown(f"**{_result_label('memory')}**")
    episodes = result.get("relevant_episodes", [])
    c.write(t("memory_episodes_caption"))
    if not episodes:
        c.caption(t("memory_none"))
        return
    for ep in episodes[:3]:
        c.markdown(f"- {ep.goal} ({'valid' if ep.valid else 'invalid'})")


def _step_knowledge(status, result: dict) -> None:
    """Render the Knowledge Agent's trace card.

    args:
        status (DeltaGenerator): the trace container.
        result (dict): the knowledge node output with retrieved objectives.

    returns:
        None: draws into the status container.
    """
    c = status.container()
    c.markdown(f"**{_result_label('knowledge')}**")
    objectives = result["relevant_objectives"]
    c.write(t("knowledge_objectives", n=len(objectives)))
    for obj in objectives:
        c.markdown(f"- {tr(obj.title)}")
    if not objectives:
        c.caption(t("knowledge_empty_hint"))
    retrieval_engine = result.get("retrieval_engine")
    if retrieval_engine:
        c.caption(f"{t('rag_engine')}: `{retrieval_engine}`")
    retrieval_status = result.get("retrieval_status")
    if retrieval_status:
        c.caption(f"{t('rag_status')}: `{retrieval_status}`")
    if result.get("retrieval_wiki_unreachable"):
        c.warning(t("rag_wiki_unreachable"))
    if result.get("retrieval_warning"):
        c.warning(result["retrieval_warning"])


def _step_plan(status, result: dict) -> None:
    """Render the Planning Agent's trace card.

    args:
        status (DeltaGenerator): the trace container.
        result (dict): the plan node output with plan and attempt number.

    returns:
        None: draws into the status container.
    """
    c = status.container()
    c.markdown(f"**{_result_label('plan')}**")
    plan = result["plan"]
    if not plan or not plan.steps:
        c.write(t("no_plan"))
        return
    lines = []
    for i, step in enumerate(plan.steps, 1):
        s, e = step.window.start, step.window.end
        window = f"Day {s.day} - {s.hour:02d}:{s.minute:02d}\u2013{e.hour:02d}:{e.minute:02d}"
        lines.append(f"{i}. {tr(step.title)} @ {tr(step.location)} (`{window}`)")
    c.markdown("\n".join(lines))


def _step_critic(status, result: dict) -> None:
    """Render the Critic Agent's trace card.

    args:
        status (DeltaGenerator): the trace container.
        result (dict): the critic node output with the validation result.

    returns:
        None: draws into the status container.
    """
    c = status.container()
    c.markdown(f"**{_result_label('critic')}**")
    validation = result["validation"]
    if validation.valid:
        # No manual "✓" prefix: t("plan_valid") already carries its own check.
        c.write(t("plan_valid"))
        return
    c.write(t("replan_line", n=len(validation.issues), max=MAX_PLANNING_ATTEMPTS))
    for issue in validation.issues:
        _render_issue(c, issue)


def _render_issue(scope, issue) -> None:
    """Render a single validation issue with severity, kind, step and message.

    args:
        scope (DeltaGenerator): the container to draw into.
        issue (ValidationIssue): the issue to display.

    returns:
        None: draws the issue row.
    """
    is_error = issue.severity == "error"
    kind = t(f"kind_{issue.kind}")
    where = t("step_n", n=issue.step_idx + 1) if issue.step_idx is not None else t("plan")
    col_sev, col_kind, col_step, col_msg = scope.columns([1, 1, 1, 4], vertical_alignment="center")
    sev = (t("sev_error") if is_error else t("sev_warning")).upper()
    col_sev.badge(sev, color="red" if is_error else "orange")
    col_kind.badge(kind.upper(), color="blue")
    col_step.markdown(f"**{where}**")
    col_msg.markdown(tr_msg(_markdown_windows(issue.message)))


def _section(title: str, caption: str = "") -> None:
    """Draw a section header with optional caption.

    args:
        title (str): the section title.
        caption (str, default ""): optional hint under the title.

    returns:
        None: draws into the app.
    """
    st.subheader(title, anchor=False)
    if caption:
        st.caption(caption)


def _fmt_clock(t: ClockTime) -> str:
    """Format a clock as inline code "Day N - HH:MM".

    Every instant renders as a code span so times stand out from the
    surrounding labels, matching models, engines and statuses.

    args:
        t (ClockTime): the time to format.

    returns:
        str: the readable representation.
    """
    return f"`Day {t.day} - {t.hour:02d}:{t.minute:02d}`"


_MONTHS_SHORT = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "it": ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"),
}


def _fmt_timestamp(iso: str | None) -> str:
    """Format an ISO timestamp as a short human date in the current language.

    Wiki revisions and retrieval times are UTC instants; they are shown as
    e.g. "10 ott 2026, 09:49 UTC". An unparsable or missing value falls back
    to the raw string (or "-"), so a weird wiki timestamp never breaks the
    sources tab.

    args:
        iso (str | None): the ISO timestamp to format.

    returns:
        str: the human-readable representation.
    """
    if not iso:
        return "-"
    try:
        dt = datetime.datetime.fromisoformat(str(iso).strip().replace("Z", "+00:00"))
    except ValueError:
        return str(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    dt = dt.astimezone(datetime.timezone.utc)
    lang = st.session_state.get("lang", DEFAULT_LANG)
    months = _MONTHS_SHORT.get(lang, _MONTHS_SHORT["en"])
    return f"{dt.day} {months[dt.month - 1]} {dt.year}, {dt.hour:02d}:{dt.minute:02d} UTC"


def _render_plan(plan) -> None:
    """Render the final plan: time + location header and step actions.

    args:
        plan (Plan | None): the plan to display.

    returns:
        None: draws into the app.
    """
    if not plan or not plan.steps:
        st.write(t("no_plan"))
        return
    for step in plan.steps:
        wl = step.window.start
        st.markdown(f"**{_fmt_clock(wl)} \u2500 {tr(step.location)}**")
        with st.container(border=True):
            st.markdown(f"**{tr(step.title)}**")
            for action in step.actions:
                st.markdown(f"\u2713 {tr(action)}")


def _render_why(plan) -> None:
    """Render the "why" tab: window, needs and dependencies per step.

    args:
        plan (Plan | None): the plan to explain.

    returns:
        None: draws into the app.
    """
    if not plan or not plan.steps:
        st.write(t("no_plan"))
        return
    for i, step in enumerate(plan.steps, 1):
        with st.container(border=True):
            st.markdown(f"**{t('step_n', n=i)} \u2014 {tr(step.title)}**")
            st.write(
                f"{t('window_label')}: {_fmt_clock(step.window.start)} "
                f"\u2192 {_fmt_clock(step.window.end)}"
            )
            if step.requires_items:
                needs = ", ".join(tr(x) for x in step.requires_items)
                st.write(f"{t('needs')}: {needs}")
            if step.requires_masks:
                needs = ", ".join(tr(x) for x in step.requires_masks)
                st.write(f"{t('source_masks')} {needs}")
            if step.depends_on:
                deps = ", ".join(str(d + 1) for d in step.depends_on)
                st.write(t("depends_on", deps=deps))


def _window_range(w: TimeWindow) -> str:
    """Format a window's start through end hour as one range string.

    args:
        w (TimeWindow): the window to format.

    returns:
        str: e.g. "Day 1 08:00–09:00".
    """
    start = tr(_fmt_clock(w.start))
    return f"{start}\u2013{w.end.hour:02d}:{w.end.minute:02d}"


def _render_sources(objectives, kb) -> None:
    """Render the game-sources tab for the retrieved objectives.

    args:
        objectives (list[Objective]): the objectives to source.
        kb (KnowledgeBase): the knowledge base to resolve NPCs/events.

    returns:
        None: draws into the app.
    """
    if not objectives:
        st.write(t("no_sources"))
        return
    for obj in objectives:
        with st.container(border=True):
            st.markdown(f"\U0001f50d **{tr(obj.title)}**")
            st.write(
                f"{t('source_when')} {tr(_fmt_clock(obj.window.start))} "
                f"\u2192 {tr(_fmt_clock(obj.window.end))}"
            )
            st.write(f"{t('source_where')} {tr(obj.location)}")
            if obj.npc_id:
                npc = kb.npc(obj.npc_id)
                if npc:
                    slots = " \u00b7 ".join(_window_range(w) for w in npc.schedule)
                    st.write(
                        f"{t('source_npc')} {tr(npc.name)} \u00b7 {t('source_active')} {slots}"
                    )
            if obj.event_ref:
                event = kb.event(obj.event_ref)
                if event:
                    st.write(
                        f"{t('source_event')} {tr(event.name)} \u00b7 {_window_range(event.window)}"
                    )
            if obj.requires_items:
                items = ", ".join(tr(x) for x in obj.requires_items)
                st.write(f"{t('source_needs')} {items}")
            if obj.requires_masks:
                masks = ", ".join(tr(x) for x in obj.requires_masks)
                st.write(f"{t('source_masks')} {masks}")
            prereq_titles = [o.title for o in kb.all_objectives if o.id in obj.prerequisites]
            if prereq_titles:
                st.write(f"{t('source_after')} {', '.join(tr(x) for x in prereq_titles)}")


def _render_rag_source(source) -> None:
    """Render one indexed wiki page and its complete provenance manifest.

    The page opens as a collapsed expander headed by its title, so a long
    indexed list stays scannable while the full provenance stays one click away.
    """
    with st.expander(tr(source.title)):
        page_id = source.source_page_id if source.source_page_id is not None else source.id
        if page_id:
            st.caption(f"{t('rag_page_id')}: {page_id}")
        if source.source_revision_id is not None:
            st.caption(
                f"{t('rag_revision')}: {source.source_revision_id} "
                f"({_fmt_timestamp(source.source_revision_timestamp)})"
            )
        if source.source_url:
            st.markdown(f"{t('rag_revision_url')}: [{source.source_url}]({source.source_url})")
        if source.canonical_url:
            st.markdown(
                f"{t('rag_canonical_url')}: [{source.canonical_url}]({source.canonical_url})"
            )
        license_text = source.license_note or "-"
        if source.license_url:
            license_text = f"{license_text} · [{t('rag_license_link')}]({source.license_url})"
        st.caption(f"{t('rag_license')}: {license_text}")
        if source.retrieved_at:
            st.caption(f"{t('rag_retrieved_at')}: {_fmt_timestamp(source.retrieved_at)}")


def _render_rag_ingested_page(title: str) -> None:
    """Render a title-only fallback for legacy ingestion results."""
    with st.expander(tr(title)):
        pass


def _render_rag_evidence(
    evidence,
    engine: str = "",
    status: str = "",
    warning: str = "",
    wiki_unreachable: bool = False,
    indexed_sources=None,
    ingested_pages=None,
) -> None:
    """Render indexed source pages separately from supplemental evidence.

    The indexed-source manifest is a UI/state concern. Only ``evidence`` is
    intended for planner context, so source pages remain visible even when a
    second vector query returns no passage.
    """
    st.markdown(f"**{t('rag_sources')}**")
    st.caption(t("rag_sources_caption"))
    if engine:
        st.caption(f"{t('rag_engine')}: `{engine}`")
    if status:
        st.caption(f"{t('rag_status')}: `{status}`")
    if wiki_unreachable:
        st.warning(t("rag_wiki_unreachable"))
    if warning:
        st.warning(f"{t('rag_warning')}: {warning}")

    sources = list(indexed_sources or [])
    if not sources:
        seen: set[str] = set()
        for item in evidence:
            source = item.chunk.metadata
            key = source.id or f"{source.source_page_id}:{source.source_revision_id}"
            if key not in seen:
                seen.add(key)
                sources.append(source)
    st.markdown(f"*{t('rag_indexed_sources')}*")
    if sources:
        st.caption(t("rag_indexed_sources_caption", n=len(sources)))
        for source in sources:
            _render_rag_source(source)
    elif ingested_pages:
        st.caption(t("rag_indexed_sources_caption", n=len(ingested_pages)))
        for title in ingested_pages:
            _render_rag_ingested_page(str(title))
    else:
        st.caption(t("rag_no_indexed_sources"))

    st.markdown(f"**{t('rag_evidence')}**")
    if not evidence:
        st.caption(t("rag_no_evidence"))
        return
    for item in evidence:
        metadata = item.chunk.metadata
        source = metadata.source_url or metadata.canonical_url or "Zelda Wiki"
        excerpt = " ".join(item.chunk.text.split())
        if len(excerpt) > 600:
            excerpt = excerpt[:597].rstrip() + "..."
        with st.container(border=True):
            st.markdown(f"**{tr(metadata.title)}** · {t('rag_score')}: {item.score:.3f}")
            st.write(excerpt)
            st.caption(f"{t('rag_source')}: {source}")
            if metadata.source_revision_id is not None:
                st.caption(
                    f"{t('rag_revision')}: {metadata.source_revision_id} "
                    f"({_fmt_timestamp(metadata.source_revision_timestamp)})"
                )


def _render_trace_state(gs) -> None:
    """Render the canonicalised state in the trace tab.

    args:
        gs (GameState): the state understood by the system.

    returns:
        None: draws into the app.
    """
    _section(t("understood"), t("understood_caption"))
    with st.container(border=True):
        _state_fields(st, gs)


def _render_memory(episodes) -> None:
    """Render past episodes recalled by memory in the trace tab."""
    _section(t("memory_episodes"), t("memory_episodes_caption"))
    if not episodes:
        st.caption(t("memory_none"))
        return
    for ep in episodes[:3]:
        with st.container(border=True):
            st.markdown(f"**{ep.goal}** ({'valid' if ep.valid else 'invalid'})")
            if ep.plan_summary:
                st.caption(" ".join(str(ep.plan_summary).split())[:300])


def _render_trace_attempts(n: int) -> None:
    """Render the planning-attempt counter in the trace tab.

    args:
        n (int): the number of planning attempts made.

    returns:
        None: draws into the app.
    """
    _section(t("trace_attempts"), t("trace_attempts_caption"))
    if n == 0:
        st.success(t("no_replan"))
    elif n >= MAX_PLANNING_ATTEMPTS:
        st.warning(t("replan_gave_up", max=MAX_PLANNING_ATTEMPTS))
    else:
        st.info(t("attempts", n=n, max=MAX_PLANNING_ATTEMPTS))


def _render_trace_issues(validation) -> None:
    """Render validation details and legend in the trace tab.

    args:
        validation (ValidationResult): the validation outcome to display.

    returns:
        None: draws into the app.
    """
    _section(t("validation_details"), t("validation_caption"))
    col_problems, col_legend = st.columns([2, 1], vertical_alignment="top", gap="large")
    with col_problems:
        _section(t("problems"))
        if not validation.issues:
            st.success(t("no_issues"))
        for issue in validation.issues:
            with st.container(border=True):
                _render_issue(st, issue)
    with col_legend:
        _section(t("legend_severity"))
        r1a, r1b = st.columns([1, 3])
        with r1a:
            st.badge(t("sev_error").upper(), color="red")
        with r1b:
            st.write(t("sev_legend_error"))
        r2a, r2b = st.columns([1, 3])
        with r2a:
            st.badge(t("sev_warning").upper(), color="orange")
        with r2b:
            st.write(t("sev_legend_warning"))


def render() -> None:
    """Main Streamlit UI: state editor, planning action and result tabs.

    args:
        (none)

    returns:
        None: renders the whole app page.
    """
    if "lang" not in st.session_state:
        st.session_state["lang"] = "it"

    st.set_page_config(
        page_title="Termina Companion",
        page_icon="\U0001f319",
        layout="wide",
    )

    with st.sidebar:
        st.selectbox(t("language"), list(_LANGS), key="lang", format_func=lambda c: _LANGS[c])
        st.divider()
        _section(t("llm_settings"))
        provider = os.getenv("LLM_PROVIDER", "").strip()
        model = os.getenv("LLM_MODEL", "").strip()
        base_url = os.getenv("LLM_BASE_URL", "").strip()
        if provider:
            st.markdown(f"- **LLM Provider**: `{provider}`")
            if model:
                st.markdown(f"- **Modello**: `{model}`")
            elif base_url:
                st.markdown(f"- **LLM_BASE_URL**: `{base_url}`")
        else:
            st.warning(
                "LLM not configured. Set LLM_PROVIDER (and credentials) in .env (see .env.example)."
            )

    st.title(f"\U0001f319 {t('title')}")
    st.caption(t("subtitle"))

    kb = build_default_knowledge()

    left, right = st.columns(2)
    with left:
        _section(t("game_state"), t("game_state_caption"))
        c1, c2 = st.columns([1, 1])
        with c1:
            day = st.selectbox(t("day"), [1, 2, 3], index=1)
        with c2:
            tm = st.time_input(t("time"), datetime.time(8, 0))

        locations = sorted({loc.name for loc in kb.locations})
        location = st.selectbox(t("location"), locations or ["Termina Field"], format_func=tr)

        masks = st.pills(
            t("masks"),
            list(MASKS),
            selection_mode="multi",
            format_func=tr,
            help=t("masks_help"),
            wrap=True,
        )
        item_options = sorted(
            {i for quest in kb.quests for o in quest.objectives for i in o.requires_items}
        )
        inventory = st.multiselect(
            t("inventory"),
            item_options or ["Kafei's Letter"],
            format_func=tr,
            help=t("inventory_help"),
            placeholder=t("inventory_placeholder"),
            accept_new_options=True,
        )
        quest_names = {q.name: q.id for q in kb.quests}
        done_q = st.pills(
            t("quest_progress"),
            list(quest_names),
            selection_mode="multi",
            format_func=tr,
            help=t("quest_progress_help"),
            wrap=True,
        )
        st.caption(t("legend"))

    with right:
        _section(t("goal"), t("goal_caption"))
        goal_text = st.text_area(
            t("goal_placeholder"),
            placeholder=t("goal_example"),
            height=180,
            label_visibility="collapsed",
        )
        st.markdown('<div style="padding:0.4rem;"></div>', unsafe_allow_html=True)
        task = st.session_state.get(_PLANNING_TASK_KEY)
        generate_disabled, stop_disabled = _plan_controls_disabled(task)
        if not (goal_text or "").strip():
            generate_disabled = True
        run_col, stop_col = st.columns([4, 1])
        with run_col:
            run = st.button(
                t("generate_plan"),
                type="primary",
                use_container_width=True,
                disabled=generate_disabled,
                key="generate_plan_button",
            )
        with stop_col:
            stop = st.button(
                t("stop_plan"),
                use_container_width=True,
                disabled=stop_disabled,
                help=t("stop_plan_help"),
                key="stop_plan_button",
            )

    if stop and _task_is_active(task):
        task.stop_event.set()
        task.status = "stopping"
        st.rerun()

    if run and not _task_is_active(task) and (goal_text or "").strip():
        game_state = GameState(
            time=ClockTime(day=day, hour=tm.hour, minute=tm.minute),
            location=location,
            inventory=list(inventory or []),
            masks=list(masks or []),
            quest_progress={quest_names[q]: "done" for q in (done_q or [])},
        )
        goal = Goal(description=goal_text)

        initial = {
            "game_state": game_state,
            "goal": goal,
            "llm_config": {},
        }
        # Build the cached graph in the main thread: `_graph()` is wrapped in
        # @st.cache_resource, whose dispatcher needs the script run context.
        graph = _graph()
        _start_planning_task(initial, graph)
        st.rerun()

    task = st.session_state.get(_PLANNING_TASK_KEY)
    if _task_is_active(task):
        # Block here, redrawing the stepper only on agent updates. The final
        # rerun re-enables Generate/Stop and renders the result below.
        _planning_live(task)
        st.rerun()

    if task is not None:
        _render_planning_progress(task)
        _render_planning_result(task, kb)
        return

    st.info(t("info_edit_state"))


if __name__ == "__main__":
    render()
