"""Phase 11 evaluation: scenarios, per-check failures and the end-to-end run.

The evaluator is deterministic, so every check is exercised with a hand-built
plan: a reference chain that must pass, and mutated plans that must fail with
the expected check kind.
"""

from __future__ import annotations

import pytest

from app.data.mock_knowledge import build_default_knowledge
from app.domain import ClockTime, Goal, Plan, PlanStep, TimeWindow, ValidationResult
from app.evaluation.evaluator import evaluate_plan, relevant_objectives
from app.evaluation.models import EvaluationReport, PlanScenario, ScenarioResult
from app.evaluation.scenarios import EVALUATION_SCENARIOS, SCENARIOS_BY_ID
from app.graph import run_pipeline

_KB = build_default_knowledge()
_QUEST_OF_OBJECTIVE = {
    objective.id: quest.id for quest in _KB.quests for objective in quest.objectives
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clock(t: ClockTime) -> tuple[int, int, int]:
    return (t.day, t.hour, t.minute)


def _later(a: ClockTime, b: ClockTime) -> ClockTime:
    return a if _clock(a) >= _clock(b) else b


def _earlier(a: ClockTime, b: ClockTime) -> ClockTime:
    return a if _clock(a) <= _clock(b) else b


def _add_hour(t: ClockTime) -> ClockTime:
    total = (t.day - 1) * 24 * 60 + t.hour * 60 + t.minute + 60
    day, rem = divmod(total, 24 * 60)
    return ClockTime(day=day + 1, hour=rem // 60, minute=rem % 60)


def _reference_plan(scenario: PlanScenario) -> Plan:
    """Build the chain a correct plan must follow for a scenario.

    args:
        scenario (PlanScenario): the scenario to build the plan for.

    returns:
        Plan: one step per expected objective, chronologically scheduled.
    """
    objectives = {obj.id: obj for obj in relevant_objectives(scenario)}
    steps: list[PlanStep] = []
    earliest = scenario.game_state.time
    for ref in scenario.required_objective_refs:
        objective = objectives[ref]
        start = _later(earliest, objective.window.start)
        end = _earlier(_add_hour(start), objective.window.end)
        if _clock(end) <= _clock(start):
            start, end = objective.window.start, objective.window.end
        steps.append(
            PlanStep(
                title=objective.title,
                objective_ref=ref,
                location=objective.location,
                window=TimeWindow(start=start, end=end),
                requires_items=objective.requires_items,
                requires_masks=objective.requires_masks,
            )
        )
        earliest = end
    return Plan(goal=scenario.goal, steps=steps)


def _tool_calls(scenario: PlanScenario) -> list[str]:
    """The MCP tools a Knowledge Agent must call for a scenario.

    args:
        scenario (PlanScenario): the scenario to derive the calls for.

    returns:
        list[str]: the expected tool calls.
    """
    calls = ["search_quests"]
    for objective in relevant_objectives(scenario):
        if objective.npc_id:
            calls.append(f"get_npc_schedule:{objective.npc_id}")
        if objective.event_ref:
            calls.append(f"get_event:{objective.event_ref}")
    return calls


def _kinds(result: ScenarioResult) -> set[str]:
    return {issue.kind for issue in result.issues if issue.severity == "error"}


# ---------------------------------------------------------------------------
# Scenario integrity
# ---------------------------------------------------------------------------


def test_every_scenario_goal_retrieves_its_expected_objectives():
    """Each goal surfaces the objectives the scenario expects."""
    for scenario in EVALUATION_SCENARIOS:
        retrieved = {obj.id for obj in relevant_objectives(scenario)}
        missing = set(scenario.required_objective_refs) - retrieved
        assert not missing, f"{scenario.id}: {sorted(missing)} were not retrieved"


def test_every_scenario_goal_retrieves_a_single_quest():
    """Each goal is specific enough to match one quest only."""
    for scenario in EVALUATION_SCENARIOS:
        quests = {_QUEST_OF_OBJECTIVE[obj.id] for obj in relevant_objectives(scenario)}
        assert len(quests) == 1, f"{scenario.id} matched {sorted(quests)}"


def test_scenario_ids_are_unique():
    """Scenario ids identify one scenario each."""
    ids = [scenario.id for scenario in EVALUATION_SCENARIOS]
    assert len(ids) == len(set(ids))
    assert set(ids) == set(SCENARIOS_BY_ID)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", EVALUATION_SCENARIOS, ids=lambda s: s.id)
def test_reference_plan_passes_every_scenario(scenario: PlanScenario):
    """The chain a correct plan follows passes every check."""
    result = evaluate_plan(_reference_plan(scenario), scenario, tool_calls=_tool_calls(scenario))
    assert result.passed, [issue.message for issue in result.issues]
    assert not _kinds(result)


def test_missing_objective_fails_the_achievement_check():
    """A plan that stops short of the goal fails."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]
    plan = _reference_plan(scenario)
    plan.steps = plan.steps[:-1]

    result = evaluate_plan(plan, scenario, tool_calls=_tool_calls(scenario))

    assert not result.passed
    assert "objective_achievement" in _kinds(result)


def test_forbidden_objective_fails_the_achievement_check():
    """A plan containing a forbidden objective fails."""
    scenario = SCENARIOS_BY_ID["mikau-with-zora-mask"]
    plan = _reference_plan(scenario)
    objectives = {obj.id: obj for obj in relevant_objectives(scenario)}
    owned = objectives["mm_get_zora_mask"]
    plan.steps.append(
        PlanStep(
            title=owned.title,
            objective_ref=owned.id,
            location=owned.location,
            window=TimeWindow(start=ClockTime(day=1, hour=7), end=ClockTime(day=1, hour=8)),
        )
    )

    result = evaluate_plan(plan, scenario, tool_calls=_tool_calls(scenario))

    assert not result.passed
    assert "objective_achievement" in _kinds(result)


def test_step_outside_its_slot_fails_the_temporal_check():
    """A step scheduled outside its objective's window fails."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]
    plan = _reference_plan(scenario)
    plan.steps[1].window = TimeWindow(start=ClockTime(day=1, hour=9), end=ClockTime(day=1, hour=10))

    result = evaluate_plan(plan, scenario, tool_calls=_tool_calls(scenario))

    assert not result.passed
    assert "temporal_ordering" in _kinds(result)


def test_overlapping_steps_fail_the_temporal_check():
    """Two steps that overlap in time fail."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]
    plan = _reference_plan(scenario)
    plan.steps[1].window = TimeWindow(start=ClockTime(day=2, hour=8), end=ClockTime(day=2, hour=9))

    result = evaluate_plan(plan, scenario, tool_calls=_tool_calls(scenario))

    assert not result.passed
    assert "temporal_ordering" in _kinds(result)


def test_step_before_the_current_time_fails_the_temporal_check():
    """A plan that starts in the past fails."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]
    plan = _reference_plan(scenario)
    plan.steps[0].window = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))

    result = evaluate_plan(plan, scenario, tool_calls=_tool_calls(scenario))

    assert not result.passed
    assert "temporal_ordering" in _kinds(result)


