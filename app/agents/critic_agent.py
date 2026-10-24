"""Critic/Validator Agent: checks whether the plan is feasible.

Runs deterministic feasibility rules against the player's state and the
knowledge base. This is the important domain logic kept dependency-free so it
can be unit-tested directly.
"""

from __future__ import annotations

import logging

from app.data.mock_knowledge import NPC, Objective, Quest, build_default_knowledge
from app.domain import (
    ClockTime,
    GameState,
    Plan,
    PlanStep,
    ValidationIssue,
    ValidationResult,
)
from app.state import AttemptRecord, PlanningState
from app.trace import set_output
from app.trace import span as traced_span

logger = logging.getLogger(__name__)


def _build_quest_maps(quests: list[Quest]) -> tuple[dict[str, Quest], dict[str, str]]:
    quest_by_id = {q.id: q for q in quests}
    quest_terminal = {q.id: q.objectives[-1].id for q in quests if q.objectives}
    return quest_by_id, quest_terminal


_KB = build_default_knowledge()
_QUEST_BY_ID, _QUEST_TERMINAL = _build_quest_maps(_KB.quests)
_OBJ_BY_ID = {obj.id: obj for q in _KB.quests for obj in q.objectives}


def _quest_is_satisfied(required_quest_id: str, game_state: GameState, plan: Plan) -> bool:
    if game_state.quest_progress.get(required_quest_id) == "done":
        return True
    terminal = _QUEST_TERMINAL.get(required_quest_id)
    if terminal:
        for step in plan.steps:
            if step.objective_ref == terminal:
                return True
        # Owning the quest's reward is proof enough that its terminal step
        # already happened (the planner prunes it as an owned provide).
        terminal_obj = _OBJ_BY_ID.get(terminal)
        if terminal_obj is not None and _provides_owned(terminal_obj, game_state):
            return True
    return False


def _quest_prerequisite_closure(
    required_quest_id: str,
    game_state: GameState,
    plan: Plan,
    visited: set[str] | None = None,
) -> list[str]:
    if visited is None:
        visited = set()
    if required_quest_id in visited:
        return []
    visited.add(required_quest_id)

    if _quest_is_satisfied(required_quest_id, game_state, plan):
        return []

    missing: list[str] = []
    q = _QUEST_BY_ID.get(required_quest_id)
    if not q:
        # still missing, but we don't know its deps
        missing.append(required_quest_id)
    else:
        reqs: set[str] = set()
        for obj in q.objectives:
            for r in getattr(obj, "requires_quests", []) or []:
                reqs.add(r)
        for r in sorted(reqs):
            missing.extend(_quest_prerequisite_closure(r, game_state, plan, visited))
        # add this quest if still missing
        if not _quest_is_satisfied(required_quest_id, game_state, plan):
            missing.append(required_quest_id)

    # deduplicate preserving order
    seen = set()
    out = []
    for m in missing:
        if m in seen:
            continue
        seen.add(m)
        out.append(m)
    return out


def validate_plan(
    plan: Plan | None,
    game_state: GameState,
    objectives: list[Objective],
    npcs: list[NPC] | None = None,
) -> ValidationResult:
    """Check a plan's feasibility against the player's state and knowledge.

    Runs deterministic rules per step: empty plan, unknown objective,
    location, time window, NPC availability, missing items and masks (items
    and masks provided by earlier plan steps are credited), and sequence
    ordering.

    args:
        plan (Plan | None): the plan to validate.
        game_state (GameState): the player's inventory, masks and progress.
        objectives (list[Objective]): knowledge objectives to ground refs.
        npcs (list[NPC] | None, default None): NPCs to check availability.

    returns:
        ValidationResult: valid, plus the list of issues found.
    """
    if not plan or not plan.steps:
        return ValidationResult(
            valid=False,
            issues=[ValidationIssue(severity="error", kind="empty", message="Plan has no steps.")],
        )

    issues: list[ValidationIssue] = []
    by_id = {o.id: o for o in objectives}
    npc_by_id = {n.id: n for n in npcs or []}
    for idx, step in enumerate(plan.steps):
        issues.extend(_check_step(step, idx, plan, game_state, by_id, npc_by_id))
    return ValidationResult(valid=not issues, issues=issues)


def _quest_display_name(quest_id: str) -> str:
    q = _QUEST_BY_ID.get(quest_id)
    if q:
        return q.name
    return quest_id


