"""Minimal Streamlit UI for Termina Companion.

Entry points: ``uv run streamlit run main.py`` (preferred) or
``uv run streamlit run app/ui.py``.
"""

from __future__ import annotations

import datetime
import datetime as _datetime
import html
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import streamlit as st

from app.data.mock_knowledge import MASKS, build_default_knowledge
from app.domain import ClockTime, GameState, Goal, TimeWindow
from app.evaluation.comparison import compare_reports, select_baseline
from app.evaluation.models import EvaluationReport, ScenarioResult
from app.evaluation.runner import run_scenarios
from app.evaluation.scenarios import EVALUATION_SCENARIOS, SCENARIOS_BY_ID
from app.evaluation.storage import (
    LAST_REPORT_NAME,
    get_eval_dir,
    load_history,
    load_report,
    save_report,
)
from app.graph import MAX_PLANNING_ATTEMPTS, build_graph
from app.i18n import DEFAULT_LANG, spinner_lines, t, tr, tr_msg
from app.llm import default_model_for
from app.phoenix import publish_plan_validation
from app.save import load_state, save_state
from app.settings import get_settings
from app.state import PlanningState
from app.trace import current_run, pipeline_span

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


_LANGS = {"en": "\U0001f1ec\U0001f1e7 English", "it": "\U0001f1ee\U0001f1f9 Italiano"}

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
_TICK_SECONDS = 2.0

