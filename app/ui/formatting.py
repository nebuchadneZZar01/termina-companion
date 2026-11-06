"""Shared formatting, entity and HTML primitives."""

from __future__ import annotations

import datetime
import html
import re

import streamlit as st

from app.data.mock_knowledge import MASKS
from app.domain import TimeWindow
from app.domain import internal_hour as _internal_hour
from app.i18n import DEFAULT_LANG, t, tr

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


_ENTITY_CLASS = {"item": "tc-item", "mask": "tc-mask", "place": "tc-place"}


def _entity_span(value: str, kind: str) -> str:
    """Return one display value as its semantic game-entity span."""
    return f'<span class="{_ENTITY_CLASS[kind]}">{html.escape(value)}</span>'


def _entities_html(values, kind: str) -> str:
    """Return a comma-separated, translated list of semantic entity spans."""
    return ", ".join(_entity_span(tr(value), kind) for value in values)


def _entity_index(kb) -> tuple[re.Pattern[str], dict[str, str]]:
    """Build the longest-first matcher for known items, masks and places."""
    if kb is None:
        return re.compile(r"(?!x)x"), {}
    items = {
        item
        for objective in kb.all_objectives
        for item in (*objective.requires_items, *objective.provides_items)
    }
    masks = set(MASKS)
    for objective in kb.all_objectives:
        masks.update(objective.requires_masks)
        masks.update(objective.provides_masks)
    masks.update(item for item in items if "mask" in item.casefold())
    items -= masks
    places = {location.name for location in kb.locations} | {"Clock Town"}
    pairs = [
        *((tr(name), "mask") for name in masks),
        *((tr(name), "item") for name in items),
        *((tr(name), "place") for name in places),
    ]
    kinds: dict[str, str] = {}
    for name, kind in pairs:
        if name:
            kinds.setdefault(name.casefold(), kind)
    if not kinds:
        return re.compile(r"(?!x)x"), {}
    ordered = sorted(kinds, key=len, reverse=True)
    pattern = re.compile(
        "|".join(f"(?<!\\w){re.escape(name)}(?!\\w)" for name in ordered),
        re.IGNORECASE,
    )
    return pattern, kinds


def _highlight_entities(text: str, index: tuple[re.Pattern[str], dict[str, str]]) -> str:
    """Escape *text* and wrap the game entities it mentions in semantic spans."""
    raw = tr(text)
    pattern, kinds = index
    if not kinds:
        return html.escape(raw)
    parts: list[str] = []
    position = 0
    for match in pattern.finditer(raw):
        parts.append(html.escape(raw[position : match.start()]))
        parts.append(_entity_span(match.group(0), kinds[match.group(0).casefold()]))
        position = match.end()
    parts.append(html.escape(raw[position:]))
    return "".join(parts)


