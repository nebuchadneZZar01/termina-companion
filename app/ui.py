"""Minimal Streamlit UI for Termina Companion.

Entry points: ``uv run streamlit run main.py`` (preferred) or
``uv run streamlit run app/ui.py``.
"""

from __future__ import annotations

import datetime
import itertools
import queue
import re
import threading
import time

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


_SPINNER_INTERVAL = 3.0


_CSS = """
<style>
.section-title {
    color: #F5B301;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    font-size: 0.9rem;
    border-bottom: 1px solid #33415C;
    padding-bottom: 0.3rem;
    margin: 0.6rem 0 0.6rem 0;
}
.caption-hint {
    color: #8A93A6;
    font-size: 0.82rem;
    margin: -0.2rem 0 0.5rem 0;
}
.step-time {
    color: #F5B301;
    font-weight: 600;
    letter-spacing: 0.04em;
    margin: 0.5rem 0 0.1rem 0;
}
</style>
"""


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


def _engine_badge(engine: str | None) -> str:
    """Format an engine name as a parenthesised badge suffix.

    args:
        engine (str | None): the engine label, e.g. "rule-based".

    returns:
        str: " (engine)" or "" when empty.
    """
    return f" ({engine})" if engine else ""


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
        f"**\u2713 {t('agent_planning')}{_engine_badge(result.get('plan_engine'))} \u2014 "
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
    col_sev.badge(
        (t("sev_error") if is_error else t("sev_warning")).upper(),
        color="red" if is_error else "orange",
    )
    col_kind.badge(kind.upper(), color="blue")
    col_step.markdown(f"**{where}**")
    col_msg.markdown(_markdown_windows(tr_msg(issue.message)))


def _section(title: str, caption: str = "") -> None:
    """Draw a styled section header with optional caption.

    args:
        title (str): the section title.
        caption (str, default ""): optional hint under the title.

    returns:
        None: draws into the app.
    """
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    if caption:
        st.markdown(f'<div class="caption-hint">{caption}</div>', unsafe_allow_html=True)


def _fmt_clock(t: ClockTime) -> str:
    """Format a clock as "Day N HH:MM".

    args:
        t (ClockTime): the time to format.

    returns:
        str: the readable representation.
    """
    return f"Day {t.day} {t.hour:02d}:{t.minute:02d}"


def _time_s(t: ClockTime) -> str:
    """Format a clock as "HH:MM".

    args:
        t (ClockTime): the time to format.

    returns:
        str: the hours and minutes, e.g. "08:00".
    """
    return f"{t.hour:02d}:{t.minute:02d}"


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
        st.markdown(
            f'<div class="step-time">{_time_s(wl)} \u2500 {tr(step.location)}</div>',
            unsafe_allow_html=True,
        )
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


