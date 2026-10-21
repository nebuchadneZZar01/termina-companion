"""Deterministic evaluator for generated plans.

The evaluator never calls an LLM: it takes the plan produced by a run and
checks it against the expectations declared by a scenario. Game knowledge is
read through the MCP tools (:mod:`app.mcp.tools`), the same seam the agents
use, so the evaluation reflects what the Knowledge Agent could have known.

Checks, each producing issues of its own kind:

* ``plan_shape`` — the plan exists, its steps reference known objectives and
  their number is within the expected range.
* ``objective_achievement`` — the expected objectives are in the plan, the
  goal objective comes last and forbidden objectives are absent.
* ``temporal_ordering`` — steps are chronological, never overlap, stay inside
  their objective's slot and never start before the player's current time.
* ``prerequisites`` — every step's items, masks and prerequisite objectives
  are satisfied by the player's state or by an earlier step.
* ``tool_usage`` — the Knowledge Agent consulted the MCP tools the goal needs.
* ``critic`` — the Critic Agent did not reject the plan.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.data.mock_knowledge import Objective
from app.domain import ClockTime, Plan, ValidationResult
from app.evaluation.models import EvaluationIssue, PlanScenario, ScenarioResult
from app.mcp.tools import check_prerequisites, search_quests

logger = logging.getLogger(__name__)

SEARCH_TOOL = "search_quests"
NPC_TOOL = "get_npc_schedule"
EVENT_TOOL = "get_event"


def evaluate_plan(
    plan: Plan | None,
    scenario: PlanScenario,
    tool_calls: Sequence[str] = (),
    validation: ValidationResult | None = None,
) -> ScenarioResult:
    """Check a produced plan against a scenario's expectations.

    args:
        plan (Plan | None): the plan produced by the run, if any.
        scenario (PlanScenario): the expectations to check against.
        tool_calls (Sequence[str], default ()): the MCP tools the Knowledge
            Agent invoked, as ``"tool"`` or ``"tool:<arg>"``.
        validation (ValidationResult | None, default None): the Critic's
            verdict, when the run produced one.

    returns:
        ScenarioResult: the outcome, with one issue per failed expectation.
    """
    issues: list[EvaluationIssue] = []
    objectives = relevant_objectives(scenario)
    by_id = {obj.id: obj for obj in objectives}

    if plan is None or not plan.steps:
        issues.append(
            EvaluationIssue(severity="error", kind="plan_shape", message="No plan was produced.")
        )
        return ScenarioResult(scenario_id=scenario.id, passed=False, issues=issues, step_count=0)

    refs = [step.objective_ref for step in plan.steps]
    _check_shape(plan, scenario, by_id, issues)
    _check_achievement(scenario, refs, by_id, issues)
    _check_temporal(plan, scenario, by_id, issues)
    _check_prerequisites(plan, scenario, by_id, issues)
    _check_tool_usage(objectives, tool_calls, issues)
    _check_critic(validation, issues)

    passed = not any(issue.severity == "error" for issue in issues)
    return ScenarioResult(
        scenario_id=scenario.id,
        passed=passed,
        issues=issues,
        step_count=len(plan.steps),
        objective_refs=refs,
    )


def relevant_objectives(scenario: PlanScenario) -> list[Objective]:
    """Objectives the Knowledge Agent would retrieve for a scenario's goal.

    The lookup mirrors the Knowledge Agent exactly (same MCP tool, same
    progress map), so the evaluation sees the objectives the planner was
    given — never more.

    args:
        scenario (PlanScenario): the scenario whose goal is looked up.

    returns:
        list[Objective]: the matched objectives.
    """
    groups = search_quests(scenario.goal, scenario.game_state.quest_progress)
    objectives: list[Objective] = []
    for group in groups:
        for raw in group.get("objectives", []):
            try:
                objectives.append(Objective.model_validate(raw))
            except Exception as exc:  # noqa: BLE001 - malformed data is skipped
                logger.warning("Evaluation: skipping invalid objective: %s", exc)
    return objectives


def _check_shape(
    plan: Plan,
    scenario: PlanScenario,
    by_id: dict[str, Objective],
    issues: list[EvaluationIssue],
) -> None:
    """Check the plan's shape: step count and objective references.

    args:
        plan (Plan): the produced plan.
        scenario (PlanScenario): the expectations to check against.
        by_id (dict[str, Objective]): known objectives, by id.
        issues (list[EvaluationIssue]): the issue list to append to.

    returns:
        None: appends to ``issues``.
    """
    count = len(plan.steps)
    if count < scenario.min_steps:
        issues.append(
            EvaluationIssue(
                severity="error",
                kind="plan_shape",
                message=f"Expected at least {scenario.min_steps} step(s), got {count}.",
            )
        )
    if scenario.max_steps and count > scenario.max_steps:
        issues.append(
            EvaluationIssue(
                severity="warning",
                kind="plan_shape",
                message=f"Expected at most {scenario.max_steps} step(s), got {count}.",
            )
        )
    for idx, step in enumerate(plan.steps):
        if not step.objective_ref:
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="plan_shape",
                    message=f"Step {idx + 1} has no objective reference.",
                    step_idx=idx,
                )
            )
        elif step.objective_ref not in by_id:
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="plan_shape",
                    message=(
                        f"Step {idx + 1} references {step.objective_ref!r}, "
                        "which is not an objective of this goal."
                    ),
                    step_idx=idx,
                )
            )


def _check_achievement(
    scenario: PlanScenario,
    refs: list[str],
    by_id: dict[str, Objective],
    issues: list[EvaluationIssue],
) -> None:
    """Check that the plan reaches the goal and avoids forbidden objectives.

    args:
        scenario (PlanScenario): the expectations to check against.
        refs (list[str]): the plan's objective references, in order.
        by_id (dict[str, Objective]): known objectives, by id.
        issues (list[EvaluationIssue]): the issue list to append to.

    returns:
        None: appends to ``issues``.
    """
    for ref in scenario.required_objective_refs:
        if ref not in refs:
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="objective_achievement",
                    message=f"The plan does not achieve {ref!r}.",
                )
            )
        elif ref not in by_id:
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="objective_achievement",
                    message=(
                        f"{ref!r} was never retrieved for this goal: the knowledge "
                        "layer did not surface it."
                    ),
                )
            )
    terminal = scenario.terminal_objective_ref
    if terminal and terminal not in refs:
        issues.append(
            EvaluationIssue(
                severity="error",
                kind="objective_achievement",
                message=f"The plan never reaches {terminal!r}.",
            )
        )
    elif terminal and refs[-1] != terminal:
        issues.append(
            EvaluationIssue(
                severity="warning",
                kind="objective_achievement",
                message=f"{terminal!r} is not the final step of the plan.",
            )
        )
    for ref in scenario.forbidden_objective_refs:
        if ref in refs:
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="objective_achievement",
                    message=f"The plan contains the forbidden objective {ref!r}.",
                )
            )
    for before, after in scenario.expected_order:
        if before not in refs or after not in refs:
            continue
        if refs.index(before) > refs.index(after):
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="temporal_ordering",
                    message=f"{before!r} must come before {after!r}.",
                )
            )


def _check_temporal(
    plan: Plan,
    scenario: PlanScenario,
    by_id: dict[str, Objective],
    issues: list[EvaluationIssue],
) -> None:
    """Check the plan's timing: order, overlap, slot and current time.

    args:
        plan (Plan): the produced plan.
        scenario (PlanScenario): the expectations to check against.
        by_id (dict[str, Objective]): known objectives, by id.
        issues (list[EvaluationIssue]): the issue list to append to.

    returns:
        None: appends to ``issues``.
    """
    now = scenario.game_state.time
    for idx, step in enumerate(plan.steps):
        if _clock(step.window.start) < _clock(now):
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="temporal_ordering",
                    message=f"Step {idx + 1} starts before the player's current time.",
                    step_idx=idx,
                )
            )
        objective = by_id.get(step.objective_ref)
        if objective is not None and not (
            objective.window.contains(step.window.start)
            and _clock(step.window.end) <= _clock(objective.window.end)
        ):
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="temporal_ordering",
                    message=(
                        f"Step {idx + 1} window {step.window} falls outside the "
                        f"objective's slot {objective.window}."
                    ),
                    step_idx=idx,
                )
            )
        if idx and _clock(step.window.start) < _clock(plan.steps[idx - 1].window.end):
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="temporal_ordering",
                    message=f"Step {idx + 1} overlaps the previous step.",
                    step_idx=idx,
                )
            )


def _check_prerequisites(
    plan: Plan,
    scenario: PlanScenario,
    by_id: dict[str, Objective],
    issues: list[EvaluationIssue],
) -> None:
    """Check that every step's requirements are satisfied when it happens.

    Items and masks provided by earlier steps count as owned, exactly like the
    Critic does, so a chain that hands over the letter or a mask passes.

    args:
        plan (Plan): the produced plan.
        scenario (PlanScenario): the expectations to check against.
        by_id (dict[str, Objective]): known objectives, by id.
        issues (list[EvaluationIssue]): the issue list to append to.

    returns:
        None: appends to ``issues``.
    """
    inventory = set(scenario.game_state.inventory)
    masks = set(scenario.game_state.masks)
    provided_items: set[str] = set()
    provided_masks: set[str] = set()

    for idx, step in enumerate(plan.steps):
        objective = by_id.get(step.objective_ref)
        if objective is None:
            continue
        try:
            met = check_prerequisites(
                objective.id,
                inventory=sorted(inventory | provided_items),
                masks=sorted(masks | provided_masks),
                quest_progress=scenario.game_state.quest_progress,
            )
        except ValueError as exc:
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="prerequisites",
                    message=f"Step {idx + 1} could not be checked: {exc}",
                    step_idx=idx,
                )
            )
            continue
        if met["missing_items"]:
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="prerequisites",
                    message=(
                        f"Step {idx + 1} is missing item(s): {', '.join(met['missing_items'])}."
                    ),
                    step_idx=idx,
                )
            )
        if met["missing_masks"]:
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="prerequisites",
                    message=(
                        f"Step {idx + 1} is missing mask(s): {', '.join(met['missing_masks'])}."
                    ),
                    step_idx=idx,
                )
            )
        unmet = [
            prereq
            for prereq in met["unmet_prerequisites"]
            if not _prereq_satisfied(prereq, plan, idx, by_id, inventory, masks)
        ]
        if unmet:
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="prerequisites",
                    message=f"Step {idx + 1} has unmet prerequisite(s): {', '.join(unmet)}.",
                    step_idx=idx,
                )
            )
        provided_items.update(objective.provides_items)
        provided_masks.update(objective.provides_masks)


def _prereq_satisfied(
    prereq: str,
    plan: Plan,
    idx: int,
    by_id: dict[str, Objective],
    inventory: set[str],
    masks: set[str],
) -> bool:
    """Whether a prerequisite objective is satisfied before a given step.

    A prerequisite counts as satisfied when an earlier step of the plan
    performs it, or when the player already owns what it provides (the
    letter, the mask).

    args:
        prereq (str): the prerequisite objective id.
        plan (Plan): the whole plan, for earlier-step checks.
        idx (int): the index of the step that needs the prerequisite.
        by_id (dict[str, Objective]): known objectives, by id.
        inventory (set[str]): the player's items.
        masks (set[str]): the player's masks.

    returns:
        bool: True when the prerequisite is satisfied.
    """
    if any(step.objective_ref == prereq for step in plan.steps[:idx]):
        return True
    objective = by_id.get(prereq)
    if objective is None:
        return False
    return (
        bool(objective.provides_items or objective.provides_masks)
        and set(objective.provides_items) <= inventory
        and set(objective.provides_masks) <= masks
    )


def _check_tool_usage(
    objectives: list[Objective],
    tool_calls: Sequence[str],
    issues: list[EvaluationIssue],
) -> None:
    """Check that the Knowledge Agent consulted the tools the goal needs.

    args:
        objectives (list[Objective]): the retrieved objectives.
        tool_calls (Sequence[str]): the MCP tools the Knowledge Agent invoked.
        issues (list[EvaluationIssue]): the issue list to append to.

    returns:
        None: appends to ``issues``.
    """
    called = set(tool_calls)
    if SEARCH_TOOL not in called:
        issues.append(
            EvaluationIssue(
                severity="error",
                kind="tool_usage",
                message="The Knowledge Agent never searched the quest index.",
            )
        )
    for objective in objectives:
        if objective.npc_id and f"{NPC_TOOL}:{objective.npc_id}" not in called:
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="tool_usage",
                    message=f"No schedule was retrieved for {objective.npc_id!r}.",
                )
            )
        if objective.event_ref and f"{EVENT_TOOL}:{objective.event_ref}" not in called:
            issues.append(
                EvaluationIssue(
                    severity="error",
                    kind="tool_usage",
                    message=f"No event was retrieved for {objective.event_ref!r}.",
                )
            )


def _check_critic(validation: ValidationResult | None, issues: list[EvaluationIssue]) -> None:
    """Check that the Critic did not reject the plan.

    args:
        validation (ValidationResult | None): the Critic's verdict.
        issues (list[EvaluationIssue]): the issue list to append to.

    returns:
        None: appends to ``issues``.
    """
    if validation is None or validation.valid:
        return
    errors = [issue for issue in validation.issues if issue.severity == "error"]
    if not errors:
        issues.append(
            EvaluationIssue(
                severity="error",
                kind="critic",
                message="The Critic rejected the plan.",
            )
        )
        return
    for issue in errors:
        issues.append(
            EvaluationIssue(
                severity="error",
                kind="critic",
                message=f"The Critic rejected the plan: {issue.message}",
                step_idx=issue.step_idx,
            )
        )


def _clock(t: ClockTime) -> tuple[int, int, int]:
    """Collapse a clock into a sortable (day, hour, minute) tuple.

    args:
        t (ClockTime): the time to convert.

    returns:
        tuple: (day, hour, minute).
    """
    return (t.day, t.hour, t.minute)
