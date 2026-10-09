"""Minimal Streamlit UI for Termina Companion.

Entry points: ``uv run streamlit run main.py`` (preferred) or
``uv run streamlit run app/ui.py``.
"""

from __future__ import annotations

import datetime
import queue
import re
import threading
from dataclasses import dataclass, field

import streamlit as st

from app.data.mock_knowledge import MASKS, build_default_knowledge
from app.domain import ClockTime, GameState, Goal, TimeWindow
from app.graph import MAX_PLANNING_ATTEMPTS, build_graph
from app.i18n import spinner_lines, t, tr, tr_msg


@st.cache_resource
def _graph():
    """Build (and cache) the compiled LangGraph once per session.

    args:
        (none)

    returns:
        object: the compiled graph.
    """
    return build_graph()


_PROVIDERS = ("openai", "openrouter", "ollama", "lmstudio", "anthropic", "google")

_LANGS = {"en": "\U0001f1ec\U0001f1e7 English", "it": "\U0001f1ee\U0001f1f9 Italiano"}

_PLANNING_TASK_KEY = "_planning_task"
_ACTIVE_STATUSES = frozenset({"running", "stopping"})
_STOP_SENTINEL = object()
_NO_MESSAGE = object()
# Idle wait used by the live progress loop. It only bounds how long we block on
# the worker queue before emitting an invisible yield point, so a queued Stop
# click is handled promptly. It never triggers a redraw on its own.
_IDLE_WAIT = 0.25


@dataclass
class _PlanningTask:
    """Background planning run kept in Streamlit session state."""

    events: queue.Queue[object] = field(default_factory=queue.Queue)
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    status: str = "running"
    result: dict = field(default_factory=dict)
    updates: list[tuple[str, dict]] = field(default_factory=list)
    error: str = ""
    spinner_index: int = 0


def _task_is_active(task: _PlanningTask | None) -> bool:
    """Return whether a planning task is still running or stopping."""
    return task is not None and task.status in _ACTIVE_STATUSES


def _plan_controls_disabled(task: _PlanningTask | None, llm_model: str) -> tuple[bool, bool]:
    """Return the ``(generate, stop)`` disabled flags for the planning controls.

    args:
        task (_PlanningTask | None): the session planning task, if any.
        llm_model (str): the model typed in the sidebar.

    returns:
        tuple[bool, bool]: Generate is disabled while a run is active or no
        model is configured; Stop is enabled only while a run is running, not
        while a stop request is already pending.
    """
    active = _task_is_active(task)
    stopping = task is not None and task.status == "stopping"
    return active or not llm_model.strip(), stopping or not active


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
    try:
        for update in graph.stream(initial, stream_mode="updates"):
            if stop_event.is_set():
                events.put(_STOP_SENTINEL)
                return
            events.put(update)
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
        elif isinstance(item, dict):
            for node, data in item.items():
                if not isinstance(data, dict):
                    continue
                task.result.update(data)
                task.updates.append((node, data))
                # One phase per agent update, so the progress label only moves
                # when the run actually advanced (never once per re-render).
                task.spinner_index += 1
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


def _progress_label(task: _PlanningTask) -> str:
    """Return the current progress-phase label for a run.

    The label is derived from the number of drained agent updates, so it stays
    identical across re-renders and only changes when a new update arrives.

    args:
        task (_PlanningTask): the planning task being rendered.

    returns:
        str: e.g. "Opening the Door of Time...".
    """
    phrases = spinner_lines()
    if not phrases:
        return t("planning")
    return f"{phrases[task.spinner_index % len(phrases)]}..."