_AGENT_LABEL_KEY = {
    "state": "agent_state",
    "knowledge": "agent_knowledge",
    "plan": "agent_planning",
    "critic": "agent_critic",
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


def _progress_label(tick: int) -> str:
    """Return the reasoning title for a wall-clock tick (rotates every 2s)."""
    phrases = spinner_lines()
    if not phrases:
        return t("planning")
    return f"{phrases[tick % len(phrases)]}..."


def _outer_status(task: _PlanningTask, tick: int) -> tuple[str, str]:
    """Return the live title state and label for the current task status."""
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


def _plain_progress(line: str) -> str:
    """Drop inline markdown markers now that progress lines render as HTML."""
    return line.replace("`", "").replace("*", "")


def _render_planning_progress(task: _PlanningTask) -> None:
    """Render the finished agent registry and any terminal error."""
    _html_block(_agent_registry_html(task))
    if task.status == "error":
        st.error(t("planning_error", error=task.error or "unknown error"))
    elif task.status == "stopped":
        st.warning(t("planning_stopped"))


def _live_title_html(label: str) -> str:
    """Return the pulsing reasoning title drawn above the live registry."""
    return (
        '<div class="tc-live-title">'
        '<span class="tc-live-dot" aria-hidden="true"></span>'
        f"<span>{html.escape(label)}</span></div>"
    )


def _planning_live(task: _PlanningTask) -> None:
    """Drive the live HTML registry until the run reaches a terminal state.

    The registry is redrawn only when a streamed event arrives, while the
    reasoning title rotates on the 2s wall-clock tick. Keeping the registry out
    of the tick redraw preserves any row the user opened between events. The
    single empty placeholder is an invisible yield point, which is what lets
    Streamlit process a queued Stop click while this script is still running.
    """
    title = st.empty()
    registry = st.empty()
    yield_point = st.empty()
    started = time.monotonic()
    last_tick = -1

    def draw_title(tick: int) -> None:
        _state, label = _outer_status(task, tick)
        title.markdown(_live_title_html(label), unsafe_allow_html=True)

    def draw_registry() -> None:
        registry.markdown(_agent_registry_html(task, live=True), unsafe_allow_html=True)

    draw_title(0)
    draw_registry()
    last_tick = 0
    while _task_is_active(task):
        progressed = _drain_planning_task(task, wait=_IDLE_WAIT)
        if progressed:
            draw_registry()
        tick = int((time.monotonic() - started) // _TICK_SECONDS)
        if progressed or tick != last_tick:
            draw_title(tick)
            last_tick = tick
        yield_point.empty()


def _render_planning_result(task: _PlanningTask, kb) -> None:
    """Render the last completed plan, even when the run failed afterwards.

    A failed re-planning attempt produces no plan update, so ``task.result``
    still holds the plan and the validation of the last attempt that reached
    the Critic. Showing it (with its issues) beats hiding the only result the
    run produced. When no attempt completed, the failure is already rendered
    by :func:`_render_planning_progress` and there is nothing to show.
    """
    result = task.result
    validation = result.get("validation")
    failed = task.status in {"error", "stopped"}
    if validation is None:
        if not failed:
            st.warning(t("planning_incomplete"))
        return

    attempt = result.get("replan_attempts", 0)
    plan = result.get("plan")
    if validation.valid:
        _section(t("your_plan"))
        if failed:
            st.caption(
                t(
                    "plan_last_attempt",
                    n=attempt,
                    max=MAX_PLANNING_ATTEMPTS,
                )
            )
        _html_block(
            _verdict_html(
                True,
                t("plan_valid"),
                t("verdict_ok_body", n=attempt, max=MAX_PLANNING_ATTEMPTS),
            )
        )
    else:
        missing = _missing_requirements(validation.issues)
        body = (
            t("verdict_missing_body")
            if missing
            else t(
                "verdict_fail_body",
                n=len(validation.issues),
                n_attempt=attempt,
                max=MAX_PLANNING_ATTEMPTS,
            )
        )
        _html_block(
            _verdict_html(
                False,
                t("verdict_fail_title"),
                body,
                _missing_chips_html(validation.issues),
            )
        )
        if validation.issues:
            _html_block(_problems_panel_html(validation.issues))
        _render_last_plan(plan, validation.issues)
        if failed:
            st.caption(
                t(
                    "plan_last_attempt",
                    n=attempt,
                    max=MAX_PLANNING_ATTEMPTS,
                )
            )

    plan_model = result.get("plan_model")
    if plan_model:
        st.caption(t("plan_model_caption", model=_fmt_model(plan_model)))

    if validation.valid:
        _render_plan(plan)

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
    if get_settings().tracing_enabled:
        header = f"{header} \u00b7 [Open Phoenix \u2197]({get_settings().phoenix_ui_url})"
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


# Engines whose badge is an acronym, not a lowercase identifier.
_ENGINE_LABELS = {"llm": "LLM"}


def _engine_for(node: str, result: dict) -> tuple[str | None, str]:
    """Return the ``(engine, model)`` pair for an agent node's badge."""
    if node == "plan":
        return result.get("plan_engine"), result.get("plan_model") or ""
    return result.get(f"{node}_engine"), ""


def _fmt_model(model: str | None) -> str:
    """Render a model name as inline code, or the unknown placeholder."""
    return f"`{model}`" if model else t("eval_unknown")


_WINDOW_RE = re.compile(
    r"\[(Day \d, \d{2}:\d{2}(?: \(\+1\))? \u2192 Day \d, \d{2}:\d{2}(?: \(\+1\))?)\]"
)


def _markdown_windows(s: str) -> str:
    """Wraps embedded TimeWindow strings in backticks for markdown rendering."""
    return _WINDOW_RE.sub(lambda m: f"`[{m.group(1)}]`", s)


def _state_fields(scope, gs) -> None:
    """Render the game state as one bulleted markdown block.

    A single markdown list keeps the four fields tight and indented exactly
    like the other trace lists.

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


def _render_issue(scope, issue, fallback: str = "plan") -> None:
    """Render a single validation issue with severity, kind, step and message.

    args:
        scope (DeltaGenerator): the container to draw into.
        issue (ValidationIssue): the issue to display.
        fallback (str, default "plan"): the label used when the issue does
            not point at a single step. An empty fallback hides the position
            column entirely (evaluation warnings are about the whole scenario,
            and a bare "Scenario" cell there reads as a stray field).

    returns:
        None: draws the issue row.
    """
    is_error = issue.severity == "error"
    kind = t(f"kind_{issue.kind}")
    if issue.step_idx is not None:
        where = t("step_n", n=issue.step_idx + 1)
    elif fallback:
        where = t(fallback)
    else:
        where = ""
    if where:
        cols = scope.columns([1, 1, 1, 4], vertical_alignment="center")
        col_sev, col_kind, col_step, col_msg = cols
    else:
        col_sev, col_kind, col_msg = scope.columns([1, 1, 4], vertical_alignment="center")
        col_step = None
    sev = (t("sev_error") if is_error else t("sev_warning")).upper()
    col_sev.badge(sev, color="red" if is_error else "orange")
    col_kind.badge(kind.upper(), color="blue")
    if col_step is not None:
        col_step.markdown(f"**{where}**")
    col_msg.markdown(tr_msg(_markdown_windows(issue.message)))


_MISSING_RE = re.compile(r"^Missing (item|mask)\(s\): (.+)\.$")


def _missing_requirements(issues) -> list[str]:
    """Extract missing item/mask names from the Critic's English issue text."""
    names: list[str] = []
    for issue in issues:
        match = _MISSING_RE.match(issue.message.strip())
        if match is None:
            continue
        for name in match.group(2).split(","):
            name = name.strip()
            if name and name not in names:
                names.append(name)
    return names


def _missing_chips_html(issues, prefix: bool = False) -> str:
    """Return requirement chips for the issues, optionally prefixed with 'missing'."""
    names = _missing_requirements(issues)
    if not names:
        return ""
    chips = []
    for name in names:
        label = t("missing_requirement", name=tr(name)) if prefix else tr(name)
        chips.append(f'<span class="tc-missing-chip">{html.escape(label)}</span>')
    return f'<div class="tc-missing-chips">{"".join(chips)}</div>'


def _issues_table_html(issues, fallback: str = "plan") -> str:
    """Return the Critic issue table shared by the registry and problems panels."""
    rows = []
    for issue in issues:
        severity = t("sev_error") if issue.severity == "error" else t("sev_warning")
        tone = "error" if issue.severity == "error" else "warning"
        kind = t(f"kind_{issue.kind}")
        where = t("step_n", n=issue.step_idx + 1) if issue.step_idx is not None else t(fallback)
        rows.append(
            '<div class="tc-issue-row">'
            f'<span><span class="tc-sev-tag {tone}">{html.escape(severity.upper())}</span></span>'
            f'<span><span class="tc-kind-tag">{html.escape(kind.upper())}</span></span>'
            f'<span class="tc-issue-step">{html.escape(where)}</span>'
            f"<span>{html.escape(tr_msg(issue.message))}</span>"
            "</div>"
        )
    return (
        '<div class="tc-issues-table">'
        '<div class="tc-issue-row tc-issue-head">'
        f"<span>{html.escape(t('issue_severity').upper())}</span>"
        f"<span>{html.escape(t('issue_kind').upper())}</span>"
        f"<span>{html.escape(t('issue_step').upper())}</span>"
        f"<span>{html.escape(t('issue_detail').upper())}</span>"
        "</div>"
        f"{''.join(rows)}</div>"
    )


def _problems_panel_html(issues) -> str:
    """Return the full-width problems table shown under an invalid plan."""
    return (
        '<section class="tc-problems-panel">'
        f'<div class="tc-panel-title">{html.escape(t("problems"))}</div>'
        f"{_issues_table_html(issues)}"
        "</section>"
    )


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
    """Format a clock as inline code "Day N - HH:MM (+1)".

    Every instant renders as a code span so times stand out from the
    surrounding labels, matching models, engines and statuses. The ``(+1)``
    marks the night after midnight at the end of the same game day.

    args:
        t (ClockTime): the time to format.

    returns:
        str: the readable representation.
    """
    suffix = " (+1)" if t.next_morning else ""
    return f"`Day {t.day} - {t.display_hour:02d}:{t.minute:02d}{suffix}`"


def _fmt_window(w: TimeWindow) -> str:
    """Format a window as "Day N - HH:MM–HH:MM" without code spans.

    args:
        w (TimeWindow): the window to format.

    returns:
        str: the readable range, with the end day named when it differs.
    """
    start = f"Day {w.start.day} - {w.start.display_hour:02d}:{w.start.minute:02d}"
    start += " (+1)" if w.start.next_morning else ""
    if w.end.day == w.start.day:
        end = f"{w.end.display_hour:02d}:{w.end.minute:02d}"
        end += " (+1)" if w.end.next_morning else ""
    else:
        end = f"Day {w.end.day} - {w.end.display_hour:02d}:{w.end.minute:02d}"
        end += " (+1)" if w.end.next_morning else ""
    return f"{start}\u2013{end}"


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


def _render_plan(
    plan,
    *,
    start: int = 0,
    end: int | None = None,
    issues=None,
    show_numbers: bool = False,
) -> None:
    """Render the final plan as the Majora's Mask vertical timeline.

    args:
        plan (Plan | None): the plan to display.
        start (int, default 0): first step index to render.
        end (int | None, default None): exclusive last step index.
        issues: validation issues used to highlight steps and show chips.
        show_numbers (bool, default False): prefix each title with "Step N".

    returns:
        None: draws into the app.
    """
    if not plan or not plan.steps:
        st.write(t("no_plan"))
        return
    total = len(plan.steps)
    issues_by_step: dict[int, list] = {}
    for issue in issues or []:
        if issue.severity == "error" and issue.step_idx is not None:
            issues_by_step.setdefault(issue.step_idx, []).append(issue)
    selected = list(enumerate(plan.steps))[start:end]
    rows = []
    for index, step in selected:
        last = index == total - 1
        bad = index in issues_by_step
        start_clock = step.window.start
        suffix = " (+1)" if start_clock.next_morning else ""
        hour = f"{start_clock.display_hour:02d}:{start_clock.minute:02d}{suffix}"
        meta = [html.escape(tr(step.location))]
        needs = [tr(x) for x in (*step.requires_items, *step.requires_masks)]
        if needs:
            meta.append(f"{html.escape(t('needs'))} {html.escape(', '.join(needs))}")
        if step.depends_on:
            deps = ", ".join(str(d + 1) for d in step.depends_on)
            meta.append(html.escape(t("depends_on", deps=deps)))
        title = tr(step.title)
        if show_numbers:
            title = t("plan_step_title", n=index + 1, title=title)
        chips = _missing_chips_html(issues_by_step.get(index, []), prefix=True)
        classes = "tc-step"
        if last:
            classes += " last"
        if bad:
            classes += " bad"
        rows.append(
            f'<div class="{classes}">'
            '<div class="tc-step-time">'
            f'<div class="tc-step-hour">{hour}</div>'
            f'<div class="tc-step-day">{html.escape(t("day_n", n=start_clock.day))}</div>'
            "</div>"
            '<div class="tc-step-rail">'
            '<span class="tc-dot"></span><span class="tc-line"></span>'
            "</div>"
            '<div class="tc-step-card">'
            f'<div class="tc-step-title">{html.escape(title)}</div>'
            f'<div class="tc-step-meta">{" \u00b7 ".join(meta)}</div>'
            f"{chips}"
            "</div></div>"
        )
    _html_block(f'<div class="tc-timeline">{"".join(rows)}</div>')


def _render_last_plan(plan, issues) -> None:
    """Render the invalid plan around its first failing step."""
    _section(t("last_plan_title"))
    if not plan or not plan.steps:
        st.write(t("no_plan"))
        return
    focus = next(
        (
            issue.step_idx
            for issue in issues
            if issue.severity == "error" and issue.step_idx is not None
        ),
        None,
    )
    if focus is not None:
        st.caption(t("last_plan_caption", n=focus + 1))
    _render_plan(plan, issues=issues, show_numbers=True)


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
            if step.actions:
                st.markdown(f"**{t('actions_label')}**")
                for action in step.actions:
                    st.markdown(f"- {tr(action)}")


def _window_range(w: TimeWindow) -> str:
    """Format a window's start through end hour as one range string.

    args:
        w (TimeWindow): the window to format.

    returns:
        str: e.g. "Day 1 08:00–09:00".
    """
    start = tr(_fmt_clock(w.start))
    if w.end.day != w.start.day:
        return f"{start}\u2013{tr(_fmt_clock(w.end))}"
    suffix = " (+1)" if w.end.next_morning else ""
    return f"{start}\u2013{w.end.display_hour:02d}:{w.end.minute:02d}{suffix}"


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


def _save_evaluation_report(results: list[ScenarioResult], rag_on: bool) -> None:
    """Persist the outcome of a sweep.

    The report is written from the worker thread, so it survives a closed
    browser tab. An empty sweep is not saved: it carries no check and would
    overwrite a previous report with nothing.

    args:
        results (list[ScenarioResult]): the evaluated scenarios.
        rag_on (bool): whether the supplemental wiki retrieval ran.

    returns:
        None: writes the report, logging a warning on failure.
    """
    if not results:
        return
    try:
        path = save_report(EvaluationReport(results=results, rag_on=rag_on))
    except Exception as exc:  # noqa: BLE001 - a failed save must not kill the sweep
        logger.warning("Could not save the evaluation report: %s", exc)
        return
    logger.info("Evaluation report saved to %s", path)


def _run_evaluation(scenarios, rag_on: bool, task: _EvaluationTask) -> None:
    """Run the evaluation sweep in the worker thread.

    Every finished scenario is pushed to the task queue so the UI can show
    the progress live; the sentinel closes the stream. The outcome is also
    written to disk, so the checks outlive the browser session.

    args:
        scenarios (list[PlanScenario]): the scenarios to run.
        rag_on (bool): whether the supplemental wiki retrieval runs.
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
            on_progress=_on_progress,
            should_stop=task.stop_event.is_set,
        )
    except Exception as exc:  # noqa: BLE001 - the UI shows the failure
        task.events.put(exc)
    finally:
        _save_evaluation_report(collected, rag_on=rag_on)
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


def _start_evaluation_task(scenario_ids: list[str], rag_on: bool) -> _EvaluationTask:
    """Create, register and start one background evaluation sweep."""
    scenarios = [SCENARIOS_BY_ID[sid] for sid in scenario_ids if sid in SCENARIOS_BY_ID]
    task = _EvaluationTask(total=len(scenarios))
    task.thread = threading.Thread(
        target=_run_evaluation,
        args=(scenarios, rag_on, task),
        daemon=True,
        name="termina-evaluation",
    )
    st.session_state[_EVALUATION_TASK_KEY] = task
    task.thread.start()
    return task


def _scenario_label(scenario_id: str) -> str:
    """Return the label of a scenario in the scenario picker."""
    scenario = SCENARIOS_BY_ID.get(scenario_id)
    return f"{scenario.name} ({scenario_id})" if scenario else scenario_id


def _evaluation_live(task: _EvaluationTask) -> None:
    """Drive the evaluation progress bar until the sweep reaches a terminal state.

    The loop blocks on the worker queue (no busy timer) and repaints only when
    a scenario finishes. The empty placeholder is the invisible yield point
    that lets Streamlit process a queued Stop click during a long run.
    """
    bar = st.progress(0.0, text=t("eval_running"))
    caption = st.empty()
    yield_point = st.empty()
    while task.status in _ACTIVE_STATUSES:
        progressed = _drain_evaluation_task(task, wait=_IDLE_WAIT)
        total = max(task.total, 1)
        bar.progress(min(len(task.results) / total, 1.0), text=t("eval_running"))
        caption.caption(t("eval_running_scenario", name=task.current or "-"))
        if not progressed:
            time.sleep(0.05)
        yield_point.empty()


def _short_error(error: str, limit: int = 160) -> str:
    """Shorten a run error so the report table stays readable.

    args:
        error (str): the error message, empty when the run succeeded.
        limit (int): the maximum length kept.

    returns:
        str: the error message, truncated, or "-" when there is none.
    """
    if not error:
        return "-"
    return error if len(error) <= limit else f"{error[: limit - 1]}…"


def _saved_report_path() -> Path | None:
    """Return the report path shown under the evaluation controls.

    args:
        (none)

    returns:
        Path | None: the path of the last report, or None when the store
        cannot be opened (for instance a read-only checkout).
    """
    try:
        return get_eval_dir() / LAST_REPORT_NAME
    except OSError:
        return None


def _render_evaluation_results(report: EvaluationReport) -> None:
    """Render the outcome of an evaluation sweep: metrics, table and details.

    args:
        report (EvaluationReport): the report to render.

    returns:
        None: renders into the app.
    """
    _section(t("eval_result"))
    if not report.results:
        st.caption(t("eval_no_results"))
        return

    if report.rag_on is not None or report.models:
        st.caption(
            t(
                "eval_report_meta",
                model=_fmt_model(report.models),
                rag=t(f"eval_rag_{report.wiki_retrieval}"),
                repeats=report.repeats,
            )
        )
        if report.wiki_retrieval == "degraded":
            st.caption(t("eval_rag_degraded_help"))

    c_rate, c_passed, c_failed, c_kinds = st.columns(4)
    c_rate.metric(t("eval_pass_rate"), f"{report.pass_rate * 100:.0f}%")
    c_passed.metric(t("eval_passed"), f"{report.passed}/{report.total}")
    c_failed.metric(t("eval_failed"), str(report.failed))
    kinds = report.failures_by_kind
    c_kinds.metric(
        t("eval_failures_by_kind"),
        ", ".join(f"{_check_label(kind)}: {count}" for kind, count in kinds.items()) or "-",
    )

    _render_comparison(report)

    st.table(
        [
            {
                t("eval_scenario"): result.scenario_id,
                t("eval_status"): t("eval_pass") if result.passed else t("eval_fail"),
                t("eval_steps"): result.step_count,
                t("eval_duration"): f"{result.duration_s:.1f}s",
                t("eval_errors"): result.error_count,
                t("eval_warnings"): result.warning_count,
                t("eval_run_error"): _short_error(result.error),
            }
            for result in report.results
        ]
    )

    for result in report.results:
        status = t("eval_pass") if result.passed else t("eval_fail")
        with st.expander(f"{result.scenario_id} — {status}"):
            if result.error:
                st.error(f"{t('eval_run_error')}: {result.error}")
            elif not result.issues:
                st.success(t("eval_no_issues"))
            for issue in result.issues:
                _render_issue(st, issue, fallback="")
                help_key = f"kind_{issue.kind}_help"
                help_text = t(help_key)
                if help_text != help_key:
                    st.caption(help_text)


def _format_timestamp(value: str) -> str:
    """Format a stored ISO timestamp for display.

    A value that cannot be parsed is returned unchanged, so an old or foreign
    report still shows something instead of an empty caption.

    args:
        value (str): the stored timestamp.

    returns:
        str: the display timestamp, e.g. ``22/10/2026 15:25 UTC``.
    """
    try:
        stamp = datetime.datetime.fromisoformat(value)
    except ValueError:
        return value
    return stamp.strftime("%d/%m/%Y %H:%M UTC")


def _render_comparison(report: EvaluationReport) -> None:
    """Render how the sweep changed against the newest compatible stored sweep.

    The baseline comes from the saved history, so a sweep loaded with *Load
    last report* is compared too: it is already in the history and
    ``select_baseline`` skips the report itself. An unreadable store only hides
    the card, it never breaks the tab.

    args:
        report (EvaluationReport): the sweep being rendered.

    returns:
        None: renders into the app.
    """
    try:
        baseline = select_baseline(report, load_history())
    except Exception:  # noqa: BLE001 - an unreadable store must not break the tab
        return
    if baseline is None:
        st.caption(t("eval_compare_none"))
        return
    comparison = compare_reports(report, baseline)
    when = _format_timestamp(baseline.created_at) or t("eval_unknown")
    before = f"{comparison.baseline_passed}/{comparison.baseline_total}"
    after = f"{comparison.current_passed}/{comparison.current_total}"
    rows = [
        {
            t("eval_compare_scenario"): change.scenario_id,
            t("eval_compare_change"): t(f"eval_compare_{change.status}"),
            t("eval_compare_detail"): (
                t(
                    "eval_compare_new_failure",
                    kinds=", ".join(_check_label(kind) for kind in change.new_failure_kinds),
                )
                if change.new_failure_kinds
                else t(f"eval_compare_{change.status}_help")
            ),
        }
        for change in comparison.changes
        if change.status != "same"
    ]
    if comparison.has_regressions:
        st.warning(t("eval_compare_summary", when=when, before=before, after=after))
    elif rows:
        st.caption(t("eval_compare_summary", when=when, before=before, after=after))
    else:
        st.caption(t("eval_compare_clean", when=when, before=before, after=after))

    if comparison.model_changed:
        st.caption(
            t(
                "eval_compare_model",
                before=_fmt_model(comparison.baseline_model),
                after=_fmt_model(comparison.current_model),
            )
        )
    if comparison.rag_changed:
        st.caption(
            t(
                "eval_compare_rag",
                before=_rag_label(comparison.baseline_rag),
                after=_rag_label(comparison.current_rag),
            )
        )
    if comparison.repeats_changed:
        st.caption(
            t(
                "eval_compare_repeats",
                before=comparison.baseline_repeats,
                after=comparison.current_repeats,
            )
        )

    if rows:
        st.table(rows)


def _check_label(kind: str) -> str:
    """Return the translated label of an evaluation check kind."""
    return t(f"kind_{kind}")


def _rag_label(state: str) -> str:
    """Return the translated label of a sweep's wiki retrieval state."""
    if not state or state == "unknown":
        return t("eval_unknown")
    return t(f"eval_rag_{state}")


def _internal_hour(hour: int) -> int:
    """Map a wall-clock hour to the internal 06:00-29:59 game clock.

    Hours 00:00-05:59 belong to the night at the end of the selected game
    day, so they become 24-29 rather than the start of that day.

    args:
        hour (int): the wall-clock hour, 0-23.

    returns:
        int: the internal hour, 6-29.
    """
    return hour if hour >= 6 else hour + 24


def _time_label(day: int, value: datetime.time) -> str:
    """Describe a selected time in the current game-day model.

    args:
        day (int): the selected game day.
        value (datetime.time): the selected wall-clock time.

    returns:
        str: a translated label such as "Day 1 · 02:30 — night after midnight".
    """
    display = f"{value.hour:02d}:{value.minute:02d}"
    if value.hour < 6:
        key = "time_after_midnight"
    elif value.hour < 18:
        key = "time_day"
    else:
        key = "time_night"
    return t(key, day=day, time=display)


_THEME_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=Inter:wght@400;500;600&display=swap');

:root {
  --tc-bg: #0e1126;
  --tc-surface: #141836;
  --tc-card: #1b2046;
  --tc-border: #2a2f5c;
  --tc-border-strong: #4a4f80;
  --tc-gold: #e0b252;
  --tc-teal: #5fd1c4;
  --tc-red: #e5684f;
  --tc-text: #e8e6f2;
  --tc-muted: #a9a6c4;
}

html, body, .stApp, [data-testid="stAppViewContainer"] {
  font-family: Inter, system-ui, sans-serif;
}
.stApp {
  background: radial-gradient(circle at 20% 0%, #171c3a 0%, #0e1126 45%, #0b0e1f 100%);
  color: var(--tc-text);
}
[data-testid="stMainBlockContainer"] {
  padding-top: 1.25rem !important;
}
[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
[data-testid="stExpandSidebarButton"] { visibility: visible !important; }

h1, h2, h3, h4, h5, h6 {
  font-family: Cinzel, serif !important;
  color: var(--tc-gold);
  letter-spacing: 0.02em;
}
[data-testid="stCaptionContainer"], .stCaption { color: var(--tc-muted); }

[data-testid="stSidebar"] {
  width: 360px !important;
  min-width: 360px !important;
  max-width: 360px !important;
  background: var(--tc-surface);
  border-right: 1px solid var(--tc-border);
}
[data-testid="stSidebarContent"] {
  width: 360px !important;
  background: transparent;
}
@media (min-width: 768px) {
  [data-testid="stSidebar"] { transform: none !important; }
}
[data-testid="stSidebarUserContent"] {
  padding: 1.25rem 1.1rem 2rem;
}
[data-testid="stSidebarHeader"] {
  display: none;
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stMarkdown p { color: var(--tc-muted); }

[data-testid="stButton"] button {
  border-radius: 10px;
  border: 1px solid var(--tc-border-strong);
  background: transparent;
  color: var(--tc-text);
  font-family: Inter, sans-serif;
  font-weight: 500;
}
[data-testid="stButton"] button:hover {
  border-color: var(--tc-gold);
  color: var(--tc-gold);
}
[data-testid="stButton"] button[kind="primary"] {
  background: var(--tc-gold);
  border-color: var(--tc-gold);
  color: #1a1630;
  font-family: Cinzel, serif;
  font-weight: 700;
}
[data-testid="stButton"] button[kind="primary"]:hover {
  background: #efc46e;
  border-color: #efc46e;
  color: #1a1630;
}
.st-key-goal_row [data-testid="stButton"] button,
.st-key-goal_row [data-testid="stButton"] button * {
  font-family: Cinzel, serif !important;
  font-weight: 700;
  letter-spacing: 0.02em;
}

[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] input,
[data-testid="stTimeInput"] input,
[data-testid="stDateInput"] input {
  background: var(--tc-bg);
  border: 1px solid var(--tc-border);
  border-radius: 8px;
  color: var(--tc-text);
}
[data-testid="stTextArea"] textarea {
  background: var(--tc-surface);
  border-radius: 10px;
  padding: 14px 16px;
  font-size: 16px;
}
[data-testid="stSelectbox"] input,
[data-testid="stSelectbox"] [role="combobox"] {
  background: var(--tc-bg);
  border: 1px solid var(--tc-border);
  border-radius: 8px;
  color: var(--tc-text);
}
[data-testid="stMultiSelectTagsContainer"] {
  background: var(--tc-bg);
  border: 1px solid var(--tc-border);
  border-radius: 8px;
  padding: 4px 6px;
}
[data-testid="stMultiSelectTagsContainer"] [data-tag] {
  background: #2b2540;
  border: 1px solid var(--tc-gold);
  border-radius: 999px;
  color: var(--tc-gold);
  font-size: 13px;
}
[data-testid="stMultiSelect"] input { color: var(--tc-text); }

[data-testid="stTabs"] [role="tablist"] {
  gap: 28px;
  border-bottom: 1px solid var(--tc-border);
  background: transparent;
}
[data-testid="stTabs"] [data-testid="stTab"],
[data-testid="stTabs"] [role="tab"],
[data-testid="stTabs"] [data-baseweb="tab"],
[data-testid="stTabs"] [role="tablist"] button,
[data-testid="stTabs"] [data-testid="stTab"] *,
[data-testid="stTabs"] [role="tab"] *,
[data-testid="stTabs"] [data-baseweb="tab"] *,
[data-testid="stTabs"] [role="tablist"] button * {
  font-family: Cinzel, serif !important;
  font-weight: 700;
  letter-spacing: 0.02em;
}
[data-testid="stTabs"] [data-testid="stTab"],
[data-testid="stTabs"] [role="tab"],
[data-testid="stTabs"] [data-baseweb="tab"],
[data-testid="stTabs"] [role="tablist"] button {
  color: var(--tc-muted);
  background: transparent;
  padding: 8px 2px;
}
[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"],
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color: var(--tc-gold);
  border-bottom: 2px solid var(--tc-gold);
}

[data-testid="stButtonGroup"] [data-variant="pills"] {
  border-radius: 999px;
  border: 1px solid var(--tc-border-strong);
  background: transparent;
  color: var(--tc-muted);
  font-size: 13px;
  padding: 4px 12px;
}
[data-testid="stButtonGroup"] [data-variant="pills"]:hover {
  border-color: var(--tc-gold);
  color: var(--tc-gold);
}
[data-testid="stButtonGroup"] [data-variant="pills"][data-selected],
[data-testid="stButtonGroup"] [data-variant="pills"][aria-selected="true"],
[data-testid="stButtonGroup"] [data-variant="pills"][aria-pressed="true"] {
  background: #2b2540;
  border-color: var(--tc-gold);
  color: var(--tc-gold);
}

[data-testid="stExpander"],
[data-testid="stExpander"] details {
  background: var(--tc-surface);
  border: 1px solid var(--tc-border);
  border-radius: 12px;
}
[data-testid="stExpander"] summary {
  font-family: Cinzel, serif;
  color: var(--tc-text);
}
[data-testid="stMetric"] {
  background: var(--tc-surface);
  border: 1px solid var(--tc-border);
  border-radius: 12px;
  padding: 14px 16px;
}
[data-testid="stMetricValue"] { font-family: Cinzel, serif; color: var(--tc-gold); }
[data-testid="stAlert"] {
  border-radius: 12px;
  border: 1px solid var(--tc-border);
  background: var(--tc-card);
}
[data-testid="stAlertContainer"] {
  background: var(--tc-card) !important;
  border: 1px solid var(--tc-border) !important;
  border-radius: 12px;
}

.tc-brand-name {
  font-family: Cinzel, serif;
  font-weight: 700;
  font-size: 22px;
  letter-spacing: 0.04em;
  color: var(--tc-gold);
}
.tc-brand-tag { color: var(--tc-muted); font-size: 13px; }

.tc-time-card {
  background: var(--tc-card);
  border: 1px solid var(--tc-border);
  border-radius: 14px;
  padding: 12px 14px;
  margin: 4px 0 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.tc-time-head { display: flex; justify-content: space-between; align-items: baseline; }
.tc-time-label {
  font-family: Cinzel, serif;
  font-size: 12px;
  letter-spacing: 0.06em;
  color: var(--tc-muted);
}
.tc-time-value { font-family: Cinzel, serif; font-size: 26px; color: var(--tc-gold); }
.tc-time-value small { font-size: 13px; color: var(--tc-teal); }
.tc-daybar { display: flex; gap: 6px; }
.tc-daybar span { flex: 1; height: 8px; border-radius: 4px; background: var(--tc-border); }
.tc-daybar span.on { background: var(--tc-gold); }
.tc-daylabels {
  display: flex;
  justify-content: space-between;
  color: var(--tc-muted);
  font-size: 12px;
}
.tc-daylabels .on { color: var(--tc-gold); font-weight: 600; }
.tc-time-caption { color: var(--tc-muted); font-size: 12px; }

.tc-fairy { display: flex; gap: 10px; align-items: center; }
.tc-fairy-figure { position: relative; width: 96px; height: 72px; flex: none; }
.tc-fairy-wings { position: absolute; inset: 0; width: 96px; height: 72px; }
.tc-fairy-orb {
  position: absolute;
  left: 30px;
  top: 26px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: radial-gradient(circle at 50% 50%, #ffffff 0%, #fff3a0 30%,
    #f5d142 62%, rgba(245, 209, 66, 0.15) 100%);
  box-shadow: 0 0 22px 8px rgba(245, 209, 66, 0.5);
}
.tc-fairy-bubble {
  flex: 1;
  padding: 14px 18px;
  border-radius: 4px 16px 16px 16px;
  background: #12302f;
  border: 1px solid var(--tc-teal);
}
.tc-fairy-name {
  font-family: Cinzel, serif;
  font-weight: 700;
  color: var(--tc-teal);
  font-size: 14px;
  letter-spacing: 0.08em;
}
.tc-fairy-text { color: var(--tc-text); }

.tc-panel {
  background: var(--tc-surface);
  border: 1px solid var(--tc-border);
  border-radius: 14px;
  padding: 14px 16px;
  margin: 6px 0 14px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.tc-panel-title {
  font-family: Cinzel, serif;
  font-size: 13px;
  letter-spacing: 0.1em;
  color: var(--tc-muted);
}
.tc-live-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 2px 0 12px;
  color: var(--tc-gold);
  font-family: Cinzel, serif;
  font-size: 15px;
}
.tc-live-dot {
  width: 9px;
  height: 9px;
  flex: none;
  border-radius: 50%;
  background: var(--tc-gold);
  animation: tc-pulse 1.6s ease-out infinite;
}
@keyframes tc-pulse {
  0% { box-shadow: 0 0 0 0 rgba(245, 209, 66, 0.5); }
  70% { box-shadow: 0 0 0 8px rgba(245, 209, 66, 0); }
  100% { box-shadow: 0 0 0 0 rgba(245, 209, 66, 0); }
}
.tc-registry-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.tc-registry-hint { font-size: 12px; color: var(--tc-muted); margin-top: -8px; }
.tc-registry { display: flex; flex-direction: column; gap: 8px; }
.tc-reg {
  border: 1px solid var(--tc-border);
  border-radius: 10px;
  background: var(--tc-card);
  overflow: hidden;
}
.tc-reg.bad { border-color: rgba(224, 90, 90, 0.55); }
.tc-reg.running { border-color: rgba(245, 209, 66, 0.55); }
.tc-reg > summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  list-style: none;
  cursor: pointer;
}
.tc-reg > summary::-webkit-details-marker { display: none; }
.tc-reg[open] > summary { border-bottom: 1px solid var(--tc-border); }
.tc-reg-dot {
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
  background: var(--tc-teal);
}
.tc-reg.bad .tc-reg-dot { background: var(--tc-red); }
.tc-reg.running .tc-reg-dot {
  background: var(--tc-gold);
  animation: tc-pulse 1.6s ease-out infinite;
}
.tc-reg-main { flex: 1; min-width: 0; }
.tc-reg-name {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-weight: 600;
}
.tc-reg-sub { font-size: 12px; color: var(--tc-muted); }
.tc-reg-engine,
.tc-reg-attempt {
  padding: 1px 8px;
  border-radius: 5px;
  border: 1px solid var(--tc-border-strong);
  color: var(--tc-muted);
  font-size: 11px;
  font-weight: 500;
}
.tc-reg-attempt { border-color: var(--tc-gold); color: var(--tc-gold); }
.tc-reg-right { flex: none; max-width: 52%; text-align: right; }
.tc-reg-result {
  overflow: hidden;
  font-size: 12px;
  color: var(--tc-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tc-reg.running .tc-reg-result { color: var(--tc-gold); }
.tc-reg-time { font-size: 11px; color: var(--tc-muted); }
.tc-chev { color: var(--tc-muted); transition: transform 0.15s; }
.tc-reg[open] .tc-chev { transform: rotate(180deg); }
.tc-reg-body { padding: 12px 14px 14px; font-size: 13px; }
.tc-reg-body ul { margin: 0; padding-left: 18px; }
.tc-reg-body li { margin: 3px 0; }
.tc-reg-activity { color: var(--tc-muted); }
.tc-reg-activity ul {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}
.tc-reg-activity li { color: var(--tc-muted); }
.tc-reg-activity li.current { color: var(--tc-gold); }
.tc-reg-activity .tc-ev { display: inline-block; width: 16px; }
.tc-reg-kv { display: flex; flex-wrap: wrap; gap: 4px 16px; color: var(--tc-muted); }
.tc-reg-issues-box {
  padding: 12px 14px;
  border-radius: 10px;
  background: #2a1a24;
  border: 1px solid var(--tc-red);
}
.tc-reg-issue-head { color: #f0b5a8; margin-bottom: 6px; }
.tc-reg-stop { color: var(--tc-muted); }
.tc-problems-pill {
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid var(--tc-red);
  background: rgba(224, 90, 90, 0.12);
  color: var(--tc-red);
  font-size: 12px;
  white-space: nowrap;
}

.tc-badges { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.tc-badges-label { font-size: 12px; color: var(--tc-muted); }
.tc-badge {
  padding: 2px 10px;
  border-radius: 6px;
  border: 1px solid var(--tc-teal);
  color: var(--tc-teal);
  font-size: 12px;
}
.tc-badge.gold { border-color: var(--tc-gold); color: var(--tc-gold); }
.tc-badge.red { border-color: var(--tc-red); color: var(--tc-red); }
.tc-badges span:last-child { font-size: 12px; color: var(--tc-muted); }

.tc-verdict {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  border-radius: 12px;
  background: #12302f;
  border: 1px solid var(--tc-teal);
}
.tc-verdict.fail { background: #2a1a24; border-color: var(--tc-red); }
.tc-verdict-icon { font-size: 22px; color: var(--tc-teal); }
.tc-verdict.fail .tc-verdict-icon { color: var(--tc-red); }
.tc-verdict-title {
  font-family: Cinzel, serif;
  font-weight: 700;
  color: var(--tc-teal);
  font-size: 17px;
}
.tc-verdict.fail .tc-verdict-title { color: var(--tc-red); }
.tc-verdict-body { font-size: 13px; color: #b9e5e0; }
.tc-verdict.fail .tc-verdict-body { color: #f0b5a8; }

.tc-issues-table { display: flex; flex-direction: column; }
.tc-issue-row {
  display: grid;
  grid-template-columns: 86px 108px 80px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  padding: 8px 0;
  border-top: 1px solid var(--tc-border);
  font-size: 13px;
}
.tc-issue-head {
  padding: 4px 0;
  border-top: 0;
  color: var(--tc-muted);
  font-size: 11px;
  letter-spacing: 0.06em;
}
.tc-sev-tag,
.tc-kind-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
}
.tc-sev-tag.error { background: #3a1c26; color: #f0757a; }
.tc-sev-tag.warning { background: #3a3320; color: var(--tc-gold); }
.tc-kind-tag { background: #14305a; color: #7ab8ff; }
.tc-issue-step { font-weight: 600; }
.tc-problems-panel {
  padding: 16px 20px;
  border-radius: 14px;
  background: var(--tc-surface);
  border: 1px solid var(--tc-border);
}
.tc-problems-panel .tc-issues-table { margin-top: 6px; }
.tc-missing-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.tc-missing-chip {
  padding: 2px 10px;
  border-radius: 6px;
  border: 1px solid var(--tc-red);
  background: #1b2046;
  color: #f0b5a8;
  font-size: 12px;
}

.tc-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 56px 24px;
  border-radius: 14px;
  border: 1px dashed var(--tc-border-strong);
  background: var(--tc-surface);
  text-align: center;
}
.tc-empty-icon { color: var(--tc-gold); }
.tc-empty-title {
  font-family: Cinzel, serif;
  font-weight: 700;
  font-size: 20px;
  color: var(--tc-gold);
}
.tc-empty-body { max-width: 460px; color: var(--tc-muted); }

.tc-timeline { display: flex; flex-direction: column; }
.tc-step { display: flex; gap: 18px; }
.tc-step-time { width: 92px; flex: none; text-align: right; padding-top: 14px; }
.tc-step-hour { font-family: Cinzel, serif; font-weight: 700; }
.tc-step-day { font-size: 12px; color: var(--tc-muted); }
.tc-step-rail {
  width: 14px;
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.tc-dot {
  width: 12px;
  height: 12px;
  margin-top: 18px;
  border-radius: 50%;
  background: var(--tc-gold);
  flex: none;
}
.tc-line { flex: 1; width: 2px; background: var(--tc-border); min-height: 16px; }
.tc-step:last-child .tc-line { display: none; }
.tc-step-card {
  flex: 1;
  margin-bottom: 12px;
  padding: 14px 18px;
  border-radius: 12px;
  background: var(--tc-surface);
  border: 1px solid var(--tc-border);
}
.tc-step-title { font-weight: 600; }
.tc-step-meta { font-size: 13px; color: var(--tc-muted); }
.tc-step.last .tc-step-hour { color: var(--tc-red); }
.tc-step.last .tc-dot { background: var(--tc-red); }
.tc-step.last .tc-step-card { background: #2a1a24; border-color: var(--tc-red); }
.tc-step.last .tc-step-meta { color: #f0b5a8; }
.tc-step.bad .tc-step-hour { color: var(--tc-red); }
.tc-step.bad .tc-dot { background: var(--tc-red); }
.tc-step.bad .tc-step-card { background: #2a1a24; border-color: var(--tc-red); }
.tc-step.bad .tc-step-meta { color: #f0b5a8; }

@media (max-width: 700px) {
  .tc-step-time { width: 64px; }
}
"""


def _html_block(markup: str) -> None:
    """Draw trusted HTML markup into the page."""
    st.markdown(markup, unsafe_allow_html=True)


def _inject_styles() -> None:
    """Install the Majora's Mask theme once per script run."""
    _html_block(f"<style>{_THEME_CSS}</style>")


def _hours_left(day: int, internal_hour: int, minute: int) -> int:
    """Return the whole hours left before the cycle ends (Day 3 29:59)."""
    elapsed = (day - 1) * 1440 + (internal_hour - 6) * 60 + minute
    return max(0, (3 * 1440 - elapsed) // 60)


def _brand_html() -> str:
    """Return the sidebar brand block."""
    return (
        '<div class="tc-brand">'
        '<div class="tc-brand-name">TaIA</div>'
        f'<div class="tc-brand-tag">{html.escape(t("brand_tagline"))}</div>'
        "</div>"
    )


def _time_card_html(day: int, value: datetime.time) -> str:
    """Return the sidebar "time left" card for the selected game time."""
    hour = _internal_hour(value.hour)
    suffix = " <small>(+1)</small>" if hour >= 24 else ""
    display = f"{value.hour:02d}:{value.minute:02d}"
    bars = "".join(f'<span class="{"on" if n == day else ""}"></span>' for n in (1, 2, 3))
    labels = "".join(
        f'<span class="{"on" if n == day else ""}">{html.escape(t("day_n", n=n))}</span>'
        for n in (1, 2, 3)
    )
    return (
        '<div class="tc-time-card">'
        '<div class="tc-time-head">'
        f'<span class="tc-time-label">{html.escape(t("time_left_label"))}</span>'
        f'<span class="tc-time-value">{display}{suffix}</span>'
        "</div>"
        f'<div class="tc-daybar">{bars}</div>'
        f'<div class="tc-daylabels">{labels}</div>'
        f'<div class="tc-time-caption">{html.escape(t("time_left_caption", day=day))}</div>'
        "</div>"
    )


def _empty_plan_html() -> str:
    """Return the dashed empty-state card shown before the first plan."""
    return (
        '<section class="tc-empty">'
        '<svg class="tc-empty-icon" width="40" height="40" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<circle cx="12" cy="12" r="9"></circle>'
        '<path d="M12 7v5l3 2"></path></svg>'
        f'<div class="tc-empty-title">{html.escape(t("empty_plan_title"))}</div>'
        f'<div class="tc-empty-body">{html.escape(t("empty_plan_body"))}</div>'
        "</section>"
    )


def _fairy_html(day: int, value: datetime.time) -> str:
    """Return TaIA's greeting bubble with the hours left in the cycle."""
    hours = _hours_left(day, _internal_hour(value.hour), value.minute)
    wings = (
        '<svg class="tc-fairy-wings" viewBox="0 0 96 72" aria-hidden="true">'
        '<defs><linearGradient id="taiaw" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#bfe6f2" stop-opacity="0.75"></stop>'
        '<stop offset="1" stop-color="#fff3a0" stop-opacity="0.75"></stop>'
        "</linearGradient></defs>"
        '<path d="M40 38C28 30 16 16 12 3C26 8 38 22 40 38Z" fill="url(#taiaw)" '
        'stroke="#8fb8c4" stroke-width="1" stroke-linejoin="round" '
        'stroke-linecap="round"></path>'
        '<path d="M39 35C29 25 21 14 14 5" fill="none" stroke="#8fb8c4" '
        'stroke-width="0.9" stroke-linecap="round"></path>'
        '<path d="M56 38C68 30 80 16 84 3C70 8 58 22 56 38Z" fill="url(#taiaw)" '
        'stroke="#8fb8c4" stroke-width="1" stroke-linejoin="round" '
        'stroke-linecap="round"></path>'
        '<path d="M57 35C67 25 75 14 82 5" fill="none" stroke="#8fb8c4" '
        'stroke-width="0.9" stroke-linecap="round"></path>'
        '<path d="M38 47C29 44 21 47 13 54C23 57 33 55 38 47Z" fill="url(#taiaw)" '
        'stroke="#8fb8c4" stroke-width="1" stroke-linejoin="round" '
        'stroke-linecap="round"></path>'
        '<path d="M58 47C67 44 75 47 83 54C73 57 63 55 58 47Z" fill="url(#taiaw)" '
        'stroke="#8fb8c4" stroke-width="1" stroke-linejoin="round" '
        'stroke-linecap="round"></path>'
        '<circle cx="70" cy="60" r="3.5" fill="none" stroke="#f5d142" '
        'stroke-width="1.2"></circle>'
        '<circle cx="80" cy="66" r="2.2" fill="#f5d142"></circle>'
        '<circle cx="88" cy="56" r="1.8" fill="#fff3a0"></circle>'
        "</svg>"
    )
    return (
        '<section class="tc-fairy">'
        '<div class="tc-fairy-figure" aria-hidden="true">'
        f"{wings}"
        '<span class="tc-fairy-orb"></span>'
        "</div>"
        '<div class="tc-fairy-bubble">'
        '<div class="tc-fairy-name">TaIA</div>'
        f'<div class="tc-fairy-text">{html.escape(t("fairy_greeting", hours=hours))}</div>'
        "</div></section>"
    )


_AGENT_SUBTITLE_KEY = {
    "state": "agent_card_state",
    "knowledge": "agent_card_knowledge",
    "plan": "agent_card_plan",
    "critic": "agent_card_critic",
}


def _rag_badges_html(result: dict) -> str:
    """Return the wiki-evidence badge row for a finished or running run."""
    status = result.get("retrieval_status") or ""
    if not status:
        return ""
    if status == "unavailable":
        tone = "red"
    elif status in {"wiki_ingested", "wiki_miss"}:
        tone = "gold"
    else:
        tone = ""
    badges = f'<span class="tc-badge {tone}">{html.escape(status)}</span>'
    sources = result.get("retrieval_indexed_sources") or []
    if sources:
        badges += f"<span>{html.escape(t('indexed_pages_n', n=len(sources)))}</span>"
    return (
        '<div class="tc-badges">'
        f'<span class="tc-badges-label">{html.escape(t("wiki_evidence"))}</span>'
        f"{badges}</div>"
    )


def _plain_clock(clock) -> str:
    """Format a clock for HTML text without markdown code spans."""
    suffix = " (+1)" if clock.next_morning else ""
    return f"{t('day_n', n=clock.day)}, {clock.display_hour:02d}:{clock.minute:02d}{suffix}"


def _registry_rows(task: _PlanningTask) -> list[dict]:
    """Pair each streamed agent start with its progress, update and duration."""
    rows: list[dict] = []
    for index, entry in enumerate(task.log):
        kind = entry[0]
        if kind not in {"start", "update", "progress"}:
            continue
        if kind == "progress":
            payload = entry[1]
            if not isinstance(payload, dict):
                continue
            node = payload.get("node", "")
            if node not in _AGENT_LABEL_KEY:
                continue
            target = next((row for row in reversed(rows) if row["node"] == node), None)
            if target is not None:
                target["events"].append(payload)
            continue
        node = entry[1]
        if node not in _AGENT_LABEL_KEY:
            continue
        if kind == "start":
            rows.append({"node": node, "data": None, "seconds": None, "events": []})
            continue
        data = entry[2] if len(entry) > 2 else None
        if not isinstance(data, dict):
            continue
        target = next(
            (row for row in reversed(rows) if row["node"] == node and row["data"] is None),
            None,
        )
        if target is None:
            target = {"node": node, "data": None, "seconds": None, "events": []}
            rows.append(target)
        target["data"] = data
        target["seconds"] = task.timings.get(index)
    return rows


def _registry_activity_html(events: list[dict], running: bool) -> str:
    """Return the live activity timeline for one agent row."""
    lines = [line for line in (_plain_progress(_progress_line(event)) for event in events) if line]
    if not lines:
        return ""
    items = []
    for index, line in enumerate(lines):
        current = running and index == len(lines) - 1
        marker = "\u23f3" if current else "\u2713"
        tone = "current" if current else "done"
        items.append(
            f'<li class="{tone}"><span class="tc-ev">{marker}</span> {html.escape(line)}</li>'
        )
    return (
        '<div class="tc-reg-activity">'
        f'<div class="tc-panel-title">{html.escape(t("activity"))}</div>'
        f"<ul>{''.join(items)}</ul></div>"
    )


def _registry_live_summary(events: list[dict]) -> str:
    """Return the current progress line (or a starting hint) for a live row."""
    for event in reversed(events):
        line = _progress_line(event)
        if line:
            return _plain_progress(line)
    return t("agent_starting")


def _registry_engine_html(node: str, data: dict) -> str:
    """Return the engine chip for one registry row."""
    engine, model = _engine_for(node, data)
    if not engine:
        return ""
    label = _ENGINE_LABELS.get(engine, engine)
    if model:
        label = f"{label} · {model}"
    return f'<span class="tc-reg-engine">{html.escape(label)}</span>'


def _registry_state_summary(data: dict) -> str:
    """Return the one-line State Agent result shown in the row header."""
    gs = data.get("game_state")
    if gs is None:
        return ""
    return t(
        "registry_state_summary",
        when=_plain_clock(gs.time),
        where=tr(gs.location),
        masks=len(gs.masks),
        items=len(gs.inventory),
    )


def _registry_plan_summary(data: dict) -> str:
    """Return the one-line Planning Agent result shown in the row header."""
    plan = data.get("plan")
    if not plan or not plan.steps:
        return t("no_plan")
    return t("registry_plan_steps", n=len(plan.steps))


def _registry_critic_summary(data: dict) -> str:
    """Return the one-line Critic result shown in the row header."""
    validation = data.get("validation")
    if validation is None:
        return ""
    if validation.valid:
        return t("plan_valid")
    return t("registry_issue_count", n=len(validation.issues))


def _registry_state_body(data: dict) -> str:
    """Return the expanded State Agent body."""
    gs = data.get("game_state")
    if gs is None:
        return ""
    items = ", ".join(tr(item) for item in gs.inventory) or t("trace_none")
    masks = ", ".join(tr(mask) for mask in gs.masks) or t("trace_none")
    return (
        '<div class="tc-reg-kv">'
        f"<span><b>{html.escape(t('trace_items'))}</b> {html.escape(items)}</span>"
        f"<span><b>{html.escape(t('trace_masks'))}</b> {html.escape(masks)}</span>"
        "</div>"
    )


def _registry_knowledge_body(data: dict) -> str:
    """Return the expanded Knowledge Agent body, including RAG badges."""
    objectives = data.get("relevant_objectives") or []
    if objectives:
        items = "".join(f"<li>{html.escape(tr(obj.title))}</li>" for obj in objectives)
        body = f"<ul>{items}</ul>"
    else:
        body = f'<div class="tc-reg-kv">{html.escape(t("knowledge_empty_hint"))}</div>'
    return body + _rag_badges_html(data)


def _registry_plan_body(data: dict) -> str:
    """Return the expanded Planning Agent body as a compact step list."""
    plan = data.get("plan")
    if not plan or not plan.steps:
        return f'<div class="tc-reg-kv">{html.escape(t("no_plan"))}</div>'
    items = "".join(
        f"<li>{index}. {html.escape(tr(step.title))} "
        f'<span class="tc-reg-time">{html.escape(_fmt_window(step.window))}</span></li>'
        for index, step in enumerate(plan.steps, 1)
    )
    return f"<ul>{items}</ul>"


def _registry_critic_body(data: dict) -> str:
    """Return the expanded Critic body with its issues."""
    validation = data.get("validation")
    if validation is None:
        return ""
    if validation.valid:
        return f'<div class="tc-reg-kv">{html.escape(t("plan_valid"))}</div>'
    stop = (
        f'<span class="tc-reg-stop">{html.escape(t("registry_stop_here"))}</span>'
        if len(data.get("attempt_log") or []) >= MAX_PLANNING_ATTEMPTS
        else ""
    )
    head = t("replan_line", n=len(validation.issues), max=MAX_PLANNING_ATTEMPTS)
    return (
        '<div class="tc-reg-issues-box">'
        f'<div class="tc-reg-issue-head">{html.escape(head)}{stop}</div>'
        f"{_issues_table_html(validation.issues)}"
        f"{_missing_chips_html(validation.issues, prefix=True)}"
        "</div>"
    )


def _registry_body(
    node: str, data: dict, *, events: list[dict] | None = None, live: bool = False
) -> str:
    """Dispatch the expanded body for one registry row."""
    if data:
        if node == "state":
            return _registry_state_body(data)
        if node == "knowledge":
            return _registry_knowledge_body(data)
        if node == "plan":
            return _registry_plan_body(data)
        if node == "critic":
            return _registry_critic_body(data)
        return ""
    return _registry_activity_html(events or [], running=live)


def _registry_summary(
    node: str, data: dict, *, events: list[dict] | None = None, live: bool = False
) -> str:
    """Dispatch the one-line result for one registry row."""
    if not data:
        if live:
            return _registry_live_summary(events or [])
        lines = [line for line in (_progress_line(event) for event in events or []) if line]
        return _plain_progress(lines[-1]) if lines else ""
    if node == "state":
        return _registry_state_summary(data)
    if node == "knowledge":
        return t("knowledge_objectives", n=len(data.get("relevant_objectives") or []))
    if node == "plan":
        return _registry_plan_summary(data)
    if node == "critic":
        return _registry_critic_summary(data)
    return ""


def _agent_registry_html(task: _PlanningTask, live: bool = False) -> str:
    """Return the agent registry, shared by live and finished runs."""
    rows = _registry_rows(task)
    if not rows:
        return ""
    validation = task.result.get("validation")
    error_count = (
        len([issue for issue in validation.issues if issue.severity == "error"])
        if validation is not None and not validation.valid
        else 0
    )
    pill = ""
    if error_count:
        pill = (
            '<span class="tc-problems-pill">'
            f"{html.escape(t('problems_count', n=error_count))}</span>"
        )
    cards = []
    plan_attempt = 0
    last = len(rows) - 1
    for index, row in enumerate(rows):
        node = row["node"]
        data = row["data"] or {}
        running = live and row["data"] is None
        attempt = None
        if node == "plan":
            plan_attempt = int(data.get("replan_attempts") or plan_attempt + 1)
            attempt = plan_attempt
        elif node == "critic" and plan_attempt:
            attempt = plan_attempt
        bad = (
            node == "critic" and data.get("validation") is not None and not data["validation"].valid
        )
        attempt_chip = ""
        if attempt is not None:
            attempt_chip = (
                '<span class="tc-reg-attempt">'
                f"{html.escape(t('step_attempt', n=attempt, max=MAX_PLANNING_ATTEMPTS))}"
                "</span>"
            )
        seconds = row["seconds"]
        duration = f'<div class="tc-reg-time">{seconds:.1f}s</div>' if seconds is not None else ""
        classes = "tc-reg"
        if bad:
            classes += " bad"
        if running:
            classes += " running"
        summary = _registry_summary(node, data, events=row["events"], live=live)
        body = _registry_body(node, data, events=row["events"], live=running)
        cards.append(
            f'<details class="{classes}"{" open" if index == last else ""}>'
            "<summary>"
            '<span class="tc-reg-dot"></span>'
            '<div class="tc-reg-main">'
            f'<div class="tc-reg-name">{html.escape(t(_AGENT_LABEL_KEY[node]))}'
            f"{_registry_engine_html(node, data)}{attempt_chip}</div>"
            f'<div class="tc-reg-sub">{html.escape(t(_AGENT_SUBTITLE_KEY[node]))}</div>'
            "</div>"
            '<div class="tc-reg-right">'
            f'<div class="tc-reg-result">{html.escape(summary)}</div>'
            f"{duration}</div>"
            '<span class="tc-chev" aria-hidden="true">⌄</span>'
            "</summary>"
            f'<div class="tc-reg-body">{body}</div>'
            "</details>"
        )
    hint = t("agent_registry_live_hint") if live else t("agent_registry_hint")
    return (
        '<section class="tc-panel">'
        '<div class="tc-registry-head">'
        f'<div class="tc-panel-title">{html.escape(t("agents_title"))}</div>'
        f"{pill}</div>"
        f'<div class="tc-registry-hint">{html.escape(hint)}</div>'
        f'<div class="tc-registry">{"".join(cards)}</div>'
        "</section>"
    )


def _verdict_html(valid: bool, title: str, body: str, extra_html: str = "") -> str:
    """Return the Critic's verdict banner."""
    cls = "" if valid else " fail"
    icon = "\u2713" if valid else "\u2717"
    return (
        f'<section class="tc-verdict{cls}">'
        f'<div class="tc-verdict-icon" aria-hidden="true">{icon}</div>'
        f'<div><div class="tc-verdict-title">{html.escape(title)}</div>'
        f'<div class="tc-verdict-body">{html.escape(body)}</div>'
        f"{extra_html}</div></section>"
    )


def _render_configuration() -> None:
    """Show the read-only configuration loaded from the environment.

    Display only: the key settings come from environment variables (and
    ``.env``), never from the sidebar. Only the essentials are shown; the full
    contract lives in ``app/settings.py``.

    args:
        (none)

    returns:
        None: renders the configuration half of the sidebar.
    """
    settings = get_settings()
    provider = settings.llm_provider or ""
    base_url = settings.llm_base_url or ""

    _section(t("llm_settings"))
    if provider:
        model = settings.llm_model or default_model_for(provider)
        st.markdown(f"- **{t('llm_provider')}**: `{provider}`")
        if model:
            st.markdown(f"- **{t('llm_model')}**: `{model}`")
        if base_url:
            st.markdown(f"- **LLM_BASE_URL**: `{base_url}`")
        if provider in {"ollama", "lmstudio"} and base_url and urlsplit(base_url).path in {"", "/"}:
            st.warning(t("llm_base_url_hint"))
    else:
        st.warning(
            "LLM not configured. Set LLM_PROVIDER (and credentials) in .env (see .env.example)."
        )

    st.divider()
    _section(t("runtime_config"))
    rag = settings.rag
    retrieval = t("state_on") if rag.enabled else t("state_off")
    st.markdown(f"- **{t('rag_retrieval')}**: `{retrieval}`")
    st.markdown(f"- **{t('rag_embedding_model')}**: `{rag.embedding_model}`")
    if settings.tracing_enabled:
        st.markdown(f"- **{t('phoenix_url')}**: [Open \u2197]({settings.phoenix_ui_url})")
    else:
        st.markdown(f"- **{t('phoenix_url')}**: `None`")


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
        initial_sidebar_state="expanded",
    )
    _inject_styles()
    kb = build_default_knowledge()

    with st.sidebar:
        editor = _render_sidebar_editor(kb)
        st.divider()
        _section(t("save_load"))
        col_s, col_l = st.columns(2)
        with col_s:
            if st.button(t("save_button"), use_container_width=True):
                goal_val = st.session_state.get("save_goal", "")
                tm_val = st.session_state.get("save_time") or _datetime.time(6, 0)
                day_val = int(st.session_state.get("save_day", 1))
                hour_val = _internal_hour(tm_val.hour)
                data = {
                    "version": 2,
                    "day": day_val,
                    "time": {"day": day_val, "hour": hour_val, "minute": tm_val.minute},
                    "location": st.session_state.get("save_location") or "South Clock Town",
                    "masks": list(st.session_state.get("save_masks") or []),
                    "inventory": list(st.session_state.get("save_inventory") or []),
                    "quest_progress": list(st.session_state.get("save_quests") or []),
                    "goal": goal_val or "",
                }
                try:
                    _ = save_state(data)
                    st.success(t("save_ok"))
                except Exception as exc:
                    st.error(str(exc))
        with col_l:
            if st.button(t("load_button"), use_container_width=True):
                snapshot = load_state()
                if not snapshot:
                    st.warning(t("load_none"))
                else:
                    try:
                        st.session_state["save_day"] = int(snapshot.time.day)
                        st.session_state["save_time"] = _datetime.time(
                            snapshot.time.display_hour, snapshot.time.minute
                        )
                        if snapshot.migration_warning:
                            st.session_state["_save_warning"] = snapshot.migration_warning
                        if snapshot.location:
                            st.session_state["save_location"] = snapshot.location
                        st.session_state["save_masks"] = list(snapshot.masks)
                        st.session_state["save_inventory"] = list(snapshot.inventory)
                        st.session_state["save_quests"] = list(snapshot.quest_progress)
                        st.session_state["save_goal"] = snapshot.goal or ""
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
        save_warning = st.session_state.pop("_save_warning", "")
        if save_warning:
            st.warning(save_warning)
        _render_configuration()

    tab_play, tab_evaluation = st.tabs([t("tab_play"), t("tab_evaluation")])
    with tab_play:
        _render_play(editor, kb)
    with tab_evaluation:
        _render_evaluation()


def _render_sidebar_editor(kb) -> dict:
    """Render the Majora's Mask state editor in the sidebar.

    Returns the values the Play tab needs to build a ``GameState``. The
    widgets own their session-state keys, so the time card and the fairy
    greeting can read the previous run's values before the widgets exist.

    args:
        kb (KnowledgeBase): the knowledge base used for the location and item
            options.

    returns:
        dict: the selected day, time, location, masks, inventory and quests.
    """
    _html_block(_brand_html())
    st.selectbox(t("language"), list(_LANGS), key="lang", format_func=lambda c: _LANGS[c])
    day = int(st.session_state.get("save_day", 1))
    when = st.session_state.get("save_time") or datetime.time(6, 0)
    _html_block(_time_card_html(day, when))

    locations = sorted({loc.name for loc in kb.locations})
    default_loc = "South Clock Town"
    current_loc = st.session_state.get("save_location", default_loc)
    idx = locations.index(current_loc) if current_loc in locations else 0
    location = st.selectbox(
        t("sidebar_location"),
        locations or ["Termina Field"],
        index=idx,
        format_func=tr,
        key="save_location",
    )

    c1, c2 = st.columns([1, 1])
    with c1:
        day = st.selectbox(t("day"), [1, 2, 3], index=0, key="save_day")
    with c2:
        when = st.time_input(t("time"), datetime.time(6, 0), step=60, key="save_time")
    st.caption(_time_label(day, when))

    masks = st.multiselect(
        t("sidebar_masks"),
        list(MASKS),
        default=list(st.session_state.get("save_masks") or []),
        format_func=tr,
        help=t("masks_help"),
        placeholder=t("select_placeholder"),
        key="save_masks",
    )
    item_options = sorted(
        {i for quest in kb.quests for o in quest.objectives for i in o.requires_items}
    )
    # Custom items enter through the input below the pills; the add is
    # applied at the start of the next run, before the widgets exist, so
    # save_inventory/save_inventory_new are only written pre-instantiation.
    pending_add = st.session_state.pop("_inventory_add_pending", None)
    if pending_add:
        current = list(st.session_state.get("save_inventory") or [])
        if pending_add not in current:
            st.session_state["save_inventory"] = [*current, pending_add]
        st.session_state["save_inventory_new"] = ""
    # The multiselect renders only options: merge the current selection so
    # custom items (typed or loaded from a save) stay visible and removable.
    owned_now = st.session_state.get("save_inventory") or []
    inventory_options = sorted(set(item_options) | set(owned_now))
    inventory = st.multiselect(
        t("sidebar_items"),
        inventory_options or ["Hookshot"],
        default=list(owned_now),
        format_func=tr,
        help=t("inventory_help"),
        placeholder=t("select_placeholder"),
        key="save_inventory",
    )
    st.text_input(t("inventory_add"), key="save_inventory_new")
    if st.button(
        t("inventory_add_button"),
        use_container_width=True,
        key="save_inventory_add",
    ):
        typed = (st.session_state.get("save_inventory_new") or "").strip()
        if typed:
            st.session_state["_inventory_add_pending"] = typed
            st.rerun()
    quest_names = {q.name: q.id for q in kb.quests}
    done_q = st.multiselect(
        t("quest_progress"),
        list(quest_names),
        default=list(st.session_state.get("save_quests") or []),
        format_func=tr,
        help=t("quest_progress_help"),
        placeholder=t("select_placeholder"),
        key="save_quests",
    )
    return {
        "day": day,
        "time": when,
        "location": location,
        "masks": list(masks or []),
        "inventory": list(inventory or []),
        "quests": list(done_q or []),
        "quest_names": quest_names,
    }


def _render_play(editor: dict, kb) -> None:
    """Render the play tab: TaIA greeting, goal, agent cards and plan.

    args:
        editor (dict): the sidebar state editor's values.
        kb (KnowledgeBase): the knowledge base used to render sources.

    returns:
        None: renders the planning half of the app page.
    """
    _html_block(_fairy_html(editor["day"], editor["time"]))
    task = st.session_state.get(_PLANNING_TASK_KEY)
    with st.container(key="goal_row"):
        goal_col, ask_col, stop_col = st.columns([7, 2, 1], vertical_alignment="bottom")
        with goal_col:
            goal_text = st.text_input(
                t("goal_label"),
                placeholder=t("goal_example"),
                key="save_goal",
            )
        generate_disabled, stop_disabled = _plan_controls_disabled(task)
        if not (goal_text or "").strip():
            generate_disabled = True
        with ask_col:
            run = st.button(
                t("ask_taia"),
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
            time=ClockTime(
                day=editor["day"],
                hour=_internal_hour(editor["time"].hour),
                minute=editor["time"].minute,
            ),
            location=editor["location"],
            inventory=list(editor["inventory"]),
            masks=list(editor["masks"]),
            quest_progress={editor["quest_names"][q]: "done" for q in editor["quests"]},
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
        # Block here, redrawing the registry only on agent updates. The final
        # rerun re-enables Generate/Stop and renders the result below.
        _planning_live(task)
        st.rerun()

    if task is not None:
        _render_planning_progress(task)
        _render_planning_result(task, kb)
        return

    _html_block(_empty_plan_html())


def _render_evaluation() -> None:
    """Render the evaluation tab: scenario picker, run control and results.

    The sweep runs the whole pipeline once per scenario, so it happens in a
    background thread and reports every finished scenario live.

    args:
        (none)

    returns:
        None: renders the evaluation half of the app page.
    """
    _section(t("eval_title"), t("eval_caption"))
    if not get_settings().llm_provider:
        st.warning(t("eval_need_llm"))

    task = st.session_state.get(_EVALUATION_TASK_KEY)
    running = task is not None and task.status in _ACTIVE_STATUSES

    scenario_ids = st.multiselect(
        t("eval_scenarios"),
        options=[scenario.id for scenario in EVALUATION_SCENARIOS],
        default=[scenario.id for scenario in EVALUATION_SCENARIOS],
        format_func=_scenario_label,
        help=t("eval_scenarios_help"),
        key="eval_scenarios",
    )
    rag_on = st.toggle(t("eval_rag"), value=True, help=t("eval_rag_help"), key="eval_rag")

    run_col, stop_col = st.columns([4, 1])
    with run_col:
        run = st.button(
            t("eval_run"),
            type="primary",
            use_container_width=True,
            disabled=running or not scenario_ids,
            key="eval_run_button",
        )
    with stop_col:
        stop = st.button(
            t("eval_stop"),
            use_container_width=True,
            disabled=not running,
            key="eval_stop_button",
        )

    if stop and running:
        task.stop_event.set()
        task.status = "stopping"
        st.rerun()

    if run and not running and scenario_ids:
        _start_evaluation_task(scenario_ids, rag_on)
        st.rerun()

    load_col, hint_col = st.columns([1, 3])
    with load_col:
        load = st.button(t("eval_load_last"), key="eval_load_button")
    with hint_col:
        report_path = _saved_report_path()
        if report_path is not None:
            st.caption(t("eval_saved_report", path=str(report_path)))
    if load:
        saved = load_report()
        if saved is None:
            st.info(t("eval_no_saved_report"))
        else:
            st.session_state[_EVALUATION_REPORT_KEY] = saved

    task = st.session_state.get(_EVALUATION_TASK_KEY)
    if task is not None and task.status in _ACTIVE_STATUSES:
        # Block here, redrawing only when a scenario finishes. The final
        # rerun renders the report below.
        _evaluation_live(task)
        st.rerun()

    if task is not None:
        if task.status == "stopped":
            st.warning(t("eval_stopped"))
        if task.error:
            st.error(task.error)
        _render_evaluation_results(EvaluationReport(results=task.results))
        return

    # No sweep in this session: show the report restored from disk.
    saved = st.session_state.get(_EVALUATION_REPORT_KEY)
    if saved is not None:
        _render_evaluation_results(saved)


if __name__ == "__main__":
    render()
