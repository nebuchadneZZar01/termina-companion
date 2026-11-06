"""Plan result: verdict, timeline and why details."""

from __future__ import annotations

import html

import streamlit as st

from app.graph import MAX_PLANNING_ATTEMPTS
from app.i18n import t, tr
from app.ui import sources_view
from app.ui.formatting import (
    _ai_note_html,
    _entities_html,
    _entity_index,
    _entity_span,
    _highlight_entities,
    _html_clock,
    _section,
)
from app.ui.issues import (
    _missing_chips_html,
    _missing_requirements,
    _problems_panel_html,
)
from app.ui.tasks import _PlanningTask
from app.ui.theme import _html_block
from app.ui.trace_view import (
    _render_memory,
    _render_run_audit,
    _render_trace_attempts,
    _render_trace_issues,
    _render_trace_state,
)


def _render_planning_result(task: _PlanningTask, kb) -> None:
    """Render the last completed plan, even when the run failed afterwards.

    A failed re-planning attempt produces no plan update, so ``task.result``
    still holds the plan and the validation of the last attempt that reached
    the Critic. Showing it (with its issues) beats hiding the only result the
    run produced. When no attempt completed, the failure is already rendered
    by :func:`_render_planning_progress` and there is nothing to show.
    """
    result = task.result
    validation = result.get("validation")
    failed = task.status in {"error", "stopped"}
    if validation is None:
        if not failed:
            st.warning(t("planning_incomplete"))
        return

    entities = _entity_index(kb)
    attempt = result.get("replan_attempts", 0)
    plan = result.get("plan")
    if validation.valid:
        _section(t("your_plan"))
        if failed:
            st.caption(
                t(
                    "plan_last_attempt",
                    n=attempt,
                    max=MAX_PLANNING_ATTEMPTS,
                )
            )
        _html_block(
            _verdict_html(
                True,
                t("plan_valid"),
                t("verdict_ok_body", n=attempt, max=MAX_PLANNING_ATTEMPTS),
            )
        )
    else:
        missing = _missing_requirements(validation.issues)
        body = (
            t("verdict_missing_body")
            if missing
            else t(
                "verdict_fail_body",
                n=len(validation.issues),
                n_attempt=attempt,
                max=MAX_PLANNING_ATTEMPTS,
            )
        )
        _html_block(
            _verdict_html(
                False,
                t("verdict_fail_title"),
                body,
                _missing_chips_html(validation.issues),
            )
        )
        if validation.issues:
            _html_block(_problems_panel_html(validation.issues, entities))
        _render_last_plan(plan, validation.issues, kb=kb)
        if failed:
            st.caption(
                t(
                    "plan_last_attempt",
                    n=attempt,
                    max=MAX_PLANNING_ATTEMPTS,
                )
            )

    plan_model = result.get("plan_model")
    if plan_model:
        _html_block(_ai_note_html(t("plan_ai_disclaimer"), model=plan_model))
    else:
        _html_block(_ai_note_html(t("plan_ai_disclaimer_unknown")))

    if validation.valid:
        _render_plan(plan, valid=True, kb=kb)

    _section(t("behind_the_scenes"))
    tab_why, tab_sources, tab_trace = st.tabs([t("tab_why"), t("tab_sources"), t("tab_trace")])

    with tab_why:
        st.caption(t("tab_why_caption"))
        _render_why(result.get("plan"), kb=kb)
    with tab_sources:
        st.caption(t("tab_sources_caption"))
        sources_view._render_sources(result["relevant_objectives"], kb)
        sources_view._render_rag_evidence(
            evidence=result.get("retrieved_evidence", []),
            engine=result.get("retrieval_engine", ""),
            status=result.get("retrieval_status", ""),
            warning=result.get("retrieval_warning", ""),
            wiki_unreachable=result.get("retrieval_wiki_unreachable", False),
            indexed_sources=result.get("retrieval_indexed_sources", []),
        )
    with tab_trace:
        st.caption(t("tab_trace_caption"))
        _render_run_audit(result)
        _render_trace_state(result["game_state"])
        _render_memory(result.get("relevant_episodes", []))
        _render_trace_attempts(result["replan_attempts"])
        _render_trace_issues(validation, entities)


