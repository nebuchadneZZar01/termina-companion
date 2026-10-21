"""Evaluation reports persist to disk and reload without losing a check."""

from __future__ import annotations

import pytest

from app.evaluation.models import EvaluationIssue, EvaluationReport, ScenarioResult
from app.evaluation.storage import (
    LAST_REPORT_NAME,
    get_eval_dir,
    list_reports,
    load_report,
    save_report,
)


@pytest.fixture(autouse=True)
def _report_dir(tmp_path, monkeypatch):
    """Point the report directory inside pytest's tmp_path."""
    monkeypatch.setenv("RAG_QDRANT_PATH", str(tmp_path / "cache" / "qdrant"))


def _report() -> EvaluationReport:
    return EvaluationReport(
        results=[
            ScenarioResult(scenario_id="anju-kafei", passed=True, step_count=4, duration_s=12.4),
            ScenarioResult(
                scenario_id="deed-chain",
                passed=False,
                step_count=3,
                duration_s=9.1,
                error="boom",
                issues=[
                    EvaluationIssue(
                        severity="error",
                        kind="temporal_ordering",
                        message="Step 2 overlaps the previous step.",
                        step_idx=1,
                    )
                ],
            ),
        ]
    )


def test_save_and_load_round_trip():
    """A saved report reloads with every scenario, issue and error intact."""
    path = save_report(_report())
    assert path.name == LAST_REPORT_NAME
    assert path.exists()

    loaded = load_report()
    assert loaded is not None
    assert loaded.total == 2
    assert loaded.passed == 1
    assert loaded.failed == 1
    assert loaded.pass_rate == 0.5

    first, second = loaded.results
    assert first.scenario_id == "anju-kafei"
    assert first.passed is True
    assert first.step_count == 4
    assert second.scenario_id == "deed-chain"
    assert second.error == "boom"
    assert second.issues[0].kind == "temporal_ordering"
    assert second.issues[0].step_idx == 1
    assert second.error_count == 2


def test_save_keeps_a_timestamped_history_copy():
    """Every save leaves a history copy next to the last report."""
    save_report(_report())
    history = list_reports()
    assert len(history) == 1
    assert history[0].parent.name == "evaluations"
    assert history[0].read_text(encoding="utf-8") == (
        save_report(_report(), history=False).read_text(encoding="utf-8")
    )


def test_save_without_history_writes_only_the_last_report():
    """The history copy can be skipped."""
    save_report(_report(), history=False)
    assert list_reports() == []
    assert load_report() is not None


def test_load_missing_file_returns_none():
    """No report on disk means load_report returns None, not an error."""
    assert load_report() is None


def test_load_invalid_json_returns_none():
    """A corrupt report file degrades to None instead of raising."""
    save_report(_report())
    path = get_eval_dir() / LAST_REPORT_NAME
    path.write_text("{not json", encoding="utf-8")
    assert load_report() is None
