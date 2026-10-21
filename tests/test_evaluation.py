"""Plan evaluation: scenarios, per-check failures and the end-to-end run.

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
from app.graph import MAX_PLANNING_ATTEMPTS, run_pipeline
from app.state import AttemptRecord

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
# Trajectory
# ---------------------------------------------------------------------------


def _accepted_attempt(**overrides) -> AttemptRecord:
    """A single accepted attempt, the shape a clean run records.

    args:
        **overrides: field values replacing the accepted defaults.

    returns:
        AttemptRecord: the attempt record.
    """
    fields = {
        "attempt": 1,
        "step_count": 3,
        "valid": True,
        "issue_kinds": [],
    }
    fields.update(overrides)
    return AttemptRecord(**fields)


def _validation(valid: bool = True) -> ValidationResult:
    return ValidationResult(valid=valid)


def test_run_without_tool_calls_fails_the_trajectory_check():
    """A recorded run that never consulted the MCP tools fails."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]

    result = evaluate_plan(
        _reference_plan(scenario),
        scenario,
        tool_calls=[],
        validation=_validation(),
        attempt_log=[_accepted_attempt()],
    )

    assert not result.passed
    assert "trajectory_order" in _kinds(result)


def test_run_without_a_critic_verdict_fails_the_trajectory_check():
    """A recorded run the Critic never judged fails."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]

    result = evaluate_plan(
        _reference_plan(scenario),
        scenario,
        tool_calls=_tool_calls(scenario),
        validation=None,
        attempt_log=[_accepted_attempt()],
    )

    assert not result.passed
    assert "trajectory_order" in _kinds(result)


def test_hand_builded_plans_are_exempt_from_the_trajectory_check():
    """Evaluating a plan without a recorded trajectory stays clean."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]

    result = evaluate_plan(_reference_plan(scenario), scenario, tool_calls=_tool_calls(scenario))

    assert result.passed
    assert not any(issue.kind == "trajectory_order" for issue in result.issues)


def test_accepted_on_the_first_attempt_is_silent():
    """A clean run records one attempt and raises nothing."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]

    result = evaluate_plan(
        _reference_plan(scenario),
        scenario,
        tool_calls=_tool_calls(scenario),
        validation=_validation(),
        attempt_log=[_accepted_attempt()],
    )

    assert result.passed
    assert not any(issue.kind == "replan_bound" for issue in result.issues)


def test_accepted_only_after_replanning_warns():
    """The plan passes, but a late acceptance is flagged."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]
    attempts = [
        _accepted_attempt(attempt=1, valid=False, issue_kinds=["prerequisites"]),
        _accepted_attempt(attempt=2),
    ]

    result = evaluate_plan(
        _reference_plan(scenario),
        scenario,
        tool_calls=_tool_calls(scenario),
        validation=_validation(),
        attempt_log=attempts,
    )

    assert result.passed
    warnings = [issue for issue in result.issues if issue.kind == "replan_bound"]
    assert warnings and warnings[0].severity == "warning"


def test_more_attempts_than_the_bound_fails():
    """A run that overshot the attempt bound fails."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]
    attempts = [_accepted_attempt(attempt=index) for index in range(1, MAX_PLANNING_ATTEMPTS + 2)]

    result = evaluate_plan(
        _reference_plan(scenario),
        scenario,
        tool_calls=_tool_calls(scenario),
        validation=_validation(),
        attempt_log=attempts,
    )

    assert not result.passed
    assert "replan_bound" in _kinds(result)


def test_a_full_proposal_is_silent():
    """A proposal covering every expected objective raises nothing."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]

    result = evaluate_plan(
        _reference_plan(scenario),
        scenario,
        tool_calls=_tool_calls(scenario),
        validation=_validation(),
        plan_proposal=_reference_plan(scenario),
        attempt_log=[_accepted_attempt()],
    )

    assert result.passed
    assert not any(issue.kind == "proposal_fidelity" for issue in result.issues)