def _render_plan(
    plan,
    *,
    start: int = 0,
    end: int | None = None,
    issues=None,
    show_numbers: bool = False,
    valid: bool = False,
    kb=None,
) -> None:
    """Render the final plan as the Majora's Mask vertical timeline.

    args:
        plan (Plan | None): the plan to display.
        start (int, default 0): first step index to render.
        end (int | None, default None): exclusive last step index.
        issues: validation issues used to highlight steps and show chips.
        show_numbers (bool, default False): prefix each title with "Step N".
        valid (bool, default False): paint the final step with the valid accent.
        kb: knowledge base used to recognise named entities in step titles.

    returns:
        None: draws into the app.
    """
    if not plan or not plan.steps:
        st.write(t("no_plan"))
        return
    entities = _entity_index(kb)
    total = len(plan.steps)
    issues_by_step: dict[int, list] = {}
    for issue in issues or []:
        if issue.severity == "error" and issue.step_idx is not None:
            issues_by_step.setdefault(issue.step_idx, []).append(issue)
    selected = list(enumerate(plan.steps))[start:end]
    rows = []
    for index, step in selected:
        last = index == total - 1
        bad = index in issues_by_step
        start_clock = step.window.start
        suffix = " (+1)" if start_clock.next_morning else ""
        hour = f"{start_clock.display_hour:02d}:{start_clock.minute:02d}{suffix}"
        meta = []
        if step.location:
            meta.append(_entity_span(tr(step.location), "place"))
        needs = [
            *(_entity_span(tr(x), "item") for x in step.requires_items),
            *(_entity_span(tr(x), "mask") for x in step.requires_masks),
        ]
        if needs:
            meta.append(f"{html.escape(t('needs'))} {', '.join(needs)}")
        if step.depends_on:
            deps = ", ".join(str(d + 1) for d in step.depends_on)
            meta.append(html.escape(t("depends_on", deps=deps)))
        title = _highlight_entities(step.title, entities)
        if show_numbers:
            title = t("plan_step_title", n=index + 1, title=title)
        chips = _missing_chips_html(issues_by_step.get(index, []), prefix=True)
        classes = "tc-step"
        if last:
            classes += " last"
            if valid:
                classes += " ok"
        if bad:
            classes += " bad"
        rows.append(
            f'<div class="{classes}">'
            '<div class="tc-step-time">'
            f'<div class="tc-step-hour">{hour}</div>'
            f'<div class="tc-step-day">{html.escape(t("day_n", n=start_clock.day))}</div>'
            "</div>"
            '<div class="tc-step-rail">'
            '<span class="tc-dot"></span><span class="tc-line"></span>'
            "</div>"
            '<div class="tc-step-card">'
            f'<div class="tc-step-title">{title}</div>'
            f'<div class="tc-step-meta">{" \u00b7 ".join(meta)}</div>'
            f"{chips}"
            "</div></div>"
        )
    _html_block(f'<div class="tc-timeline">{"".join(rows)}</div>')


def _render_last_plan(plan, issues, kb=None) -> None:
    """Render the invalid plan around its first failing step."""
    _section(t("last_plan_title"))
    if not plan or not plan.steps:
        st.write(t("no_plan"))
        return
    focus = next(
        (
            issue.step_idx
            for issue in issues
            if issue.severity == "error" and issue.step_idx is not None
        ),
        None,
    )
    if focus is not None:
        st.caption(t("last_plan_caption", n=focus + 1))
    _render_plan(plan, issues=issues, show_numbers=True, kb=kb)


def _render_why(plan, kb=None) -> None:
    """Render the "why" tab: window, needs and dependencies per step.

    args:
        plan (Plan | None): the plan to explain.
        kb: knowledge base used to recognise named entities in free text.

    returns:
        None: draws into the app.
    """
    if not plan or not plan.steps:
        st.write(t("no_plan"))
        return
    entities = _entity_index(kb)
    cards = []
    for i, step in enumerate(plan.steps, 1):
        lines = [
            f"{html.escape(t('window_label'))}: "
            f"{_html_clock(step.window.start)} \u2192 {_html_clock(step.window.end)}"
        ]
        if step.requires_items:
            needs = _entities_html(step.requires_items, "item")
            lines.append(f"{html.escape(t('needs'))}: {needs}")
        if step.requires_masks:
            masks = _entities_html(step.requires_masks, "mask")
            lines.append(f"{html.escape(t('source_masks'))} {masks}")
        if step.depends_on:
            deps = ", ".join(str(d + 1) for d in step.depends_on)
            lines.append(html.escape(t("depends_on", deps=deps)))
        body = "".join(f'<div class="tc-detail-line">{line}</div>' for line in lines)
        if step.actions:
            actions = "".join(
                f"<li>{_highlight_entities(action, entities)}</li>" for action in step.actions
            )
            body += (
                f'<div class="tc-detail-muted">{html.escape(t("actions_label"))}</div>'
                f"<ul>{actions}</ul>"
            )
        cards.append(
            '<div class="tc-detail-card">'
            f'<div class="tc-detail-title">'
            f"{html.escape(t('step_n', n=i))} \u2014 "
            f"{_highlight_entities(step.title, entities)}"
            "</div>"
            f"{body}</div>"
        )
    _html_block(f'<div class="tc-detail-list">{"".join(cards)}</div>')


def _verdict_html(valid: bool, title: str, body: str, extra_html: str = "") -> str:
    """Return the Critic's verdict banner."""
    cls = "" if valid else " fail"
    icon = "\u2713" if valid else "\u2717"
    return (
        f'<section class="tc-verdict{cls}">'
        f'<div class="tc-verdict-icon" aria-hidden="true">{icon}</div>'
        f'<div><div class="tc-verdict-title">{html.escape(title)}</div>'
        f'<div class="tc-verdict-body">{html.escape(body)}</div>'
        f"{extra_html}</div></section>"
    )