def test_out_of_order_steps_fail_the_temporal_check():
    """A chain that swaps two steps fails."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]
    plan = _reference_plan(scenario)
    plan.steps[1], plan.steps[2] = plan.steps[2], plan.steps[1]

    result = evaluate_plan(plan, scenario, tool_calls=_tool_calls(scenario))

    assert not result.passed
    assert "temporal_ordering" in _kinds(result)


def test_missing_prerequisite_fails_the_prerequisite_check():
    """A plan that skips the step handing over an item fails."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]
    plan = _reference_plan(scenario)
    plan.steps = [step for step in plan.steps if step.objective_ref != "ak_get_letter"]

    result = evaluate_plan(plan, scenario, tool_calls=_tool_calls(scenario))

    assert not result.passed
    assert "prerequisites" in _kinds(result)


def test_missing_tool_call_fails_the_tool_usage_check():
    """A run that never asked for the NPC schedules fails."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]

    result = evaluate_plan(_reference_plan(scenario), scenario, tool_calls=["search_quests"])

    assert not result.passed
    assert "tool_usage" in _kinds(result)


def test_missing_plan_fails_the_shape_check():
    """A run that produced no plan fails."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]

    result = evaluate_plan(None, scenario, tool_calls=_tool_calls(scenario))

    assert not result.passed
    assert "plan_shape" in _kinds(result)


def test_critic_rejection_fails_the_critic_check():
    """A plan the Critic rejected fails even if it satisfies the scenario."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]
    validation = ValidationResult(valid=False)

    result = evaluate_plan(
        _reference_plan(scenario),
        scenario,
        tool_calls=_tool_calls(scenario),
        validation=validation,
    )

    assert not result.passed
    assert "critic" in _kinds(result)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def test_report_aggregates_pass_rate_and_failure_kinds():
    """The report counts passes, failures and the failing check kinds."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]
    passed = evaluate_plan(_reference_plan(scenario), scenario, tool_calls=_tool_calls(scenario))
    broken = evaluate_plan(None, scenario, tool_calls=_tool_calls(scenario))

    report = EvaluationReport(results=[passed, broken])

    assert report.total == 2
    assert report.passed == 1
    assert report.failed == 1
    assert report.pass_rate == 0.5
    assert report.failures_by_kind == {"plan_shape": 1}


# ---------------------------------------------------------------------------
# End-to-end: the pipeline output satisfies its scenario
# ---------------------------------------------------------------------------


def test_pipeline_run_satisfies_the_scenario(monkeypatch):
    """A real pipeline run produces a plan the scenario accepts."""
    from app.agents import planning_agent

    scenario = SCENARIOS_BY_ID["anju-kafei"]

    class _ChainModel:
        model_name = "chain-model"

        def with_structured_output(self, _schema):
            return self

        def invoke(self, _messages, **_kwargs):
            objectives = {obj.id: obj for obj in relevant_objectives(scenario)}
            steps = []
            for ref in scenario.required_objective_refs:
                objective = objectives[ref]
                steps.append(
                    {
                        "title": objective.title,
                        "objective_ref": ref,
                        "location": objective.location,
                        "window": {
                            "start": objective.window.start.model_dump(mode="json"),
                            "end": objective.window.end.model_dump(mode="json"),
                        },
                        "depends_on": [],
                    }
                )
            return {"goal": scenario.goal, "steps": steps}

    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **_kwargs: _ChainModel())

    result = run_pipeline(scenario.game_state, Goal(description=scenario.goal))

    assert result.tool_calls, "the Knowledge Agent must record its MCP calls"
    outcome = evaluate_plan(
        result.plan,
        scenario,
        tool_calls=result.tool_calls,
        validation=result.validation,
    )
    assert outcome.passed, [issue.message for issue in outcome.issues]
