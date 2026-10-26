"""Live planning progress: reasoning title and agent registry loop."""

from __future__ import annotations

import html
import re
import time

import streamlit as st

from app.graph import MAX_PLANNING_ATTEMPTS
from app.i18n import spinner_lines, t
from app.ui.formatting import _code_html, _highlight_entities
from app.ui.tasks import (
    _IDLE_WAIT,
    _TICK_SECONDS,
    _drain_planning_task,
    _PlanningTask,
    _task_is_active,
)
from app.ui.theme import _html_block

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


def _progress_html(line: str, entities) -> str:
    """Render a progress line as HTML, preserving backticked values as code."""
    parts = re.split(r"`([^`]*)`", line)
    rendered = []
    for position, part in enumerate(parts):
        if position % 2:
            rendered.append(_code_html(part))
        else:
            rendered.append(_highlight_entities(part.replace("*", ""), entities))
    return "".join(rendered)


def _render_planning_progress(task: _PlanningTask, kb=None) -> None:
    """Render the finished agent registry and any terminal error."""
    from app.ui.registry import _agent_registry_html

    _html_block(_agent_registry_html(task, kb=kb))
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


def _planning_live(task: _PlanningTask, kb=None) -> None:
    """Drive the live HTML registry until the run reaches a terminal state.

    The registry is redrawn only when a streamed event arrives, while the
    reasoning title rotates on the 2s wall-clock tick. Keeping the registry out
    of the tick redraw preserves any row the user opened between events. The
    single empty placeholder is an invisible yield point, which is what lets
    Streamlit process a queued Stop click while this script is still running.
    """
    from app.ui.registry import _agent_registry_html

    title = st.empty()
    registry = st.empty()
    yield_point = st.empty()
    started = time.monotonic()
    last_tick = -1

    def draw_title(tick: int) -> None:
        _state, label = _outer_status(task, tick)
        title.markdown(_live_title_html(label), unsafe_allow_html=True)

    def draw_registry() -> None:
        registry.markdown(_agent_registry_html(task, live=True, kb=kb), unsafe_allow_html=True)

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
