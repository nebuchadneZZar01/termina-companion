"""Deterministic clock matrix: planner and Critic agree on what the cycle closed.

No LLM is involved: the authoritative chain rebuild runs on an empty plan and the
Critic then validates the result. These tests pin the temporal behaviour over the
whole three-day cycle — what the plan may contain, what the verdict says, and the
fact that the two sides never disagree — without paying for a model call.
"""

from __future__ import annotations

import pytest

from app.agents.critic_agent import validate_plan
from app.agents.planning_chain import _OBJECTIVE_POSITION, _reconcile_plan, dead_for
from app.agents.progress import done_objective_ids
from app.agents.scheduling import schedule_chain, select_chain
from app.data.mock_knowledge import Objective, build_default_knowledge
from app.domain import ClockTime, GameState, Goal, Plan
from app.mcp.tools import search_quests
from app.state import PlanningState

_KB = build_default_knowledge()

# The six clocks the plan pins: dawn, late night, both mid-days, the last
# afternoon and the last half hour of the cycle.
CLOCKS = [
    ClockTime(day=1, hour=6),
    ClockTime(day=1, hour=22),
    ClockTime(day=2, hour=8),
    ClockTime(day=2, hour=23),
    ClockTime(day=3, hour=12),
    ClockTime(day=3, hour=29, minute=30),
]

GOALS = {
    "anju": "Reunite Anju and Kafei",
    "pamela": "free Pamela's father",
    "darmani": "learn the Goron Lullaby from Darmani",
    "romani": "Romani Ranch defend the ranch",
}


def _objectives(text: str) -> list[Objective]:
    """The objectives the Knowledge Agent would retrieve for a goal."""
    return [
        Objective.model_validate(item)
        for group in search_quests(text)
        for item in group["objectives"]
    ]


def _schedule(state: PlanningState, dead: dict[str, str]):
    """The chain and its placement, computed the way the agents compute it."""
    game_state = state.game_state
    chain = select_chain(
        state.relevant_objectives,
        owned_items=set(game_state.inventory),
        owned_masks=set(game_state.masks),
        done_ids=done_objective_ids(
            _KB.quests, game_state.completed_objectives, game_state.quest_progress
        ),
        dead=dead,
        positions=_OBJECTIVE_POSITION,
    )
    return schedule_chain(chain, game_state.time)


def _state(now: ClockTime, goal: str) -> PlanningState:
    """A planning state at a given clock for a goal key of :data:`GOALS`."""
    game_state = GameState(
        time=now,
        location="Stockpot Inn",
        inventory=["Hookshot", "Lens of Truth"],
        masks=["Garo's Mask"],
    )
    return PlanningState(
        game_state=game_state,
        goal=Goal(description=GOALS[goal]),
        relevant_objectives=_objectives(GOALS[goal]),
    )


CASES = [(goal, now) for goal in GOALS for now in CLOCKS]


@pytest.mark.parametrize(("goal", "now"), CASES, ids=[f"{g}-{n}" for g, n in CASES])
def test_no_step_is_scheduled_before_the_players_clock(goal, now):
    """Every step starts at or after now, over the whole cycle."""
    state = _state(now, goal)
    plan = _reconcile_plan(Plan(goal=state.goal.description), state)
    for step in plan.steps:
        assert (step.window.start.day, step.window.start.hour, step.window.start.minute) >= (
            now.day,
            now.hour,
            now.minute,
        ), step


@pytest.mark.parametrize(("goal", "now"), CASES, ids=[f"{g}-{n}" for g, n in CASES])
def test_steps_stay_inside_an_open_occurrence(goal, now):
    """Each step lies inside an availability occurrence still open at now."""
    from app.agents.planning_clock import occurrences

    state = _state(now, goal)
    by_id = {obj.id: obj for obj in state.relevant_objectives}
    plan = _reconcile_plan(Plan(goal=state.goal.description), state)
    for step in plan.steps:
        objective = by_id[step.objective_ref]
        open_windows = occurrences(objective, now)
        assert any(
            (window.start.day, window.start.hour, window.start.minute)
            <= (step.window.start.day, step.window.start.hour, step.window.start.minute)
            and (step.window.end.day, step.window.end.hour, step.window.end.minute)
            <= (window.end.day, window.end.hour, window.end.minute)
            for window in open_windows
        ), (objective.id, step.window)


@pytest.mark.parametrize(("goal", "now"), CASES, ids=[f"{g}-{n}" for g, n in CASES])
def test_the_plan_is_chronological_and_does_not_overlap(goal, now):
    """The rebuilt plan is ordered, with no step starting before the previous ends."""
    state = _state(now, goal)
    plan = _reconcile_plan(Plan(goal=state.goal.description), state)
    for previous, step in zip(plan.steps, plan.steps[1:]):
        assert (step.window.start.day, step.window.start.hour, step.window.start.minute) >= (
            previous.window.end.day,
            previous.window.end.hour,
            previous.window.end.minute,
        ), (previous.objective_ref, step.objective_ref)