def _check_step(
    step: PlanStep,
    idx: int,
    plan: Plan,
    game_state: GameState,
    by_id: dict[str, Objective],
    npc_by_id: dict[str, NPC],
) -> list[ValidationIssue]:
    """Validate a single plan step against all feasibility rules.

    args:
        step (PlanStep): the step under check.
        idx (int): the step index in the plan.
        plan (Plan): the whole plan, for sequence/dependency checks.
        game_state (GameState): the player's inventory and masks.
        by_id (dict[str, Objective]): objective id → objective lookup.
        npc_by_id (dict[str, NPC]): NPC id → NPC lookup.

    returns:
        list[ValidationIssue]: all issues found for this step.
    """
    issues: list[ValidationIssue] = []
    objective = by_id.get(step.objective_ref)

    if objective is None:
        if step.objective_ref:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    step_idx=idx,
                    kind="objective",
                    message="Unknown objective reference.",
                )
            )
        return issues

    if objective.location != step.location:
        issues.append(
            _issue("location", idx, f"{step.location!r} is not where {step.objective_ref} happens.")
        )

    if not objective.window.contains(step.window.start) or not _lte(
        step.window.end, objective.window.end
    ):
        issues.append(
            _issue(
                "time",
                idx,
                f"Window {step.window} falls outside the objective's slot {objective.window}.",
            )
        )

    if objective.npc_id:
        npc = npc_by_id.get(objective.npc_id)
        if npc and not any(
            _lte(w.start, step.window.start) and _lte(step.window.end, w.end) for w in npc.schedule
        ):
            issues.append(_issue("npc", idx, f"{npc.name} is unavailable during {step.window}."))

    provided_items, provided_masks = _provided_upstream(idx, plan, by_id)
    missing_items = [
        item
        for item in step.requires_items
        if item not in game_state.inventory and item not in provided_items
    ]
    if missing_items:
        issues.append(_issue("item", idx, f"Missing item(s): {', '.join(missing_items)}."))

    missing_masks = [
        mask
        for mask in step.requires_masks
        if mask not in game_state.masks and mask not in provided_masks
    ]
    if missing_masks:
        issues.append(_issue("mask", idx, f"Missing mask(s): {', '.join(missing_masks)}."))

    missing_prereqs = _missing_prerequisites(idx, objective, plan, game_state, by_id)
    if missing_prereqs:
        issues.append(
            _issue("prerequisite", idx, f"Missing prerequisite(s): {', '.join(missing_prereqs)}.")
        )

    # Quest prerequisites
    quest_reqs = getattr(objective, "requires_quests", []) or []
    for qreq in quest_reqs:
        missing_chain = _quest_prerequisite_closure(qreq, game_state, plan)
        if missing_chain:
            # build message with transitive info
            if len(missing_chain) == 1 and missing_chain[0] == qreq:
                msg = (
                    f"Quest prerequisite missing: {_quest_display_name(qreq)}. "
                    "Complete this quest first."
                )
            else:
                # ancestors first, then the required quest
                parts = []
                for mq in missing_chain:
                    parts.append(_quest_display_name(mq))
                msg = (
                    f"Quest prerequisite missing: {', '.join(parts)}. Complete these quests first."
                )
            issues.append(
                ValidationIssue(
                    severity="error", step_idx=idx, kind="quest_prerequisite", message=msg
                )
            )

    for earlier in step.depends_on:
        if earlier >= idx:
            continue
        if _lt(step.window.start, plan.steps[earlier].window.end):
            issues.append(
                _issue("sequence", idx, "Depends on a step that ends after this one starts.")
            )
    return issues


def _provided_upstream(
    idx: int, plan: Plan, by_id: dict[str, Objective]
) -> tuple[set[str], set[str]]:
    """Items and masks that earlier plan steps hand the player.

    A step that retrieves an item or a mask (an objective with
    ``provides_items`` / ``provides_masks``) makes that reward available to
    every later step, so a later requirement on it is satisfied even when the
    player does not yet own it at the start of the plan.

    args:
        idx (int): the step index whose upstream rewards are collected.
        plan (Plan): the whole plan, for earlier steps.
        by_id (dict[str, Objective]): objective id to objective lookup.

    returns:
        tuple[set[str], set[str]]: the provided items and masks, as sets.
    """
    items: set[str] = set()
    masks: set[str] = set()
    for prior in plan.steps[:idx]:
        obj = by_id.get(prior.objective_ref)
        if obj is not None:
            items.update(obj.provides_items)
            masks.update(obj.provides_masks)
    return items, masks


