"""Sweep-vs-history comparison: regressions are flagged, gaps are not."""

from __future__ import annotations

from app.evaluation.comparison import compare_reports, select_baseline
from app.evaluation.models import EvaluationIssue, EvaluationReport, ScenarioResult
from app.evaluation.storage import get_history_dir, load_history

_BASE_TIME = "2026-10-21T09:00:00+00:00"


def _result(
    scenario_id: str,
    passed: bool,
    *,
    model: str = "llama3.2",
    kinds: tuple[str, ...] = (),
    error: str = "",
) -> ScenarioResult:
    """Build one scenario result with the requested failure kinds."""
    return ScenarioResult(
        scenario_id=scenario_id,
        passed=passed,
        model=model,
        error=error,
        issues=[
            EvaluationIssue(severity="error", kind=kind, message=f"{kind} failed") for kind in kinds
        ],
    )


def _report(
    *results: ScenarioResult,
    rag_on: bool | None = True,
    repeats: int = 1,
    created_at: str = _BASE_TIME,
) -> EvaluationReport:
    """Build a report with stable metadata."""
    return EvaluationReport(
        results=list(results),
        rag_on=rag_on,
        repeats=repeats,
        created_at=created_at,
    )


def _statuses(comparison) -> dict[str, str]:
    """Map each scenario id to its comparison status."""
    return {change.scenario_id: change.status for change in comparison.changes}


def test_unchanged_sweep_reports_no_regressions():
    """Identical outcomes are all ``same`` and the pass rate does not move."""
    baseline = _report(_result("anju-kafei", True), _result("deed-chain", False))
    current = _report(_result("anju-kafei", True), _result("deed-chain", False))

    comparison = compare_reports(current, baseline)

    assert _statuses(comparison) == {"anju-kafei": "same", "deed-chain": "same"}
    assert comparison.has_regressions is False
    assert comparison.pass_rate_delta == 0.0
    assert comparison.current_passed == comparison.baseline_passed == 1
    assert comparison.current_total == comparison.baseline_total == 2


def test_pass_to_fail_is_a_regression_with_its_new_failure_kinds():
    """A scenario that passed before and fails now is a regression."""
    baseline = _report(_result("anju-kafei", True))
    current = _report(_result("anju-kafei", False, kinds=("temporal_ordering", "prerequisites")))

    comparison = compare_reports(current, baseline)

    change = comparison.changes[0]
    assert change.status == "regressed"
    assert change.previous is True
    assert change.current is False
    assert change.new_failure_kinds == ["prerequisites", "temporal_ordering"]
    assert comparison.has_regressions is True
    assert [item.scenario_id for item in comparison.regressions] == ["anju-kafei"]
    assert comparison.pass_rate_delta == -1.0


def test_fail_to_pass_is_an_improvement():
    """The other direction is reported as an improvement, not a regression."""
    baseline = _report(_result("deed-chain", False, kinds=("objective_achievement",)))
    current = _report(_result("deed-chain", True))

    comparison = compare_reports(current, baseline)

    assert comparison.changes[0].status == "improved"
    assert comparison.changes[0].new_failure_kinds == []
    assert comparison.improvements[0].scenario_id == "deed-chain"
    assert comparison.has_regressions is False
    assert comparison.pass_rate_delta == 1.0


def test_partial_sweeps_report_new_and_missing_instead_of_regressions():
    """A scenario absent on one side is a gap, never a quality drop."""
    baseline = _report(_result("anju-kafei", True), _result("deed-chain", True))
    current = _report(_result("anju-kafei", True), _result("romani-ranch", True))

    comparison = compare_reports(current, baseline)

    assert _statuses(comparison) == {
        "anju-kafei": "same",
        "deed-chain": "missing",
        "romani-ranch": "new",
    }
    assert comparison.has_regressions is False
    assert comparison.changes[1].previous is True
    assert comparison.changes[1].current is None
    assert comparison.changes[2].previous is None
    assert comparison.changes[2].current is True


def test_repeats_count_as_one_scenario_and_any_failure_wins():
    """With ``--repeat`` a scenario passes only when every run passed."""
    baseline = _report(_result("anju-kafei", True), _result("anju-kafei", True), repeats=2)
    current = _report(_result("anju-kafei", True), _result("anju-kafei", False), repeats=2)

    comparison = compare_reports(current, baseline)

    assert len(comparison.changes) == 1
    assert comparison.changes[0].status == "regressed"
    # The report-level counts still describe every run.
    assert comparison.baseline_passed == 2
    assert comparison.current_passed == 1


