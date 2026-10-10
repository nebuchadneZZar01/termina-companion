"""Shape tests for live calibration scenarios (offline, no network)."""

from __future__ import annotations

from app.rag.scenarios import CALIBRATION_SCENARIOS


def test_calibration_scenarios_cover_quests() -> None:
    assert len(CALIBRATION_SCENARIOS) >= 12
    ids = {scenario.id for scenario in CALIBRATION_SCENARIOS}
    assert any("anju" in scenario_id for scenario_id in ids)
    assert any("darmani" in scenario_id for scenario_id in ids)
    assert any("romani" in scenario_id for scenario_id in ids)
    for scenario in CALIBRATION_SCENARIOS:
        assert scenario.query.strip()
        assert scenario.expected_titles or scenario.expected_page_ids
        assert scenario.top_k > 0
