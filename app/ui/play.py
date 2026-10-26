"""Play tab: TaIA greeting, goal controls and empty state."""

from __future__ import annotations

import html

import streamlit as st

from app.domain import ClockTime, GameState, Goal
from app.domain import internal_hour as _internal_hour
from app.i18n import t
from app.ui.formatting import _fairy_html
from app.ui.plan_view import _render_planning_result
from app.ui.progress import _planning_live, _render_planning_progress
from app.ui.tasks import (
    _PLANNING_TASK_KEY,
    _graph,
    _plan_controls_disabled,
    _start_planning_task,
    _task_is_active,
)
from app.ui.theme import _html_block


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
        _planning_live(task, kb)
        st.rerun()

    if task is not None:
        _render_planning_progress(task, kb)
        _render_planning_result(task, kb)
        return

    _html_block(_empty_plan_html())