def _render_trace_state(gs) -> None:
    """Render the canonicalised state in the trace tab.

    args:
        gs (GameState): the state understood by the system.

    returns:
        None: draws into the app.
    """
    st.markdown(
        f'<p class="section-title">{t("understood")}</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="caption-hint">{t("understood_caption")}</p>',
        unsafe_allow_html=True,
    )
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
    st.markdown(
        f'<p class="section-title">{t("trace_attempts")}</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="caption-hint">{t("trace_attempts_caption")}</p>',
        unsafe_allow_html=True,
    )
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
    st.markdown(
        f'<p class="section-title">{t("validation_details")}</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="caption-hint">{t("validation_caption")}</p>',
        unsafe_allow_html=True,
    )
    col_problems, col_legend = st.columns([2, 1], vertical_alignment="top", gap="large")
    with col_problems:
        st.markdown(
            f'<p class="section-title">{t("problems")}</p>',
            unsafe_allow_html=True,
        )
        if not validation.issues:
            st.success(t("no_issues"))
        for issue in validation.issues:
            with st.container(border=True):
                _render_issue(st, issue)
    with col_legend:
        st.markdown(
            f'<p class="section-title">{t("legend_severity")}</p>',
            unsafe_allow_html=True,
        )
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
    st.set_page_config(
        page_title="Termina Companion", page_icon=":material/nightlight:", layout="wide"
    )
    st.markdown(_CSS, unsafe_allow_html=True)

    if "lang" not in st.session_state:
        st.session_state["lang"] = "en"

    top_left, top_right = st.columns([6, 1])
    with top_left:
        st.markdown(
            f'<div style="font-size:2.2rem;font-weight:800;color:#F5B301;">'
            f"\U0001f319 {t('title')}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="color:#8A93A6;margin-top:-0.7rem;">{t("subtitle")}</div>',
            unsafe_allow_html=True,
        )
    with top_right:
        st.selectbox(t("language"), ["en", "it"], key="lang", label_visibility="visible")

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
            value="Reunite Anju and Kafei before the dawn of the Third Day",
            height=180,
            label_visibility="collapsed",
        )
        st.markdown('<div style="padding:0.4rem;"></div>', unsafe_allow_html=True)
        run = st.button(t("generate_plan"), type="primary", use_container_width=True)

    if not run:
        st.info(t("info_edit_state"))
        return

    game_state = GameState(
        time=ClockTime(day=day, hour=tm.hour, minute=tm.minute),
        location=location,
        inventory=list(inventory or []),
        masks=list(masks or []),
        quest_progress={quest_names[q]: "done" for q in (done_q or [])},
    )
    goal = Goal(description=goal_text)

    initial = {"game_state": game_state, "goal": goal}
    result: dict = {}

    def _run_stream(q) -> None:
        """Stream graph updates into the given queue for the UI thread.

        args:
            q (queue.Queue): the queue receiving ``{node: data}`` updates,
            terminated with ``None``.

        returns:
            None: runs in a background thread.
        """
        try:
            for update in _graph().stream(initial, stream_mode="updates"):
                q.put(update)
        finally:
            q.put(None)

    agent_name = {
        "state": t("agent_state"),
        "knowledge": t("agent_knowledge"),
        "plan": t("agent_planning"),
        "critic": t("agent_critic"),
    }
    phrases = itertools.cycle(spinner_lines())
    q: queue.Queue = queue.Queue()
    threading.Thread(target=_run_stream, args=(q,), daemon=True).start()

    with st.status(f"{next(phrases)}...", type="step", state="running", expanded=True) as outer:
        next_flip = time.monotonic()
        while True:
            if next_flip <= time.monotonic():
                outer.update(label=f"{next(phrases)}...", state="running", expanded=True)
                next_flip = time.monotonic() + _SPINNER_INTERVAL
            try:
                item = q.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                break
            for node, data in item.items():
                result.update(data)
                name = agent_name[node]
                if node == "plan":
                    attempt = t(
                        "step_attempt",
                        n=result["replan_attempts"],
                        max=MAX_PLANNING_ATTEMPTS,
                    )
                    name += f" \u2014 {attempt}"
                with st.status(name, type="step", expanded=True) as step:
                    _append_step(step, node, result)
                outer.update(expanded=True)
        st.status(
            t("planning_complete")
            if result["validation"].valid
            else t("planning_gave_up", max=MAX_PLANNING_ATTEMPTS),
            type="step",
            state="complete" if result["validation"].valid else "error",
        )
    valid = result["validation"].valid
    outer.update(
        label=t("planning_complete") if valid else t("planning_gave_up", max=MAX_PLANNING_ATTEMPTS),
        state="complete" if valid else "error",
        expanded=True,
    )

    _section(t("your_plan"))
    validation = result["validation"]
    if validation.valid:
        st.success(t("plan_valid"))
    else:
        st.error(t("plan_not_valid"))

    _render_plan(result["plan"])

    tab_why, tab_sources, tab_trace = st.tabs([t("tab_why"), t("tab_sources"), t("tab_trace")])

    with tab_why:
        st.markdown(
            f'<p class="caption-hint">{t("tab_why_caption")}</p>',
            unsafe_allow_html=True,
        )
        _render_why(result["plan"])
    with tab_sources:
        st.markdown(
            f'<p class="caption-hint">{t("tab_sources_caption")}</p>',
            unsafe_allow_html=True,
        )
        _render_sources(result["relevant_objectives"], kb)
    with tab_trace:
        st.markdown(
            f'<p class="caption-hint">{t("tab_trace_caption")}</p>',
            unsafe_allow_html=True,
        )
        _render_trace_state(result["game_state"])
        _render_trace_attempts(result["replan_attempts"])
        _render_trace_issues(validation)


if __name__ == "__main__":
    render()
