"""Streamlit page entry point and layout."""

from __future__ import annotations

import datetime as _datetime
from pathlib import Path

import streamlit as st

from app.data.mock_knowledge import build_default_knowledge
from app.domain import internal_hour as _internal_hour
from app.i18n import t
from app.save import load_state, save_state
from app.ui.evaluation_view import _render_evaluation
from app.ui.formatting import _section
from app.ui.play import _render_play
from app.ui.sidebar import (
    _apply_pending_load,
    _render_configuration,
    _render_sidebar_editor,
)
from app.ui.theme import _inject_styles

_FAVICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "favicon.svg"


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
        page_title="TaIA – Your Termina Fairy Companion",
        page_icon=str(_FAVICON_PATH),
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_styles()
    kb = build_default_knowledge()

    _apply_pending_load()
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
                    "version": 3,
                    "day": day_val,
                    "time": {"day": day_val, "hour": hour_val, "minute": tm_val.minute},
                    "location": st.session_state.get("save_location") or "South Clock Town",
                    "masks": list(st.session_state.get("save_masks") or []),
                    "inventory": list(st.session_state.get("save_inventory") or []),
                    "quest_progress": list(st.session_state.get("save_quests") or []),
                    "completed_objectives": list(st.session_state.get("save_objectives") or []),
                    "goal": goal_val or "",
                }
                try:
                    _ = save_state(data)
                    st.toast(t("save_ok"), icon="✅", duration=4)
                except Exception as exc:
                    st.toast(str(exc), icon="❌", duration=6)
        with col_l:
            if st.button(t("load_button"), use_container_width=True):
                snapshot = load_state()
                if not snapshot:
                    st.toast(t("load_none"), icon="⚠️", duration=4)
                else:
                    st.session_state["_load_pending"] = snapshot
                    st.rerun()
        if st.session_state.pop("_load_ok", False):
            st.toast(t("load_ok"), icon="✅", duration=4)
        save_warning = st.session_state.pop("_save_warning", "")
        if save_warning:
            st.toast(save_warning, icon="⚠️", duration=8)
        _render_configuration()

    tab_play, tab_evaluation = st.tabs([t("tab_play"), t("tab_evaluation")])
    with tab_play:
        _render_play(editor, kb)
    with tab_evaluation:
        with st.container(key="evaluation_tab", gap=28):
            _render_evaluation(editor)