def test_new_failure_kinds_only_list_kinds_the_baseline_did_not_have():
    """A regression caused by another check names only the new failing check."""
    baseline = _report(_result("anju-kafei", False, kinds=("plan_shape",)))
    current = _report(_result("anju-kafei", False, kinds=("plan_shape",)))

    comparison = compare_reports(current, baseline)

    assert comparison.changes[0].status == "same"
    assert comparison.changes[0].new_failure_kinds == []


def test_metadata_differences_are_flagged():
    """A different model, wiki flag or repeat count marks the sweep as incomparable."""
    baseline = _report(
        _result("anju-kafei", True, model="llama3.2"),
        rag_on=True,
        repeats=1,
        created_at="2026-10-21T09:00:00+00:00",
    )
    current = _report(
        _result("anju-kafei", True, model="gpt-5"),
        rag_on=False,
        repeats=3,
        created_at="2026-10-22T09:00:00+00:00",
    )

    comparison = compare_reports(current, baseline)

    assert comparison.model_changed is True
    assert comparison.rag_changed is True
    assert comparison.repeats_changed is True
    assert comparison.baseline_model == "llama3.2"
    assert comparison.current_model == "gpt-5"
    assert comparison.baseline_rag == "on"
    assert comparison.current_rag == "off"
    assert comparison.baseline_created_at == "2026-10-21T09:00:00+00:00"


def test_select_baseline_returns_the_newest_sweep():
    """The most recent stored sweep is the default baseline."""
    newest = _report(_result("anju-kafei", True), created_at="2026-10-22T09:00:00+00:00")
    older = _report(_result("anju-kafei", True), created_at="2026-10-20T09:00:00+00:00")
    current = _report(_result("anju-kafei", True), created_at="2026-10-23T09:00:00+00:00")

    assert select_baseline(current, [newest, older]) is newest


def test_select_baseline_skips_the_sweep_being_compared():
    """A sweep already in the history (saved before rendering) is not its own baseline."""
    saved = _report(_result("anju-kafei", True), created_at="2026-10-23T09:00:00+00:00")
    older = _report(_result("anju-kafei", True), created_at="2026-10-22T09:00:00+00:00")

    assert select_baseline(saved, [saved, older]) is older


def test_select_baseline_prefers_the_same_wiki_flag():
    """Comparing a sweep with and without retrieval would compare two things."""
    same_flag = _report(
        _result("anju-kafei", True), rag_on=False, created_at="2026-10-20T09:00:00+00:00"
    )
    newer_other_flag = _report(
        _result("anju-kafei", True), rag_on=True, created_at="2026-10-22T09:00:00+00:00"
    )
    current = _report(
        _result("anju-kafei", True), rag_on=False, created_at="2026-10-23T09:00:00+00:00"
    )

    assert select_baseline(current, [newer_other_flag, same_flag]) is same_flag


def test_select_baseline_falls_back_when_the_flag_differs():
    """Without a same-flag sweep the newest one is still the best baseline."""
    only = _report(_result("anju-kafei", True), rag_on=True, created_at="2026-10-22T09:00:00+00:00")
    current = _report(
        _result("anju-kafei", True), rag_on=False, created_at="2026-10-23T09:00:00+00:00"
    )

    assert select_baseline(current, [only]) is only


def test_select_baseline_returns_none_without_a_usable_sweep():
    """Empty history, the sweep itself and results-less reports are all unusable."""
    current = _report(_result("anju-kafei", True))
    empty = EvaluationReport(rag_on=True, created_at="2026-10-20T09:00:00+00:00")

    assert select_baseline(current, []) is None
    assert select_baseline(current, [current]) is None
    assert select_baseline(current, [empty]) is None


def test_load_history_skips_corrupt_files_and_returns_newest_first(store_dir):
    """One broken artifact must not take the whole comparison down."""
    history = get_history_dir()
    old = _report(_result("anju-kafei", True), created_at="2026-10-20T09:00:00+00:00")
    new = _report(_result("anju-kafei", False), created_at="2026-10-22T09:00:00+00:00")
    (history / "20261020T090000Z.json").write_text(old.model_dump_json(), encoding="utf-8")
    (history / "20261022T090000Z.json").write_text(new.model_dump_json(), encoding="utf-8")
    (history / "20261021T090000Z.json").write_text("{not json", encoding="utf-8")

    reports = load_history()

    assert [report.created_at for report in reports] == [
        "2026-10-22T09:00:00+00:00",
        "2026-10-20T09:00:00+00:00",
    ]


def test_load_history_returns_empty_list_without_a_store(store_dir):
    """No history directory yet means no baseline, not an error."""
    assert load_history() == []