def test_a_proposal_missing_objectives_warns():
    """A thin proposal is a warning: the rebuild repaired it."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]
    full = _reference_plan(scenario)
    thin = Plan(goal=full.goal, steps=full.steps[:1])

    result = evaluate_plan(
        full,
        scenario,
        tool_calls=_tool_calls(scenario),
        validation=_validation(),
        plan_proposal=thin,
        attempt_log=[_accepted_attempt()],
    )

    assert result.passed
    warnings = [issue for issue in result.issues if issue.kind == "proposal_fidelity"]
    assert warnings and warnings[0].severity == "warning"


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


def test_run_errors_are_counted_as_failures():
    """A crashed run is a failure, never a scenario without issues."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]
    crashed = ScenarioResult(
        scenario_id=scenario.id,
        passed=False,
        step_count=0,
        duration_s=1.5,
        error="PlanningAgentError: LLM invocation failed",
    )

    report = EvaluationReport(results=[crashed])

    assert report.failed == 1
    assert report.pass_rate == 0.0
    assert report.failures_by_kind == {"run_error": 1}
    assert crashed.error_count == 1


def test_report_exposes_the_models_that_produced_the_plans():
    """The report names its producing models, once, even across repeats."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]
    results = [
        ScenarioResult(scenario_id=scenario.id, passed=True, model="llama3.2"),
        ScenarioResult(scenario_id=scenario.id, passed=True, model="llama3.2"),
        ScenarioResult(scenario_id=scenario.id, passed=True, model="gemma4"),
    ]

    report = EvaluationReport(results=results)

    assert report.models == "gemma4, llama3.2"
    assert EvaluationReport(results=[ScenarioResult(scenario_id=scenario.id)]).models == ""


def test_report_reports_what_the_wiki_retrieval_actually_did():
    """A degraded sweep is not labelled as if the retrieval had run."""
    scenario = SCENARIOS_BY_ID["anju-kafei"]

    def _result(status: str) -> ScenarioResult:
        return ScenarioResult(scenario_id=scenario.id, passed=True, retrieval_status=status)

    # RAG switched off: nothing was attempted.
    assert EvaluationReport(results=[_result("")], rag_on=False).wiki_retrieval == "off"
    # Asked for and healthy: every leg hit the cache or the wiki.
    assert EvaluationReport(results=[_result("cache_hit")], rag_on=True).wiki_retrieval == "on"
    assert EvaluationReport(results=[_result("wiki_ingested")], rag_on=True).wiki_retrieval == "on"
    # One leg failed to run at all: the sweep must say so, even when the
    # others were fine.
    assert (
        EvaluationReport(
            results=[_result("cache_hit"), _result("unavailable")], rag_on=True
        ).wiki_retrieval
        == "degraded"
    )
    # A wiki_miss is an ordinary outcome (nothing relevant found), not a
    # failure: a sweep full of them still ran.
    assert EvaluationReport(results=[_result("wiki_miss")], rag_on=True).wiki_retrieval == "on"
    # An older report recorded no status and no flag.
    assert EvaluationReport(results=[_result("")]).wiki_retrieval == "unknown"
    assert EvaluationReport().wiki_retrieval == "unknown"


def test_run_scenarios_records_the_sweep_metadata(monkeypatch):
    """The sweep report carries the RAG flag and the producing model."""
    from app.evaluation import runner

    scenario = SCENARIOS_BY_ID["anju-kafei"]

    def _fake_run_scenario(item):
        """Stand in for the pipeline run, no LLM involved."""
        return ScenarioResult(scenario_id=item.id, passed=True, model="test-model")

    monkeypatch.setattr(runner, "run_scenario", _fake_run_scenario)

    report = runner.run_scenarios([scenario], rag_on=False)

    assert report.rag_on is False
    assert report.models == "test-model"
    assert [result.scenario_id for result in report.results] == [scenario.id]


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
    assert result.plan_model == "chain-model"
    assert result.plan_proposal is not None, "the planner must keep its raw proposal"
    assert result.attempt_log, "the critic must record one attempt"
    outcome = evaluate_plan(
        result.plan,
        scenario,
        tool_calls=result.tool_calls,
        validation=result.validation,
    )
    assert outcome.passed, [issue.message for issue in outcome.issues]
