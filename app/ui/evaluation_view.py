"""Evaluation tab: sweep controls, results and comparison."""

from __future__ import annotations

import datetime
import html
import logging
import time
from pathlib import Path

import streamlit as st

from app.evaluation.comparison import compare_reports, select_baseline
from app.evaluation.models import EvaluationReport
from app.evaluation.scenarios import EVALUATION_SCENARIOS, SCENARIOS_BY_ID
from app.evaluation.storage import (
    LAST_REPORT_NAME,
    get_eval_dir,
    load_history,
    load_report,
)
from app.i18n import t
from app.settings import get_settings
from app.ui.formatting import (
    _code_html,
    _fairy_html,
    _fmt_model,
    _section,
    _table_html,
)
from app.ui.issues import _render_issue
from app.ui.tasks import (
    _ACTIVE_STATUSES,
    _EVALUATION_REPORT_KEY,
    _EVALUATION_TASK_KEY,
    _IDLE_WAIT,
    _drain_evaluation_task,
    _EvaluationTask,
    _start_evaluation_task,
)
from app.ui.theme import _html_block

logger = logging.getLogger(__name__)


def _failure_breakdown_html(kinds: dict[str, int]) -> str:
    """Return the failures-by-check panel shown under the evaluation metrics."""
    chips = "".join(
        f'<span class="tc-failure-chip"><b>{count}</b> {html.escape(_check_label(kind))}</span>'
        for kind, count in kinds.items()
    )
    if not chips:
        chips = '<span class="tc-failure-empty">\u2013</span>'
    return (
        '<div class="tc-failure-panel">'
        f'<div class="tc-failure-label">{html.escape(t("eval_failures_by_kind"))}</div>'
        f'<div class="tc-failure-list">{chips}</div>'
        "</div>"
    )


def _scenario_label(scenario_id: str) -> str:
    """Return the label of a scenario in the scenario picker."""
    scenario = SCENARIOS_BY_ID.get(scenario_id)
    return f"{scenario.name} ({scenario_id})" if scenario else scenario_id


def _evaluation_live(task: _EvaluationTask) -> None:
    """Drive the evaluation progress bar until the sweep reaches a terminal state.

    The loop blocks on the worker queue (no busy timer) and repaints only when
    a scenario finishes. The empty placeholder is the invisible yield point
    that lets Streamlit process a queued Stop click during a long run.
    """
    bar = st.progress(0.0, text=t("eval_running"))
    caption = st.empty()
    yield_point = st.empty()
    while task.status in _ACTIVE_STATUSES:
        progressed = _drain_evaluation_task(task, wait=_IDLE_WAIT)
        total = max(task.total, 1)
        bar.progress(min(len(task.results) / total, 1.0), text=t("eval_running"))
        caption.caption(t("eval_running_scenario", name=task.current or "-"))
        if not progressed:
            time.sleep(0.05)
        yield_point.empty()


def _short_error(error: str, limit: int = 160) -> str:
    """Shorten a run error so the report table stays readable.

    args:
        error (str): the error message, empty when the run succeeded.
        limit (int): the maximum length kept.

    returns:
        str: the error message, truncated, or "-" when there is none.
    """
    if not error:
        return "-"
    return error if len(error) <= limit else f"{error[: limit - 1]}…"


def _saved_report_path() -> Path | None:
    """Return the report path shown under the evaluation controls.

    args:
        (none)

    returns:
        Path | None: the path of the last report, or None when the store
        cannot be opened (for instance a read-only checkout).
    """
    try:
        return get_eval_dir() / LAST_REPORT_NAME
    except OSError:
        return None


