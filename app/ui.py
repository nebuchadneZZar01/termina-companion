"""Minimal Streamlit UI for Termina Companion.

Entry points: ``uv run streamlit run main.py`` (preferred) or
``uv run streamlit run app/ui.py``.
"""

from __future__ import annotations

import datetime

import streamlit as st

from app.data.mock_knowledge import MASKS, build_default_knowledge
from app.domain import ClockTime, GameState, Goal, TimeWindow
from app.graph import MAX_PLANNING_ATTEMPTS, build_graph
from app.i18n import t, tr, tr_msg


@st.cache_resource
def _graph():
    return build_graph()


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
.agents-compact {
    color: #8A93A6;
    font-size: 0.85rem;
    margin: 0.4rem 0 0.8rem 0;
}
</style>
"""


def _section(title: str, caption: str = "") -> None:
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    if caption:
        st.markdown(f'<div class="caption-hint">{caption}</div>', unsafe_allow_html=True)


def _fmt_clock(t: ClockTime) -> str:
    return f"Day {t.day} {t.hour:02d}:{t.minute:02d}"


def _time_s(t: ClockTime) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def _render_plan(plan) -> None:
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
            if step.depends_on:
                deps = ", ".join(str(d + 1) for d in step.depends_on)
                st.write(t("depends_on", deps=deps))


def _window_range(w: TimeWindow) -> str:
    start = tr(_fmt_clock(w.start))
    return f"{start}\u2013{w.end.hour:02d}:{w.end.minute:02d}"


def _render_sources(objectives, kb) -> None:
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
            prereq_titles = [o.title for o in kb.all_objectives if o.id in obj.prerequisites]
            if prereq_titles:
                st.write(f"{t('source_after')} {', '.join(tr(x) for x in prereq_titles)}")


def _render_trace_state(gs) -> None:
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
            is_error = issue.severity == "error"
            kind = t(f"kind_{issue.kind}")
            where = issue.step_idx + 1 if issue.step_idx is not None else None
            with st.container(border=True):
                col_sev, col_kind, col_step = st.columns([1, 1, 2], vertical_alignment="center")
                with col_sev:
                    st.badge(
                        (t("sev_error") if is_error else t("sev_warning")).upper(),
                        color="red" if is_error else "orange",
                    )
                with col_kind:
                    st.badge(kind.upper(), color="blue")
                if where:
                    with col_step:
                        st.markdown(f"**{t('step_n', n=where)}**")
                st.write(tr_msg(issue.message))
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

    with st.spinner(t("planning")):
        result = _graph().invoke({"game_state": game_state, "goal": goal})

    _section(t("your_plan"))
    validation = result["validation"]
    if validation.valid:
        st.success(t("plan_valid"))
    else:
        st.error(t("plan_not_valid"))

    _render_plan(result["plan"])

    agent_ok = [
        bool(result["state_summary"]),
        bool(result["retrieved_context"]),
        bool(result["plan"] and result["plan"].steps),
        validation.valid,
    ]
    agent_count = sum(agent_ok)
    agents = [
        (t("agent_state"), t("agent_state_desc"), agent_ok[0]),
        (t("agent_knowledge"), t("agent_knowledge_desc"), agent_ok[1]),
        (t("agent_planning"), t("agent_planning_desc"), agent_ok[2]),
        (t("agent_critic"), t("agent_critic_desc"), agent_ok[3]),
    ]
    st.markdown(
        f'<div class="agents-compact">{t("agents_line", count=agent_count)}</div>',
        unsafe_allow_html=True,
    )
    with st.expander(t("agents_detail")):
        for name, desc, ok in agents:
            mark = "\u2713" if ok else "\u2717"
            col_text, col_badge = st.columns([4, 1], vertical_alignment="center")
            with col_text:
                st.markdown(f"**{mark} {name}** \u2014 {desc}")
            with col_badge:
                st.badge(
                    (t("agent_done") if ok else t("agent_failed")).upper(),
                    color="green" if ok else "red",
                )

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