def _render_planning_progress(task: _PlanningTask) -> None:
    """Render accumulated agent updates for the current planning run."""
    validation = task.result.get("validation")
    running_label = _progress_label(task)
    if task.status == "done":
        valid = bool(getattr(validation, "valid", False))
        outer_state = "complete" if valid else "error"
        outer_label = (
            t("planning_complete") if valid else t("planning_gave_up", max=MAX_PLANNING_ATTEMPTS)
        )
    elif task.status == "error":
        outer_state = "error"
        outer_label = t("planning_error", error=task.error or "unknown error")
    elif task.status == "stopped":
        outer_state = "error"
        outer_label = t("planning_stopped")
    elif task.status == "stopping":
        outer_state = "running"
        outer_label = t("planning_stopping")
    else:
        outer_state = "running"
        outer_label = running_label

    agent_name = {
        "state": t("agent_state"),
        "knowledge": t("agent_knowledge"),
        "plan": t("agent_planning"),
        "critic": t("agent_critic"),
    }
    with st.status(outer_label, type="step", state=outer_state, expanded=True) as outer:
        for node, _data in task.updates:
            name = agent_name.get(node, node)
            if node == "plan":
                attempt = task.result.get("replan_attempts", 1)
                name += f" — {t('step_attempt', n=attempt, max=MAX_PLANNING_ATTEMPTS)}"
            with st.status(name, type="step", expanded=True) as step:
                _append_step(step, node, task.result)
        if task.status == "running":
            outer.update(label=running_label, state="running", expanded=True)
        elif task.status == "stopping":
            outer.update(label=t("planning_stopping"), state="running", expanded=True)
    if task.status == "error":
        st.error(t("planning_error", error=task.error or "unknown error"))
    elif task.status == "stopped":
        st.warning(t("planning_stopped"))


def _planning_live(task: _PlanningTask) -> None:
    """Render the live stepper, redrawing only when the run actually advances.

    The loop idles on the worker queue instead of on a timer: while the agent is
    thinking no delta is sent, so the stepper does not flicker and a collapsed
    stepper is not re-expanded on its own. The single empty placeholder is an
    invisible yield point, which is what lets Streamlit process a queued Stop
    click while this script is still running.

    args:
        task (_PlanningTask): the active planning task.

    returns:
        None: blocks until the task reaches a terminal state, having drawn the
        stepper once and then once per change.
    """
    _render_planning_progress(task)
    yield_point = st.empty()
    while _task_is_active(task):
        if _drain_planning_task(task, wait=_IDLE_WAIT):
            _render_planning_progress(task)
        else:
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
            indexed_sources=result.get("retrieval_indexed_sources", []),
            ingested_pages=result.get("retrieval_ingested_pages", []),
        )
    with tab_trace:
        st.caption(t("tab_trace_caption"))
        _render_trace_state(result["game_state"])
        _render_trace_attempts(result["replan_attempts"])
        _render_trace_issues(validation)


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
    c.markdown(f"**\u2713 {t('agent_state')}{_engine_badge(result.get('state_engine'))}**")
    c.write(f"{t('trace_where')} {tr(result['game_state'].location)}")
    c.write(result["state_summary"])


def _step_knowledge(status, result: dict) -> None:
    """Render the Knowledge Agent's trace card.

    args:
        status (DeltaGenerator): the trace container.
        result (dict): the knowledge node output with retrieved objectives.

    returns:
        None: draws into the status container.
    """
    c = status.container()
    c.markdown(f"**\u2713 {t('agent_knowledge')}{_engine_badge(result.get('knowledge_engine'))}**")
    objectives = result["relevant_objectives"]
    c.write(t("knowledge_objectives", n=len(objectives)))
    for obj in objectives:
        c.write(f"\u2022 {tr(obj.title)}")
    if not objectives:
        c.caption(t("knowledge_empty_hint"))
    retrieval_engine = result.get("retrieval_engine")
    if retrieval_engine:
        c.caption(f"{t('rag_engine')}: {retrieval_engine}")
    retrieval_status = result.get("retrieval_status")
    if retrieval_status:
        c.caption(f"{t('rag_status')}: {retrieval_status}")
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
    plan = result["plan"]
    attempt = result["replan_attempts"]
    header = (
        f"**\u2713 {t('agent_planning')}"
        f"{_engine_badge(result.get('plan_engine'), result.get('plan_model'))} \u2014 "
        f"{t('step_attempt', n=attempt, max=MAX_PLANNING_ATTEMPTS)}**"
    )
    c.markdown(header)
    if not plan or not plan.steps:
        c.write(t("no_plan"))
        return
    for i, step in enumerate(plan.steps, 1):
        s, e = step.window.start, step.window.end
        window = f"Day {s.day} {s.hour:02d}:{s.minute:02d}\u2013{e.hour:02d}:{e.minute:02d}"
        c.write(f"\u2022 {i}. {tr(step.title)} @ {tr(step.location)} ({window})")