def _render_evaluation_results(report: EvaluationReport) -> None:
    """Render the outcome of an evaluation sweep: metrics, table and details.

    args:
        report (EvaluationReport): the report to render.

    returns:
        None: renders into the app.
    """
    _section(t("eval_result"))
    if not report.results:
        st.caption(t("eval_no_results"))
        return

    if report.rag_on is not None or report.models:
        planner_label = (
            t(f"eval_planner_{report.planner}")
            if report.planner in ("llm", "deterministic")
            else t("eval_unknown")
        )
        st.caption(
            t(
                "eval_report_meta",
                model=_fmt_model(report.models),
                planner=planner_label,
                rag=t(f"eval_rag_{report.wiki_retrieval}"),
                repeats=report.repeats,
            )
        )
        if report.wiki_retrieval == "degraded":
            st.caption(t("eval_rag_degraded_help"))

    c_rate, c_passed, c_failed = st.columns(3)
    c_rate.metric(t("eval_pass_rate"), f"{report.pass_rate * 100:.0f}%")
    c_passed.metric(t("eval_passed"), f"{report.passed}/{report.total}")
    c_failed.metric(t("eval_failed"), str(report.failed))
    _html_block(_failure_breakdown_html(report.failures_by_kind))

    _render_comparison(report)

    rows = []
    for result in report.results:
        status = t("eval_pass") if result.passed else t("eval_fail")
        status_class = "tc-cell-pass" if result.passed else "tc-cell-fail"
        warnings = (
            f'<span class="tc-cell-warn">{result.warning_count}</span>'
            if result.warning_count
            else "0"
        )
        error = _short_error(result.error)
        error_cell = (
            _code_html(error)
            if result.error
            else f'<span class="tc-cell-muted">{html.escape(error)}</span>'
        )
        rows.append(
            [
                _code_html(result.scenario_id),
                f'<span class="{status_class}">{html.escape(status)}</span>',
                str(result.step_count),
                f'<span class="tc-cell-muted">{result.duration_s:.1f}s</span>',
                str(result.error_count),
                warnings,
                error_cell,
            ]
        )
    _html_block(
        _table_html(
            [
                t("eval_scenario"),
                t("eval_status"),
                t("eval_steps"),
                t("eval_duration"),
                t("eval_errors"),
                t("eval_warnings"),
                t("eval_run_error"),
            ],
            rows,
            numeric={2, 4, 5},
        )
    )

    with st.container(key="eval_details", gap=28):
        for result in report.results:
            status = t("eval_pass") if result.passed else t("eval_fail")
            with st.expander(f"`{result.scenario_id}` — {status}"):
                if result.error:
                    st.error(t("eval_run_error"))
                    st.code(result.error, language="text")
                elif not result.issues:
                    st.success(t("eval_no_issues"))
                for issue in result.issues:
                    _render_issue(st, issue, fallback="")
                    help_key = f"kind_{issue.kind}_help"
                    help_text = t(help_key)
                    if help_text != help_key:
                        st.caption(help_text)


def _format_timestamp(value: str) -> str:
    """Format a stored ISO timestamp for display.

    A value that cannot be parsed is returned unchanged, so an old or foreign
    report still shows something instead of an empty caption.

    args:
        value (str): the stored timestamp.

    returns:
        str: the display timestamp, e.g. ``22/10/2026 15:25 UTC``.
    """
    try:
        stamp = datetime.datetime.fromisoformat(value)
    except ValueError:
        return value
    return stamp.strftime("%d/%m/%Y %H:%M UTC")


def _render_comparison(report: EvaluationReport) -> None:
    """Render how the sweep changed against the newest compatible stored sweep.

    The baseline comes from the saved history, so a sweep loaded with *Load
    last report* is compared too: it is already in the history and
    ``select_baseline`` skips the report itself. An unreadable store only hides
    the card, it never breaks the tab.

    args:
        report (EvaluationReport): the sweep being rendered.

    returns:
        None: renders into the app.
    """
    try:
        baseline = select_baseline(report, load_history())
    except Exception:  # noqa: BLE001 - an unreadable store must not break the tab
        return
    if baseline is None:
        st.caption(t("eval_compare_none"))
        return
    comparison = compare_reports(report, baseline)
    when = _format_timestamp(baseline.created_at) or t("eval_unknown")
    before = f"{comparison.baseline_passed}/{comparison.baseline_total}"
    after = f"{comparison.current_passed}/{comparison.current_total}"
    changes = [change for change in comparison.changes if change.status != "same"]
    rows = []
    for change in changes:
        detail = (
            t(
                "eval_compare_new_failure",
                kinds=", ".join(_check_label(kind) for kind in change.new_failure_kinds),
            )
            if change.new_failure_kinds
            else t(f"eval_compare_{change.status}_help")
        )
        rows.append(
            [
                _code_html(change.scenario_id),
                html.escape(t(f"eval_compare_{change.status}")),
                html.escape(detail),
            ]
        )
    if comparison.has_regressions:
        st.warning(t("eval_compare_summary", when=when, before=before, after=after))
    elif rows:
        st.caption(t("eval_compare_summary", when=when, before=before, after=after))
    else:
        text = t("eval_compare_clean", when=when, before=before, after=after)
        _html_block(
            '<div class="tc-banner">'
            f'<span class="tc-banner-icon">\u2713</span>'
            f"<span>{html.escape(text)}</span></div>"
        )

    if comparison.model_changed:
        st.caption(
            t(
                "eval_compare_model",
                before=_fmt_model(comparison.baseline_model),
                after=_fmt_model(comparison.current_model),
            )
        )
    if comparison.rag_changed:
        st.caption(
            t(
                "eval_compare_rag",
                before=_rag_label(comparison.baseline_rag),
                after=_rag_label(comparison.current_rag),
            )
        )
    if comparison.repeats_changed:
        st.caption(
            t(
                "eval_compare_repeats",
                before=comparison.baseline_repeats,
                after=comparison.current_repeats,
            )
        )

    if rows:
        with st.container(key="eval_comparison_table"):
            _html_block(
                _table_html(
                    [
                        t("eval_compare_scenario"),
                        t("eval_compare_change"),
                        t("eval_compare_detail"),
                    ],
                    rows,
                )
            )


