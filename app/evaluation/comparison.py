"""Compare an evaluation sweep with a stored baseline to flag regressions.

A sweep is only meaningful as a trend: a plan that passed yesterday and fails
today is a regression even when the aggregate pass rate looks acceptable. The
comparison is deliberately pure — it takes two :class:`EvaluationReport`
objects and returns a :class:`SweepComparison` — so the CLI harness and the
Streamlit tab report the same verdict.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.evaluation.models import (
    EvaluationReport,
    ScenarioChange,
    SweepComparison,
)


def _scenario_outcomes(
    report: EvaluationReport,
) -> tuple[dict[str, bool], dict[str, set[str]]]:
    """Collapse a report's results into one outcome per scenario id.

    ``--repeat`` runs the same scenario several times, so a scenario counts as
    passed only when every one of its runs passed: a flaky failure is still a
    failure. The error-severity check kinds are kept for the regression detail.

    args:
        report (EvaluationReport): the report to summarize.

    returns:
        tuple[dict[str, bool], dict[str, set[str]]]: scenario id to outcome,
        and scenario id to the check kinds that failed there.
    """
    outcomes: dict[str, bool] = {}
    kinds: dict[str, set[str]] = {}
    for result in report.results:
        scenario = result.scenario_id
        outcomes[scenario] = outcomes.get(scenario, True) and result.passed
        kinds.setdefault(scenario, set()).update(
            issue.kind for issue in result.issues if issue.severity == "error"
        )
    return outcomes, kinds


def compare_reports(current: EvaluationReport, baseline: EvaluationReport) -> SweepComparison:
    """Compare a sweep with a baseline and classify every scenario.

    A scenario present in only one of the sweeps is reported as ``new`` or
    ``missing``, never as a regression: a partial sweep must not be mistaken
    for a quality drop, and hiding the gap would misrepresent the delta.

    args:
        current (EvaluationReport): the sweep that just finished.
        baseline (EvaluationReport): the sweep to compare it against.

    returns:
        SweepComparison: the per-scenario changes plus the metadata of both
        sides, so a renderer needs nothing else.
    """
    current_outcomes, current_kinds = _scenario_outcomes(current)
    baseline_outcomes, baseline_kinds = _scenario_outcomes(baseline)
    changes: list[ScenarioChange] = []
    for scenario_id in sorted(set(current_outcomes) | set(baseline_outcomes)):
        previous = baseline_outcomes.get(scenario_id)
        outcome = current_outcomes.get(scenario_id)
        if previous is None:
            status = "new"
        elif outcome is None:
            status = "missing"
        elif previous and not outcome:
            status = "regressed"
        elif outcome and not previous:
            status = "improved"
        else:
            status = "same"
        new_kinds = sorted(
            current_kinds.get(scenario_id, set()) - baseline_kinds.get(scenario_id, set())
        )
        changes.append(
            ScenarioChange(
                scenario_id=scenario_id,
                previous=previous,
                current=outcome,
                status=status,
                new_failure_kinds=new_kinds if status == "regressed" else [],
            )
        )
    return SweepComparison(
        baseline_created_at=baseline.created_at,
        baseline_model=baseline.models,
        baseline_planner=baseline.planner,
        baseline_rag=baseline.wiki_retrieval,
        baseline_passed=baseline.passed,
        baseline_total=baseline.total,
        baseline_repeats=baseline.repeats,
        current_model=current.models,
        current_planner=current.planner,
        current_rag=current.wiki_retrieval,
        current_passed=current.passed,
        current_total=current.total,
        current_repeats=current.repeats,
        changes=changes,
    )


def _planner_compatible(current: EvaluationReport, baseline: EvaluationReport) -> bool:
    """Whether two sweeps may be compared at all.

    A report saved before the ablation existed carries no planner engine and is
    still compatible — refusing to compare would throw away the whole history.
    Two recorded engines that differ are never compared: a deterministic sweep
    against an LLM sweep measures the engine switch, not the change under
    test, so a regression there would be an artifact.

    args:
        current (EvaluationReport): the sweep being compared.
        baseline (EvaluationReport): the stored candidate.

    returns:
        bool: True when the engines are unknown or equal.
    """
    return not current.planner or not baseline.planner or current.planner == baseline.planner


def select_baseline(
    current: EvaluationReport, candidates: Sequence[EvaluationReport]
) -> EvaluationReport | None:
    """Pick the stored sweep to compare against.

    The candidates are expected newest first, as :func:`load_history` returns
    them. A sweep is never compared with itself: a report with the same
    ``created_at`` is skipped, so computing the comparison after saving the
    new report is safe.

    A candidate from a different planner engine is discarded outright (see
    :func:`_planner_compatible`), because the two sweeps would not measure the
    same thing. Within the compatible ones, preference goes to the newest sweep
    run with the same wiki flag — comparing a sweep with and without retrieval
    measures a different thing too — then to the newest compatible sweep.

    args:
        current (EvaluationReport): the sweep being compared.
        candidates (Sequence[EvaluationReport]): the stored sweeps, newest
            first.

    returns:
        EvaluationReport | None: the baseline, or None when no stored sweep is
        compatible.
    """
    usable = [
        report
        for report in candidates
        if report.results
        and report.created_at != current.created_at
        and _planner_compatible(current, report)
    ]
    if not usable:
        return None
    same_rag = [report for report in usable if report.rag_on == current.rag_on]
    return same_rag[0] if same_rag else usable[0]