def _step_critic(status, result: dict) -> None:
    """Render the Critic Agent's trace card.

    args:
        status (DeltaGenerator): the trace container.
        result (dict): the critic node output with the validation result.

    returns:
        None: draws into the status container.
    """
    c = status.container()
    c.markdown(f"**\u2713 {t('agent_critic')}{_engine_badge(result.get('critic_engine'))}**")
    validation = result["validation"]
    if validation.valid:
        c.write(f"\u2713 {t('plan_valid')}")
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
    """Format a clock as "Day N HH:MM".

    args:
        t (ClockTime): the time to format.

    returns:
        str: the readable representation.
    """
    return f"Day {t.day} {t.hour:02d}:{t.minute:02d}"


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
    """Render one indexed wiki page and its complete provenance manifest."""
    with st.container(border=True):
        st.markdown(f"**{tr(source.title)}**")
        page_id = source.source_page_id if source.source_page_id is not None else source.id
        if page_id:
            st.caption(f"{t('rag_page_id')}: {page_id}")
        if source.source_revision_id is not None:
            st.caption(
                f"{t('rag_revision')}: {source.source_revision_id} "
                f"({source.source_revision_timestamp or '-'})"
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
            st.caption(f"{t('rag_retrieved_at')}: {source.retrieved_at}")


def _render_rag_ingested_page(title: str) -> None:
    """Render a title-only fallback for legacy ingestion results."""
    with st.container(border=True):
        st.markdown(f"**{tr(title)}**")


def _render_rag_evidence(
    evidence,
    engine: str = "",
    status: str = "",
    warning: str = "",
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
        st.caption(f"{t('rag_engine')}: {engine}")
    if status:
        st.caption(f"{t('rag_status')}: {status}")
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
                    f"({metadata.source_revision_timestamp})"
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
        st.write(f"**{t('trace_where')}** {tr(gs.location)}")
        st.write(f"**{t('trace_when')}** {tr(_fmt_clock(gs.time))}")
        items = ", ".join(tr(x) for x in gs.inventory) or t("trace_none")
        st.write(f"**{t('trace_items')}** {items}")
        masks = ", ".join(tr(x) for x in gs.masks) or t("trace_none")
        st.write(f"**{t('trace_masks')}** {masks}")


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
        llm_provider = st.selectbox(t("llm_provider"), list(_PROVIDERS))
        llm_model = st.text_input(t("llm_model"), placeholder="gpt-4o-mini")
        llm_api_key = st.text_input(t("llm_api_key"), type="password")
        if not llm_model.strip():
            st.caption(t("llm_model_required"))

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
        generate_disabled, stop_disabled = _plan_controls_disabled(task, llm_model)
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

    if run and not _task_is_active(task):
        game_state = GameState(
            time=ClockTime(day=day, hour=tm.hour, minute=tm.minute),
            location=location,
            inventory=list(inventory or []),
            masks=list(masks or []),
            quest_progress={quest_names[q]: "done" for q in (done_q or [])},
        )
        goal = Goal(description=goal_text)

        llm_config: dict[str, str] = {}
        if llm_provider:
            llm_config["provider"] = llm_provider
        if llm_model:
            llm_config["model"] = llm_model
        if llm_api_key:
            llm_config["api_key"] = llm_api_key

        initial = {"game_state": game_state, "goal": goal, "llm_config": llm_config}
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
