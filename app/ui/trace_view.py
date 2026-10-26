"""Trace tab: audit, understood state, memory and attempts."""

from __future__ import annotations

import html

import streamlit as st

from app.graph import MAX_PLANNING_ATTEMPTS
from app.i18n import t, tr
from app.settings import get_settings
from app.trace import current_run
from app.ui.formatting import (
    _entities_html,
    _entity_span,
    _html_clock,
    _section,
    _table_html,
)
from app.ui.issues import _issues_table_html
from app.ui.theme import _html_block


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
        _html_block(f'<div class="tc-subhead">{html.escape(t("audit_timeline"))}</div>')
        rows = [
            [
                html.escape(node["name"]),
                f'<span class="tc-cell-muted">{node["duration_s"] * 1000:.0f} ms</span>',
                "\u2705" if node["status"] == "ok" else "\u274c",
                html.escape(node["detail"]),
            ]
            for node in run.nodes
        ]
        _html_block(
            _table_html(
                [t("audit_step"), t("audit_duration"), t("audit_status"), t("audit_detail")],
                rows,
            )
        )
    if run.errors:
        _html_block(f'<div class="tc-subhead">{html.escape(t("audit_errors"))}</div>')
        for error in run.errors:
            block = f"[{error['source']}] {error['message']}"
            if error["detail"]:
                block = f"{block}\n{error['detail']}"
            st.code(block, language="text")


def _state_fields_html(gs) -> str:
    """Return the canonical game state as the trace card's rows."""
    items = _entities_html(gs.inventory, "item") or html.escape(t("trace_none"))
    masks = _entities_html(gs.masks, "mask") or html.escape(t("trace_none"))
    rows = [
        (t("trace_where"), _entity_span(tr(gs.location), "place")),
        (t("trace_when"), _html_clock(gs.time)),
        (t("trace_items"), items),
        (t("trace_masks"), masks),
    ]
    body = "".join(
        f'<div class="tc-detail-line"><b>{html.escape(label)}</b> {value}</div>'
        for label, value in rows
    )
    return f'<div class="tc-detail-card">{body}</div>'


def _render_trace_state(gs) -> None:
    """Render the canonicalised state in the trace tab.

    args:
        gs (GameState): the state understood by the system.

    returns:
        None: draws into the app.
    """
    _section(t("understood"), t("understood_caption"))
    _html_block(_state_fields_html(gs))


def _render_memory(episodes) -> None:
    """Render past episodes recalled by memory in the trace tab."""
    _section(t("memory_episodes"), t("memory_episodes_caption"))
    if not episodes:
        st.caption(t("memory_none"))
        return
    cards = []
    for ep in episodes[:3]:
        status = "valid" if ep.valid else "invalid"
        summary = ""
        if ep.plan_summary:
            summary = (
                f'<div class="tc-detail-muted">'
                f"{html.escape(' '.join(str(ep.plan_summary).split())[:300])}</div>"
            )
        cards.append(
            '<div class="tc-detail-card">'
            f'<div class="tc-detail-title">{html.escape(str(ep.goal))} '
            f'<span class="tc-detail-muted">({html.escape(status)})</span></div>'
            f"{summary}</div>"
        )
    _html_block(f'<div class="tc-detail-list">{"".join(cards)}</div>')


def _render_trace_attempts(n: int) -> None:
    """Render the planning-attempt counter in the trace tab.

    args:
        n (int): the number of planning attempts made.

    returns:
        None: draws into the app.
    """
    _section(t("trace_attempts"), t("trace_attempts_caption"))
    if n == 0:
        body = t("no_replan")
        tone = "tc-cell-pass"
    elif n >= MAX_PLANNING_ATTEMPTS:
        body = t("replan_gave_up", max=MAX_PLANNING_ATTEMPTS)
        tone = "tc-cell-fail"
    else:
        body = t("attempts", n=n, max=MAX_PLANNING_ATTEMPTS)
        tone = "tc-cell-warn"
    _html_block(f'<div class="tc-detail-card"><div class="{tone}">{html.escape(body)}</div></div>')


def _render_trace_issues(validation, entities=None) -> None:
    """Render validation details and legend in the trace tab.

    args:
        validation (ValidationResult): the validation outcome to display.
        entities: optional entity matcher for item/mask/place styling.

    returns:
        None: draws into the app.
    """
    _section(t("validation_details"), t("validation_caption"))
    col_problems, col_legend = st.columns([2, 1], vertical_alignment="top", gap="large")
    with col_problems:
        _html_block(f'<div class="tc-subhead">{html.escape(t("problems"))}</div>')
        if not validation.issues:
            _html_block(
                '<div class="tc-detail-card">'
                f'<div class="tc-cell-pass">{html.escape(t("no_issues"))}</div>'
                "</div>"
            )
        else:
            _html_block(
                f'<div class="tc-detail-card">'
                f"{_issues_table_html(validation.issues, entities=entities)}</div>"
            )
    with col_legend:
        _html_block(f'<div class="tc-subhead">{html.escape(t("legend_severity"))}</div>')
        _html_block(
            '<div class="tc-detail-card">'
            '<div class="tc-detail-line">'
            f'<span class="tc-sev-tag error">{html.escape(t("sev_error").upper())}</span> '
            f"{html.escape(t('sev_legend_error'))}</div>"
            '<div class="tc-detail-line">'
            f'<span class="tc-sev-tag warning">{html.escape(t("sev_warning").upper())}</span> '
            f"{html.escape(t('sev_legend_warning'))}</div>"
            "</div>"
        )