def _table_html(headers, rows, numeric=()) -> str:
    """Return a compact dark table; cells and headers must already be escaped."""
    numeric = set(numeric)
    head = "".join(
        f'<th class="{"num" if i in numeric else ""}">{html.escape(label)}</th>'
        for i, label in enumerate(headers)
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="{"num" if i in numeric else ""}">{cell}</td>' for i, cell in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    return (
        '<div class="tc-table-wrap"><table class="tc-table">'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _code_html(value: str) -> str:
    """Return an escaped value as inline code for HTML fragments."""
    return f"<code>{html.escape(value)}</code>"


_AI_NOTE_ICON = (
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="9"></circle>'
    '<path d="M12 11v5M12 8v.5"></path>'
    "</svg>"
)


def _ai_note_html(text: str, sidebar: bool = False) -> str:
    """Return one AI Act transparency note as a bordered card.

    The note states that the output is AI-generated, so the plan view and the
    sidebar can share one primitive instead of duplicating markup.

    args:
        text (str): the already translated note body.
        sidebar (bool, default False): use the sidebar's compact, borderless
            variant.

    returns:
        str: the note markup, safe to pass to ``_html_block``.
    """
    variant = " tc-ai-note-sidebar" if sidebar else ""
    return f'<div class="tc-ai-note{variant}">{_AI_NOTE_ICON}<span>{html.escape(text)}</span></div>'


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


def _plain_clock(clock) -> str:
    """Format a clock for HTML text without markdown code spans."""
    suffix = " (+1)" if clock.next_morning else ""
    return f"{t('day_n', n=clock.day)}, {clock.display_hour:02d}:{clock.minute:02d}{suffix}"


def _html_clock(clock) -> str:
    """Format a clock as an inline code span for HTML detail cards."""
    suffix = " (+1)" if clock.next_morning else ""
    day = html.escape(t("day_n", n=clock.day))
    return (
        f'<span class="tc-code">{day} \u2013 '
        f"{clock.display_hour:02d}:{clock.minute:02d}{suffix}</span>"
    )


def _hours_left(day: int, internal_hour: int, minute: int) -> int:
    """Return the whole hours left before the cycle ends (Day 3 29:59)."""
    elapsed = (day - 1) * 1440 + (internal_hour - 6) * 60 + minute
    return max(0, (3 * 1440 - elapsed) // 60)


def _fairy_svg(
    gradient_id: str,
    css_class: str = "tc-fairy-wings",
) -> str:
    """Return TaIA's wings as inline SVG."""
    fill = f"url(#{gradient_id})"
    class_attr = f' class="{css_class}"' if css_class else ""
    return (
        f'<svg{class_attr} viewBox="0 0 96 72" aria-hidden="true">'
        f'<defs><linearGradient id="{gradient_id}" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#bfe6f2" stop-opacity="0.75"></stop>'
        '<stop offset="1" stop-color="#fff3a0" stop-opacity="0.75"></stop>'
        "</linearGradient></defs>"
        f'<path d="M40 38C28 30 16 16 12 3C26 8 38 22 40 38Z" fill="{fill}" '
        'stroke="#8fb8c4" stroke-width="1" stroke-linejoin="round" '
        'stroke-linecap="round"></path>'
        '<path d="M39 35C29 25 21 14 14 5" fill="none" stroke="#8fb8c4" '
        'stroke-width="0.9" stroke-linecap="round"></path>'
        f'<path d="M56 38C68 30 80 16 84 3C70 8 58 22 56 38Z" fill="{fill}" '
        'stroke="#8fb8c4" stroke-width="1" stroke-linejoin="round" '
        'stroke-linecap="round"></path>'
        '<path d="M57 35C67 25 75 14 82 5" fill="none" stroke="#8fb8c4" '
        'stroke-width="0.9" stroke-linecap="round"></path>'
        f'<path d="M38 47C29 44 21 47 13 54C23 57 33 55 38 47Z" fill="{fill}" '
        'stroke="#8fb8c4" stroke-width="1" stroke-linejoin="round" '
        'stroke-linecap="round"></path>'
        f'<path d="M58 47C67 44 75 47 83 54C73 57 63 55 58 47Z" fill="{fill}" '
        'stroke="#8fb8c4" stroke-width="1" stroke-linejoin="round" '
        'stroke-linecap="round"></path>'
        '<circle cx="70" cy="60" r="3.5" fill="none" stroke="#f5d142" '
        'stroke-width="1.2"></circle>'
        '<circle cx="80" cy="66" r="2.2" fill="#f5d142"></circle>'
        '<circle cx="88" cy="56" r="1.8" fill="#fff3a0"></circle>'
        "</svg>"
    )


def _fairy_html(day: int, value: datetime.time, text: str | None = None) -> str:
    """Return TaIA's greeting bubble with the hours left in the cycle.

    ``text`` overrides the play greeting, so the evaluation tab can reuse the
    same figure and bubble without inventing a second layout.
    """
    hours = _hours_left(day, _internal_hour(value.hour), value.minute)
    message = text if text is not None else t("fairy_greeting", hours=hours)
    # Both tabs stay in the DOM, so a shared gradient id would let the
    # evaluation fairy resolve the hidden play tab's defs.
    gradient_id = "taiaw-eval" if text is not None else "taiaw-play"
    wings = _fairy_svg(gradient_id)
    return (
        '<section class="tc-fairy">'
        '<div class="tc-fairy-figure" aria-hidden="true">'
        f"{wings}"
        '<span class="tc-fairy-orb"></span>'
        "</div>"
        '<div class="tc-fairy-bubble">'
        '<div class="tc-fairy-name">TaIA'
        f'<span class="tc-fairy-badge">{html.escape(t("ai_assistant_badge"))}</span></div>'
        f'<div class="tc-fairy-text">{html.escape(message)}</div>'
        "</div></section>"
    )


def _window_range(w: TimeWindow) -> str:
    """Format a window's start through end hour as one HTML range.

    The range uses the same ``tc-code`` span as ``_html_clock`` so it can be
    dropped into an HTML detail card without Markdown leaking through. A
    window on one game day collapses to a single span, while a window that
    crosses into the next day keeps both clocks and joins them with an arrow.

    args:
        w (TimeWindow): the window to format.

    returns:
        str: the HTML range, e.g. ``Day 1 – 08:00–21:05``.
    """
    if w.end.day != w.start.day:
        return f"{_html_clock(w.start)} \u2192 {_html_clock(w.end)}"
    day = html.escape(t("day_n", n=w.start.day))
    suffix = " (+1)" if w.end.next_morning else ""
    start = f"{w.start.display_hour:02d}:{w.start.minute:02d}"
    end = f"{w.end.display_hour:02d}:{w.end.minute:02d}{suffix}"
    return f'<span class="tc-code">{day} \u2013 {start}\u2013{end}</span>'
