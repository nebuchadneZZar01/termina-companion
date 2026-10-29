"""Plan evaluation: scenarios, per-check failures and the end-to-end run.

The evaluator is deterministic, so every check is exercised with a hand-built
plan: a reference chain that must pass, and mutated plans that must fail with
the expected check kind.
"""

from __future__ import annotations

import pytest

from app.data.mock_knowledge import build_default_knowledge
from app.domain import (
    ClockTime,
    Goal,
    Plan,
    PlanStep,
    TimeWindow,
    ValidationIssue,
    ValidationResult,
)
from app.domain import (
    clock_key as _clock,
)
from app.evaluation.evaluator import evaluate_plan, relevant_objectives
from app.evaluation.models import EvaluationReport, PlanScenario, ScenarioResult
from app.evaluation.scenarios import EVALUATION_SCENARIOS, SCENARIOS_BY_ID
from app.graph import MAX_PLANNING_ATTEMPTS, run_pipeline
from app.state import AttemptRecord, PlanningState

_KB = build_default_knowledge()
_QUEST_OF_OBJECTIVE = {
    objective.id: quest.id for quest in _KB.quests for objective in quest.objectives
}
#: Scenarios that expect a plan; the unreachable ones have their own checks.
_PLAN_SCENARIOS = [
    scenario for scenario in EVALUATION_SCENARIOS if scenario.expected_outcome == "plan"
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _later(a: ClockTime, b: ClockTime) -> ClockTime:
    return a if _clock(a) >= _clock(b) else b


def _earlier(a: ClockTime, b: ClockTime) -> ClockTime:
    return a if _clock(a) <= _clock(b) else b


def _add_hour(t: ClockTime) -> ClockTime:
    """Move one hour forward on the 06:00-29:59 cycle."""
    total = (t.day - 1) * 24 * 60 + (t.hour - 6) * 60 + t.minute + 60
    total = min(max(total, 0), 3 * 24 * 60 - 1)
    day, rem = divmod(total, 24 * 60)
    return ClockTime(day=day + 1, hour=rem // 60 + 6, minute=rem % 60)


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


@pytest.mark.parametrize("scenario", _PLAN_SCENARIOS, ids=lambda s: s.id)
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
    owned = objectives["mm_heal_mikau"]
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
    plan.steps = [step for step in plan.steps if step.objective_ref != "ak_meet_in_kitchen"]

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
# Unreachable outcome
# ---------------------------------------------------------------------------


def _unreachable_verdict() -> ValidationResult:
    """The Critic verdict of a chain the clock has closed."""
    return ValidationResult(
        valid=False,
        issues=[
            ValidationIssue(
                severity="error",
                kind="unreachable",
                message=(
                    "Anju and Kafei: Get Kafei's Mask from Madame Aroma: its window "
                    "ended at Day 1, 20:00. Use the Song of Time to restart the cycle."
                ),
            )
        ],
    )


def _late_scenario() -> PlanScenario:
    return SCENARIOS_BY_ID["anju-kafei-late"]


def test_the_late_scenario_clock_closes_every_objective():
    """The unreachable scenario is pinned to a clock that closes every window."""
    from app.agents.planning_chain import dead_for

    scenario = _late_scenario()
    objectives = relevant_objectives(scenario)
    state = PlanningState(
        game_state=scenario.game_state,
        goal=Goal(description=scenario.goal),
        relevant_objectives=objectives,
    )

    dead = dead_for(state)

    assert objectives, "the goal must still retrieve the chain"
    alive = sorted(objective.id for objective in objectives if objective.id not in dead)
    assert not alive, f"still reachable at {scenario.game_state.time}: {alive}"


def test_unreachable_scenario_passes_with_an_empty_plan_and_its_verdict():
    """No plan plus the unreachable verdict is exactly the expected outcome."""
    scenario = _late_scenario()

    result = evaluate_plan(
        Plan(goal=scenario.goal),
        scenario,
        plan_engine="unreachable",
        validation=_unreachable_verdict(),
    )

    assert result.passed, [issue.message for issue in result.issues]
    assert result.step_count == 0
    assert result.error_count == 0


def test_unreachable_scenario_fails_when_a_plan_is_produced():
    """A plan at a clock that closed the chain is a failure, not a bonus."""
    scenario = _late_scenario()
    plan = Plan(
        goal=scenario.goal,
        steps=[
            PlanStep(
                title="Reunite Anju and Kafei",
                objective_ref="ak_reunite",
                location="Stockpot Inn",
                window=TimeWindow(start=ClockTime(day=3, hour=24), end=ClockTime(day=3, hour=25)),
            )
        ],
    )

    result = evaluate_plan(plan, scenario, plan_engine="llm", validation=_unreachable_verdict())

    assert not result.passed
    assert "outcome" in _kinds(result)
    assert result.step_count == 1


def test_unreachable_scenario_fails_when_the_planner_called_the_llm():
    """An empty plan from the LLM engine means the short-circuit did not fire."""
    result = evaluate_plan(
        Plan(goal=_late_scenario().goal),
        _late_scenario(),
        plan_engine="llm",
        validation=_unreachable_verdict(),
    )

    assert not result.passed
    assert "outcome" in _kinds(result)
    assert any("plan_engine" in issue.message for issue in result.issues)


def test_unreachable_scenario_fails_without_a_critic_verdict():
    """The verdict is the evidence: without it the outcome is unproven."""
    result = evaluate_plan(
        Plan(goal=_late_scenario().goal),
        _late_scenario(),
        plan_engine="unreachable",
        validation=None,
    )

    assert not result.passed
    assert "outcome" in _kinds(result)


def test_unreachable_scenario_fails_when_the_critic_accepted():
    """A Critic that accepted the run contradicts the expected outcome."""
    result = evaluate_plan(
        Plan(goal=_late_scenario().goal),
        _late_scenario(),
        plan_engine="unreachable",
        validation=ValidationResult(valid=True),
    )

    assert not result.passed
    assert "outcome" in _kinds(result)


def test_unreachable_scenario_fails_on_a_different_critic_reason():
    """A generic rejection is not the temporal verdict the scenario expects."""
    verdict = ValidationResult(
        valid=False,
        issues=[ValidationIssue(severity="error", kind="empty", message="No steps.")],
    )

    result = evaluate_plan(
        Plan(goal=_late_scenario().goal),
        _late_scenario(),
        plan_engine="unreachable",
        validation=verdict,
    )

    assert not result.passed
    assert "outcome" in _kinds(result)
    assert any("empty" in issue.message for issue in result.issues)


@pytest.mark.parametrize(
    "overrides",
    [
        {"required_objective_refs": ["ak_reunite"]},
        {"terminal_objective_ref": "ak_reunite"},
        {"expected_order": [("ak_get_kafei_mask", "ak_reunite")]},
        {"min_steps": 1},
    ],
    ids=["required", "terminal", "order", "min_steps"],
)
def test_an_unreachable_scenario_rejects_plan_expectations(overrides):
    """Expecting no plan and expecting steps at once is a contradiction."""
    payload = _late_scenario().model_dump()
    payload.update(overrides)

    with pytest.raises(ValueError, match="unreachable scenario cannot expect a plan"):
        PlanScenario.model_validate(payload)


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
    # The message names the objectives by title, not by internal ref.
    titles = {obj.id: obj.title for obj in relevant_objectives(scenario)}
    proposed = {step.objective_ref for step in thin.steps}
    expected = [
        titles.get(ref, ref) for ref in scenario.required_objective_refs if ref not in proposed
    ]
    assert warnings[0].message == (
        "The LLM proposal omitted expected objectives: " + ", ".join(expected)
    )
    assert result.warning_count == 1
    assert result.error_count == 0


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
    """The sweep report carries the RAG flag, the engine and the model."""
    from app.evaluation import runner

    scenario = SCENARIOS_BY_ID["anju-kafei"]

    def _fake_run_scenario(item, planner=""):
        """Stand in for the pipeline run, no LLM involved."""
        return ScenarioResult(scenario_id=item.id, passed=True, model="test-model")

    monkeypatch.setattr(runner, "run_scenario", _fake_run_scenario)

    report = runner.run_scenarios([scenario], rag_on=False)

    assert report.rag_on is False
    assert report.planner == "llm"
    assert report.models == "test-model"
    assert [result.scenario_id for result in report.results] == [scenario.id]


def test_the_unreachable_verdict_is_not_reported_as_a_model(store_dir):
    """A sweep must not list "unreachable" among the producing models."""
    from app.evaluation import runner

    result = runner.run_scenario(_late_scenario(), planner="llm")

    assert result.passed, [issue.message for issue in result.issues]
    assert result.model == ""


def test_run_scenarios_records_the_deterministic_engine(monkeypatch):
    """The ablation sweep says so, so two reports stay comparable."""
    from app.evaluation import runner

    scenario = SCENARIOS_BY_ID["anju-kafei"]
    seen: list[str] = []

    def _fake_run_scenario(item, planner=""):
        """Record the engine the sweep passed down."""
        seen.append(planner)
        return ScenarioResult(scenario_id=item.id, passed=True, model="deterministic")

    monkeypatch.setattr(runner, "run_scenario", _fake_run_scenario)

    report = runner.run_scenarios([scenario], rag_on=False, planner="deterministic")

    assert report.planner == "deterministic"
    assert seen == ["deterministic"]


def test_the_deterministic_engine_builds_the_chain_without_an_llm(monkeypatch):
    """The baseline never asks for a model and records its own engine."""
    from app.agents import planning_agent

    scenario = SCENARIOS_BY_ID["anju-kafei"]

    def _no_model(**_kwargs):
        raise AssertionError("the deterministic engine must not ask for a model")

    monkeypatch.setattr(planning_agent, "get_chat_model", _no_model)
    state = PlanningState(
        game_state=scenario.game_state,
        goal=Goal(description=scenario.goal),
        relevant_objectives=relevant_objectives(scenario),
        planner="deterministic",
    )

    result = planning_agent.run(state)

    assert result["plan_engine"] == "deterministic"
    assert result["plan_proposal"] is None
    assert result["plan_model"] == ""
    assert [step.objective_ref for step in result["plan"].steps] == (
        scenario.required_objective_refs
    )


def test_the_default_engine_still_asks_the_llm(monkeypatch):
    """Without an opt-in the product path is untouched."""
    from app.agents import planning_agent

    scenario = SCENARIOS_BY_ID["anju-kafei"]
    called: list[str] = []

    def _model(**_kwargs):
        called.append("asked")
        raise RuntimeError("model requested")

    monkeypatch.setattr(planning_agent, "get_chat_model", _model)
    state = PlanningState(
        game_state=scenario.game_state,
        goal=Goal(description=scenario.goal),
        relevant_objectives=relevant_objectives(scenario),
    )

    with pytest.raises(RuntimeError, match="model requested"):
        planning_agent.run(state)
    assert called == ["asked"]


def test_an_explicit_engine_beats_the_environment(monkeypatch):
    """A run override wins over ``PLANNER``, so a sweep cannot leak sideways."""
    from app.agents import planning_agent

    monkeypatch.setenv("PLANNER", "deterministic")
    scenario = SCENARIOS_BY_ID["anju-kafei"]

    def _model(**_kwargs):
        raise RuntimeError("model requested")

    monkeypatch.setattr(planning_agent, "get_chat_model", _model)
    state = PlanningState(
        game_state=scenario.game_state,
        goal=Goal(description=scenario.goal),
        relevant_objectives=relevant_objectives(scenario),
        planner="llm",
    )

    with pytest.raises(RuntimeError, match="model requested"):
        planning_agent.run(state)


def test_the_environment_engine_applies_without_an_override(monkeypatch):
    """``PLANNER=deterministic`` is enough for the headless and CLI paths."""
    from app.agents import planning_agent

    monkeypatch.setenv("PLANNER", "deterministic")
    scenario = SCENARIOS_BY_ID["anju-kafei"]

    def _no_model(**_kwargs):
        raise AssertionError("the deterministic engine must not ask for a model")

    monkeypatch.setattr(planning_agent, "get_chat_model", _no_model)
    state = PlanningState(
        game_state=scenario.game_state,
        goal=Goal(description=scenario.goal),
        relevant_objectives=relevant_objectives(scenario),
    )

    assert planning_agent.run(state)["plan_engine"] == "deterministic"


def test_the_late_scenario_makes_no_llm_call(monkeypatch):
    """The planner reports the closure itself, before touching a model."""
    from app.agents import planning_agent

    scenario = _late_scenario()

    def _no_model(**_kwargs):
        raise AssertionError("a fully closed chain must not reach the LLM")

    monkeypatch.setattr(planning_agent, "get_chat_model", _no_model)
    state = PlanningState(
        game_state=scenario.game_state,
        goal=Goal(description=scenario.goal),
        relevant_objectives=relevant_objectives(scenario),
        planner="llm",
    )

    result = planning_agent.run(state)

    assert result["plan_engine"] == "unreachable"
    assert result["plan"].steps == []


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
