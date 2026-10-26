"""Validation issue rendering, chips and tables."""

from __future__ import annotations

import html
import re

from app.i18n import t, tr, tr_msg
from app.ui.formatting import (
    _entity_index,
    _entity_span,
    _highlight_entities,
    _markdown_windows,
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


def _missing_requirements(issues) -> list[tuple[str, str]]:
    """Extract missing item/mask names and their kind from the Critic's text."""
    names: list[tuple[str, str]] = []
    seen: set[str] = set()
    for issue in issues:
        match = _MISSING_RE.match(issue.message.strip())
        if match is None:
            continue
        kind = match.group(1)
        for name in match.group(2).split(","):
            name = name.strip()
            if name and name not in seen:
                seen.add(name)
                names.append((kind, name))
    return names


def _missing_chips_html(issues, prefix: bool = False) -> str:
    """Return requirement chips for the issues, optionally prefixed with 'missing'."""
    missing = _missing_requirements(issues)
    if not missing:
        return ""
    chips = []
    for kind, name in missing:
        entity = _entity_span(tr(name), kind)
        label = t("missing_requirement", name=entity) if prefix else entity
        chips.append(f'<span class="tc-missing-chip">{label}</span>')
    return f'<div class="tc-missing-chips">{"".join(chips)}</div>'


def _issues_table_html(issues, fallback: str = "plan", entities=None) -> str:
    """Return the Critic issue table shared by the registry and problems panels."""
    index = entities if entities is not None else _entity_index(None)
    rows = []
    for issue in issues:
        severity = t("sev_error") if issue.severity == "error" else t("sev_warning")
        tone = "error" if issue.severity == "error" else "warning"
        kind = t(f"kind_{issue.kind}")
        where = t("step_n", n=issue.step_idx + 1) if issue.step_idx is not None else t(fallback)
        message = _highlight_entities(tr_msg(issue.message), index)
        rows.append(
            '<div class="tc-issue-row">'
            f'<span><span class="tc-sev-tag {tone}">{html.escape(severity.upper())}</span></span>'
            f'<span><span class="tc-kind-tag">{html.escape(kind.upper())}</span></span>'
            f'<span class="tc-issue-step">{html.escape(where)}</span>'
            f"<span>{message}</span>"
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


def _problems_panel_html(issues, entities=None) -> str:
    """Return the full-width problems table shown under an invalid plan."""
    return (
        '<section class="tc-problems-panel">'
        f'<div class="tc-panel-title">{html.escape(t("problems"))}</div>'
        f"{_issues_table_html(issues, entities=entities)}"
        "</section>"
    )