def _missing_prerequisites(
    idx: int,
    objective: Objective,
    plan: Plan,
    game_state: GameState,
    by_id: dict[str, Objective],
) -> list[str]:
    """Prerequisites of a step absent from the plan and not already satisfied.

    A prerequisite counts as satisfied when it appears earlier in the plan,
    its quest is marked done, or the player already owns everything the
    prerequisite objective provides (e.g. Kafei's letter is already in the
    inventory, so "retrieve the letter" may be skipped).

    args:
        idx (int): the step's index in the plan.
        objective (Objective): the step's knowledge objective.
        plan (Plan): the whole plan, for presence checks.
        game_state (GameState): the player's inventory, masks and progress.
        by_id (dict[str, Objective]): objective id → objective lookup for the
        retrieved set.

    returns:
        list[str]: the ids of any unfulfilled prerequisites.
    """
    present = {s.objective_ref for s in plan.steps[:idx]}
    done = {qid for qid, status in (game_state.quest_progress or {}).items() if status == "done"}
    missing = []
    for prereq in objective.prerequisites:
        if prereq in present:
            continue
        if any(
            quest.id in done and any(o.id == prereq for o in quest.objectives)
            for quest in _KB.quests
        ):
            continue
        prereq_obj = by_id.get(prereq) or next(
            (o for q in _KB.quests for o in q.objectives if o.id == prereq), None
        )
        if prereq_obj and _provides_owned(prereq_obj, game_state):
            continue
        missing.append(prereq)
    return missing


def _provides_owned(obj: Objective, game_state: GameState) -> bool:
    """Whether the player already owns everything the objective provides."""
    items = set(obj.provides_items)
    masks = set(obj.provides_masks)
    return (
        (items or masks) and items <= set(game_state.inventory) and masks <= set(game_state.masks)
    )


def _lt(a: ClockTime, b: ClockTime) -> bool:
    """Strictly-less comparison of two clocks over the three-day cycle.

    args:
        a (ClockTime): first time.
        b (ClockTime): second time.

    returns:
        bool: True when ``a`` is strictly before ``b``.
    """
    return (a.day, a.hour, a.minute) < (b.day, b.hour, b.minute)


def _lte(a: ClockTime, b: ClockTime) -> bool:
    """Less-or-equal comparison of two clocks over the three-day cycle.

    args:
        a (ClockTime): first time.
        b (ClockTime): second time.

    returns:
        bool: True when ``a`` is before or equal to ``b``.
    """
    return (a.day, a.hour, a.minute) <= (b.day, b.hour, b.minute)


def _issue(kind: str, step_idx: int, message: str) -> ValidationIssue:
    """Build an error-severity validation issue.

    args:
        kind (str): the issue kind, e.g. "time" or "item".
        step_idx (int): the step the issue refers to.
        message (str): human-readable description.

    returns:
        ValidationIssue: an error-level issue for the given step.
    """
    return ValidationIssue(severity="error", step_idx=step_idx, kind=kind, message=message)


def run(state: PlanningState) -> dict:
    """LangGraph node: validate the current plan with rule-based checks.

    args:
        state (PlanningState): the workflow state with the produced plan.

    returns:
        dict: the ``validation`` result, ``critic_engine`` and the appended
        ``attempt_log`` record for this attempt.
    """
    npcs = _KB.npcs
    plan_input = f"{len(state.plan.steps)} step(s)" if state.plan else "no plan"
    with traced_span("validation", kind="CHAIN", input_value=plan_input) as validation_span:
        result = validate_plan(state.plan, state.game_state, state.relevant_objectives, npcs)
        validation_span.set_attribute("termina.validation.valid", result.valid)
        validation_span.set_attribute("termina.validation.issues", len(result.issues))
        set_output(
            validation_span,
            {
                "valid": result.valid,
                "issues": [
                    f"[{issue.severity}/{issue.kind}] {issue.message}" for issue in result.issues
                ],
            },
        )
    _log_result(result)
    return {
        "validation": result,
        "critic_engine": "rule-based",
        "attempt_log": [*state.attempt_log, _attempt_record(state, result)],
    }


def _attempt_record(state: PlanningState, validation: ValidationResult) -> AttemptRecord:
    """Summarise the attempt the Critic has just validated.

    args:
        state (PlanningState): the workflow state with the produced plan and
            the attempt log, whose length numbers this attempt.
        validation (ValidationResult): the verdict just reached.

    returns:
        AttemptRecord: one trajectory record, appended to the attempt log.
    """
    plan = state.plan
    return AttemptRecord(
        attempt=len(state.attempt_log) + 1,
        step_count=len(plan.steps) if plan else 0,
        objective_refs=[step.objective_ref for step in plan.steps] if plan else [],
        valid=validation.valid,
        issue_kinds=sorted({i.kind for i in validation.issues if i.severity == "error"}),
    )


def _log_result(result: ValidationResult) -> None:
    if result.valid:
        logger.info("Critic [rules]: VALID")
        return
    logger.info("Critic [rules]: INVALID — %d issue(s)", len(result.issues))
    for issue in result.issues:
        step = f"step {issue.step_idx + 1}" if issue.step_idx is not None else "plan"
        logger.info("  - [%s/%s] %s: %s", issue.severity, issue.kind, step, issue.message)


_KB = build_default_knowledge()