def _check_label(kind: str) -> str:
    """Return the translated label of an evaluation check kind."""
    return t(f"kind_{kind}")


def _rag_label(state: str) -> str:
    """Return the translated label of a sweep's wiki retrieval state."""
    if not state or state == "unknown":
        return t("eval_unknown")
    return t(f"eval_rag_{state}")


def _render_evaluation(editor: dict) -> None:
    """Render the evaluation tab: scenario picker, run control and results.

    The sweep runs the whole pipeline once per scenario, so it happens in a
    background thread and reports every finished scenario live.

    args:
        editor (dict): the sidebar state editor's values, used for the TaIA
            greeting.

    returns:
        None: renders the evaluation half of the app page.
    """
    _html_block(_fairy_html(editor["day"], editor["time"], text=t("eval_fairy")))
    _section(t("eval_title"), t("eval_caption"))
    if not get_settings().llm_provider:
        st.warning(t("eval_need_llm"))

    task = st.session_state.get(_EVALUATION_TASK_KEY)
    running = task is not None and task.status in _ACTIVE_STATUSES

    scenario_ids = st.multiselect(
        t("eval_scenarios"),
        options=[scenario.id for scenario in EVALUATION_SCENARIOS],
        default=[scenario.id for scenario in EVALUATION_SCENARIOS],
        format_func=_scenario_label,
        help=t("eval_scenarios_help"),
        key="eval_scenarios",
    )
    rag_on = st.toggle(t("eval_rag"), value=True, help=t("eval_rag_help"), key="eval_rag")
    planner = st.selectbox(
        t("eval_planner"),
        options=["llm", "deterministic"],
        index=0 if get_settings().planner == "llm" else 1,
        format_func=lambda value: t(f"eval_planner_{value}"),
        help=t("eval_planner_help"),
        key="eval_planner_engine",
    )

    with st.container(key="eval_actions"):
        run_col, stop_col = st.columns([3, 2])
        with run_col:
            run = st.button(
                t("eval_run"),
                type="primary",
                use_container_width=True,
                disabled=running or not scenario_ids,
                key="eval_run_button",
            )
        with stop_col:
            stop = st.button(
                t("eval_stop"),
                use_container_width=True,
                disabled=not running,
                key="eval_stop_button",
            )

    if stop and running:
        task.stop_event.set()
        task.status = "stopping"
        st.rerun()

    if run and not running and scenario_ids:
        _start_evaluation_task(scenario_ids, rag_on, planner)
        st.rerun()

    load_col, hint_col = st.columns([1, 3])
    with load_col:
        load = st.button(t("eval_load_last"), key="eval_load_button")
    with hint_col:
        report_path = _saved_report_path()
        if report_path is not None:
            st.caption(t("eval_saved_report", path=f"`{report_path}`"))
    if load:
        saved = load_report()
        if saved is None:
            st.info(t("eval_no_saved_report"))
        else:
            st.session_state[_EVALUATION_REPORT_KEY] = saved

    task = st.session_state.get(_EVALUATION_TASK_KEY)
    if task is not None and task.status in _ACTIVE_STATUSES:
        # Block here, redrawing only when a scenario finishes. The final
        # rerun renders the report below.
        _evaluation_live(task)
        st.rerun()

    if task is not None:
        if task.status == "stopped":
            st.warning(t("eval_stopped"))
        if task.error:
            st.error(task.error)
        # The worker stamps the report it saved, so the card shown right after
        # the sweep carries the same engine and RAG metadata as the stored
        # file; an interrupted sweep falls back to what the task collected.
        report = task.report or EvaluationReport(
            results=task.results,
            rag_on=task.rag_on,
            planner=task.planner,
            repeats=task.repeats,
        )
        _render_evaluation_results(report)
        return

    # No sweep in this session: show the report restored from disk.
    saved = st.session_state.get(_EVALUATION_REPORT_KEY)
    if saved is not None:
        _render_evaluation_results(saved)