@pytest.mark.parametrize(("goal", "now"), CASES, ids=[f"{g}-{n}" for g, n in CASES])
def test_planner_and_critic_agree_on_what_is_closed(goal, now):
    """The Critic reports unreachable exactly when the clock closed a chain."""
    state = _state(now, goal)
    dead = dead_for(state)
    schedule = _schedule(state, dead)
    plan = _reconcile_plan(Plan(goal=state.goal.description), state)
    result = validate_plan(plan, state.game_state, state.relevant_objectives, _KB.npcs)
    unreachable = [issue for issue in result.issues if issue.kind == "unreachable"]
    assert bool(unreachable) == bool(dead or schedule.dropped), (dead, result.issues)
    for issue in unreachable:
        assert "Song of Time" in issue.message


@pytest.mark.parametrize(("goal", "now"), CASES, ids=[f"{g}-{n}" for g, n in CASES])
def test_the_plan_holds_exactly_what_fits(goal, now):
    """The plan is the schedule: nothing reachable dropped, nothing closed added."""
    state = _state(now, goal)
    dead = dead_for(state)
    schedule = _schedule(state, dead)
    plan = _reconcile_plan(Plan(goal=state.goal.description), state)
    planned = {step.objective_ref for step in plan.steps}
    assert planned == schedule.placed_ids, (planned, schedule.placed_ids, schedule.dropped_ids)
    assert not planned & set(dead)
    result = validate_plan(plan, state.game_state, state.relevant_objectives, _KB.npcs)
    missing = [issue for issue in result.issues if issue.kind == "missing_step"]
    assert missing == []


@pytest.mark.parametrize(("goal", "now"), CASES, ids=[f"{g}-{n}" for g, n in CASES])
def test_an_empty_plan_is_never_reported_as_generically_empty(goal, now):
    """With objectives retrieved, an empty plan is a temporal verdict."""
    state = _state(now, goal)
    plan = _reconcile_plan(Plan(goal=state.goal.description), state)
    if not plan.steps:
        result = validate_plan(plan, state.game_state, state.relevant_objectives, _KB.npcs)
        kinds = {issue.kind for issue in result.issues}
        assert "empty" not in kinds
        assert "unreachable" in kinds


def test_the_matrix_covers_both_reachable_and_closed_days():
    """Guard against a vacuous matrix: both verdicts must appear."""
    reachable = [now for now in CLOCKS if not dead_for(_state(now, "anju"))]
    closed = [now for now in CLOCKS if dead_for(_state(now, "anju"))]
    assert reachable == [CLOCKS[0]]
    assert closed == CLOCKS[1:]


def test_a_fully_reachable_chain_is_planned_completely():
    """On the first dawn every shipped objective of the goal is planned."""
    state = _state(CLOCKS[0], "anju")
    plan = _reconcile_plan(Plan(goal=state.goal.description), state)
    assert {step.objective_ref for step in plan.steps} == {
        obj.id for obj in state.relevant_objectives
    }


def test_a_recurring_chain_is_still_plannable_on_the_last_day():
    """Daily availability survives even with only hours left in the cycle."""
    state = _state(ClockTime(day=3, hour=12), "pamela")
    plan = _reconcile_plan(Plan(goal=state.goal.description), state)
    assert [step.objective_ref for step in plan.steps] == [
        "pf_find_pamela",
        "pf_restore_river",
        "pf_enter_house",
        "pf_free_father",
        "pf_reunite_pamela",
    ]
    assert {step.window.start.day for step in plan.steps} == {3}
    result = validate_plan(plan, state.game_state, state.relevant_objectives, _KB.npcs)
    assert "unreachable" not in {issue.kind for issue in result.issues}


def test_a_chain_that_overruns_the_cycle_is_reported_not_shortened():
    """Six one-hour steps do not fit in the last two hours of Day 3."""
    state = _state(ClockTime(day=3, hour=22), "darmani")
    dead = dead_for(state)
    schedule = _schedule(state, dead)
    assert schedule.placed_ids and schedule.dropped_ids
    plan = _reconcile_plan(Plan(goal=state.goal.description), state)
    assert {step.objective_ref for step in plan.steps} == schedule.placed_ids
    result = validate_plan(plan, state.game_state, state.relevant_objectives, _KB.npcs)
    assert not result.valid
    unreachable = [issue for issue in result.issues if issue.kind == "unreachable"]
    assert len(unreachable) == len(schedule.dropped_ids)
    for issue in unreachable:
        assert "it no longer fits before" in issue.message
        assert "Song of Time" in issue.message
    assert "empty" not in {issue.kind for issue in result.issues}
    assert "missing_step" not in {issue.kind for issue in result.issues}


def test_a_one_off_chain_is_gone_by_the_second_day():
    """The Anju & Kafei chain is dated: midnight of Day 1 closes it."""
    state = _state(ClockTime(day=2, hour=8), "anju")
    plan = _reconcile_plan(Plan(goal=state.goal.description), state)
    assert plan.steps == []
    result = validate_plan(plan, state.game_state, state.relevant_objectives, _KB.npcs)
    assert {issue.kind for issue in result.issues} == {"unreachable"}
