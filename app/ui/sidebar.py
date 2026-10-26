"""Sidebar state editor, save/load and configuration cards."""

from __future__ import annotations

import datetime
import datetime as _datetime
import html
from urllib.parse import urlsplit

import streamlit as st

from app.data.mock_knowledge import MASKS
from app.domain import internal_hour as _internal_hour
from app.i18n import t, tr
from app.llm import default_model_for
from app.settings import Settings, get_settings
from app.ui.formatting import _time_label
from app.ui.theme import _html_block

_LANGS = {"en": "\U0001f1ec\U0001f1e7 English", "it": "\U0001f1ee\U0001f1f9 Italiano"}


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


def _side_code_html(value: str) -> str:
    """Return the monospace value chip used inside a sidebar card."""
    return f'<span class="tc-side-code">{html.escape(value)}</span>'


def _side_row_html(label: str, value_html: str) -> str:
    """Return one label/value row of a sidebar configuration card."""
    return (
        '<div class="tc-side-row">'
        f'<span class="tc-side-row-label">{html.escape(label)}</span>'
        f"{value_html}</div>"
    )


def _side_stack_row_html(label: str, value_html: str) -> str:
    """Return a stacked label/value row, for values too long to sit beside."""
    return (
        '<div class="tc-side-row tc-side-row-stack">'
        f'<span class="tc-side-row-label">{html.escape(label)}</span>'
        f"{value_html}</div>"
    )


def _side_config_card_html(title: str, rows: list[str]) -> str:
    """Return one read-only configuration card of the sidebar."""
    return (
        '<section class="tc-side-card">'
        f'<div class="tc-side-card-title">{html.escape(title)}</div>'
        f"{''.join(rows)}</section>"
    )


def _configuration_html(settings: Settings) -> str:
    """Return the LLM and runtime cards shown at the bottom of the sidebar."""
    provider = settings.llm_provider or ""
    base_url = settings.llm_base_url or ""

    llm_rows: list[str] = []
    if provider:
        model = settings.llm_model or default_model_for(provider)
        llm_rows.append(_side_row_html(t("llm_provider"), _side_code_html(provider)))
        if model:
            llm_rows.append(_side_row_html(t("llm_model"), _side_code_html(model)))
        if base_url:
            llm_rows.append(_side_row_html("LLM_BASE_URL", _side_code_html(base_url)))

    rag = settings.rag
    retrieval = t("state_on") if rag.enabled else t("state_off")
    retrieval_class = "tc-side-pill" if rag.enabled else "tc-side-pill tc-side-pill-off"
    retrieval_html = (
        f'<span class="{retrieval_class}">'
        '<span class="tc-side-pill-dot" aria-hidden="true"></span>'
        f"{html.escape(retrieval)}</span>"
    )

    embedding = rag.embedding_model
    prefix, sep, rest = embedding.partition("/")
    if sep and rest:
        embedding_html = (
            '<span class="tc-side-code">'
            f'<span class="tc-side-code-prefix">{html.escape(prefix + sep)}</span>'
            f"{html.escape(rest)}</span>"
        )
    else:
        embedding_html = _side_code_html(embedding)

    if settings.tracing_enabled:
        phoenix_html = (
            f'<a class="tc-side-link" href="{html.escape(settings.phoenix_ui_url, quote=True)}" '
            f'target="_blank" rel="noreferrer">{html.escape(t("open_phoenix"))}</a>'
        )
    else:
        phoenix_html = _side_code_html("None")

    runtime_rows = [
        _side_row_html(t("rag_retrieval"), retrieval_html),
        _side_stack_row_html(t("rag_embedding_model"), embedding_html),
        _side_row_html(t("phoenix_url"), phoenix_html),
    ]
    return _side_config_card_html(t("llm_settings"), llm_rows) + _side_config_card_html(
        t("runtime_config"), runtime_rows
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

    _html_block(_configuration_html(settings))
    if provider:
        if provider in {"ollama", "lmstudio"} and base_url and urlsplit(base_url).path in {"", "/"}:
            st.warning(t("llm_base_url_hint"))
    else:
        st.warning(
            "LLM not configured. Set LLM_PROVIDER (and credentials) in .env (see .env.example)."
        )


def _apply_pending_load() -> None:
    """Apply a pending save before the sidebar widgets own their keys."""
    snapshot = st.session_state.pop("_load_pending", None)
    if snapshot is None:
        return
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
        st.session_state["_load_ok"] = True
    except Exception as exc:
        st.toast(str(exc), icon="❌", duration=6)


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
    if st.session_state.get("save_time") is None:
        st.session_state["save_time"] = datetime.time(6, 0)
    day = int(st.session_state.get("save_day", 1))
    when = st.session_state["save_time"]
    _html_block(_time_card_html(day, when))

    locations = sorted({loc.name for loc in kb.locations})
    options = locations or ["Termina Field"]
    default_loc = "South Clock Town"
    if st.session_state.get("save_location") not in options:
        st.session_state["save_location"] = default_loc if default_loc in options else options[0]
    location = st.selectbox(
        t("sidebar_location"),
        options,
        format_func=tr,
        key="save_location",
    )

    c1, c2 = st.columns([1, 1])
    with c1:
        day = st.selectbox(t("day"), [1, 2, 3], index=0, key="save_day")
    with c2:
        when = st.time_input(t("time"), value=None, step=60, key="save_time")
    st.caption(_time_label(day, when))

    if st.session_state.get("save_masks") is None:
        st.session_state["save_masks"] = []
    masks = st.multiselect(
        t("sidebar_masks"),
        list(MASKS),
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
    if st.session_state.get("save_inventory") is None:
        st.session_state["save_inventory"] = []
    pending_add = st.session_state.pop("_inventory_add_pending", None)
    if pending_add:
        current = list(st.session_state["save_inventory"])
        if pending_add not in current:
            st.session_state["save_inventory"] = [*current, pending_add]
        st.session_state["save_inventory_new"] = ""
    # The multiselect renders only options: merge the current selection so
    # custom items (typed or loaded from a save) stay visible and removable.
    owned_now = list(st.session_state["save_inventory"])
    inventory_options = sorted(set(item_options) | set(owned_now))
    inventory = st.multiselect(
        t("sidebar_items"),
        inventory_options or ["Hookshot"],
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
    if st.session_state.get("save_quests") is None:
        st.session_state["save_quests"] = []
    done_q = st.multiselect(
        t("quest_progress"),
        list(quest_names),
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
