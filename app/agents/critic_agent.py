"""Critic/Validator Agent: checks whether the plan is feasible.

Runs deterministic feasibility rules against the player's state and the
authoritative game knowledge. The Critic never trusts the plan step fields the
planner produced: requirements, dependencies and temporal ordering are
recomputed from the knowledge objectives, resolved through the MCP tools. This
keeps the validator reliable even when the planner's grounding introduced an
inconsistency.
"""

from __future__ import annotations

import logging

from app.agents.critic_knowledge import KnowledgeView
from app.agents.planning_clock import occurrences
from app.agents.reachability import dead_objectives, dead_quests
from app.data.mock_knowledge import NPC, Objective
from app.domain import (
    ClockTime,
    GameState,
    Plan,
    PlanStep,
    ValidationIssue,
    ValidationResult,
    clock_key,
)
from app.state import AttemptRecord, PlanningState
from app.trace import set_output
from app.trace import span as traced_span

logger = logging.getLogger(__name__)


def _quest_is_satisfied(
    required_quest_id: str,
    game_state: GameState,
    plan: Plan,
    view: KnowledgeView,
    done_ids: set[str] | None = None,
) -> bool:
    if game_state.quest_progress.get(required_quest_id) == "done":
        return True
    quest = view.quest(required_quest_id)
    if quest is None or not quest.objectives:
        return False
    every = done_ids or set(game_state.completed_objectives)
    if all(obj.id in every for obj in quest.objectives):
        # The player declared every objective of the quest as completed.
        return True
    terminal = quest.objectives[-1]
    if any(step.objective_ref == terminal.id for step in plan.steps):
        return True
    # Owning the quest's reward is proof enough that its terminal step
    # already happened (the planner prunes it as an owned provide).
    return _provides_owned(terminal, game_state)


def _quest_prerequisite_closure(
    required_quest_id: str,
    game_state: GameState,
    plan: Plan,
    view: KnowledgeView,
    visited: set[str] | None = None,
    done_ids: set[str] | None = None,
) -> list[str]:
    if visited is None:
        visited = set()
    if required_quest_id in visited:
        return []
    visited.add(required_quest_id)

    if _quest_is_satisfied(required_quest_id, game_state, plan, view, done_ids):
        return []

    missing: list[str] = []
    quest = view.quest(required_quest_id)
    if quest is None:
        # still missing, but we don't know its deps
        missing.append(required_quest_id)
    else:
        reqs: set[str] = set()
        for obj in quest.objectives:
            reqs.update(obj.requires_quests)
        for r in sorted(reqs):
            missing.extend(
                _quest_prerequisite_closure(r, game_state, plan, view, visited, done_ids)
            )
        # add this quest if still missing
        if not _quest_is_satisfied(required_quest_id, game_state, plan, view, done_ids):
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
    and masks provided by earlier plan steps are credited), prerequisite
    objectives and quests, and sequence ordering. Requirements and dependency
    timing come from the authoritative Objective, never from the plan step
    fields; every reference is resolved against the whole knowledge base
    through the MCP tools. Consecutive steps must not overlap.

    A step whose window has closed, or that starts before the player's clock,
    is an ``unreachable`` error: only the Song of Time reopens it. One
    ``unreachable`` issue per dead chain names the quest, the objective that was
    missed and the window end, even when the plan shows the steps that are still
    feasible. An empty plan is only ``empty`` when nothing is out of reach;
    otherwise it is reported as the temporal failure it is.

    args:
        plan (Plan | None): the plan to validate.
        game_state (GameState): the player's inventory, masks and progress.
        objectives (list[Objective]): objectives supplied by the caller; they
            take precedence over the knowledge base (tests inject synthetic
            ones).
        npcs (list[NPC] | None, default None): NPC overrides, same precedence.

    returns:
        ValidationResult: valid, plus the list of issues found.
    """
    view = KnowledgeView(objectives, npcs)
    done_ids = _done_ids(game_state, view)
    reachability = {
        "owned_items": set(game_state.inventory),
        "owned_masks": set(game_state.masks),
        "done_quests": {
            quest_id
            for quest_id, status in (game_state.quest_progress or {}).items()
            if status == "done"
        },
        "done_objectives": done_ids,
        "load_quest": view.quest,
    }
    dead = dead_objectives(objectives, game_state.time, **reachability)
    dead_gates = dead_quests(objectives, game_state.time, **reachability)
    roots = sorted(set(dead.values()))

    if not plan or not plan.steps:
        issues = [_root_issue(root, view) for root in roots]
        if not issues:
            issues = [ValidationIssue(severity="error", kind="empty", message="Plan has no steps.")]
        return ValidationResult(valid=False, issues=issues)

    issues: list[ValidationIssue] = []
    for idx, step in enumerate(plan.steps):
        issues.extend(_check_step(step, idx, plan, game_state, view, done_ids, dead_gates))
    issues.extend(_check_overlaps(plan))
    # One issue per dead chain, unless a step of that chain already reported it.
    covered = {dead[step.objective_ref] for step in plan.steps if step.objective_ref in dead}
    issues.extend(_root_issue(root, view) for root in roots if root not in covered)
    return ValidationResult(valid=not issues, issues=issues)


def _root_issue(root: str, view: KnowledgeView) -> ValidationIssue:
    """One ``unreachable`` issue for the root of a dead chain.

    The message names the quest, the objective the player missed and the end of
    its window, so the verdict says what to undo with the Song of Time instead
    of only stating that the plan cannot work.

    args:
        root (str): the root objective id from the reachability closure.
        view (KnowledgeView): authoritative objective and quest lookups.

    returns:
        ValidationIssue: a plan-level error (``step_idx`` None).
    """
    objective = view.objective(root)
    if objective is None:
        return ValidationIssue(
            severity="error",
            kind="unreachable",
            message=f"{root} is out of reach. Use the Song of Time to restart the cycle.",
        )
    quest = view.quest_for_objective(root)
    label = f"{quest.name}: {objective.title}" if quest else objective.title
    return ValidationIssue(
        severity="error",
        kind="unreachable",
        message=(
            f"{label}: its window ended at {objective.window.end}. "
            "Use the Song of Time to restart the cycle."
        ),
    )


def _done_ids(game_state: GameState, view: KnowledgeView) -> set[str]:
    """Objective ids already completed, with ``done`` quests expanded.

    The player state is the source of truth. A quest marked ``done`` counts as
    every one of its objectives being completed; its objectives come from the
    knowledge view, never from the plan.

    args:
        game_state (GameState): the player's inventory, masks and progress.
        view (KnowledgeView): authoritative quest lookups.

    returns:
        set[str]: every objective id that is already done.
    """
    done = set(game_state.completed_objectives)
    for quest_id, status in (game_state.quest_progress or {}).items():
        if status != "done":
            continue
        quest = view.quest(quest_id)
        if quest is not None:
            done.update(obj.id for obj in quest.objectives)
    return done


def _quest_display_name(quest_id: str, view: KnowledgeView) -> str:
    quest = view.quest(quest_id)
    if quest:
        return quest.name
    return quest_id


def _check_step(
    step: PlanStep,
    idx: int,
    plan: Plan,
    game_state: GameState,
    view: KnowledgeView,
    done_ids: set[str] | None = None,
    dead_gates: set[str] | None = None,
) -> list[ValidationIssue]:
    """Validate a single plan step against all feasibility rules.

    Every authoritative value is read from the resolved Objective, so a
    corrupted plan step cannot hide an infeasibility. An unknown reference is
    an error: nothing about that step can be verified.

    args:
        step (PlanStep): the step under check.
        idx (int): the step index in the plan.
        plan (Plan): the whole plan, for sequence/dependency checks.
        game_state (GameState): the player's inventory and masks.
        view (KnowledgeView): authoritative knowledge lookups.
        done_ids (set[str] | None): completed objectives, quests expanded.
        dead_gates (set[str] | None): quests that can no longer be completed.

    returns:
        list[ValidationIssue]: all issues found for this step.
    """
    issues: list[ValidationIssue] = []
    objective = view.objective(step.objective_ref)

    if objective is None:
        detail = f": {step.objective_ref!r}" if step.objective_ref else ""
        issues.append(_issue("objective", idx, f"Unknown objective reference{detail}."))
        return issues

    if objective.location != step.location:
        issues.append(
            _issue("location", idx, f"{step.location!r} is not where {step.objective_ref} happens.")
        )

    now = game_state.time
    open_windows = occurrences(objective, now)
    if not open_windows:
        # The objective happens once per cycle and its window is gone: nothing
        # else about the step matters, only the cycle restart does.
        return [
            _issue(
                "unreachable",
                idx,
                f"{objective.title}: its window ended at {objective.window.end}. "
                "Use the Song of Time to restart the cycle.",
            )
        ]
    if _lt(step.window.start, now):
        issues.append(
            _issue(
                "unreachable",
                idx,
                f"Step starts at {step.window.start}, but it is now {now}. "
                "Use the Song of Time to restart the cycle.",
            )
        )

    if not any(
        _lte(window.start, step.window.start) and _lte(step.window.end, window.end)
        for window in open_windows
    ):
        issues.append(
            _issue(
                "time",
                idx,
                f"Window {step.window} falls outside the objective's slot {objective.window}.",
            )
        )

    if objective.npc_id:
        npc = view.npc(objective.npc_id)
        if npc and not any(
            _lte(w.start, step.window.start) and _lte(step.window.end, w.end) for w in npc.schedule
        ):
            issues.append(_issue("npc", idx, f"{npc.name} is unavailable during {step.window}."))

    provided_items, provided_masks = _provided_upstream(idx, plan, view)
    missing_items = [
        item
        for item in objective.requires_items
        if item not in game_state.inventory and item not in provided_items
    ]
    if missing_items:
        issues.append(_issue("item", idx, f"Missing item(s): {', '.join(missing_items)}."))

    missing_masks = [
        mask
        for mask in objective.requires_masks
        if mask not in game_state.masks and mask not in provided_masks
    ]
    if missing_masks:
        issues.append(_issue("mask", idx, f"Missing mask(s): {', '.join(missing_masks)}."))

    missing_prereqs = _missing_prerequisites(idx, objective, plan, game_state, view, done_ids)
    if missing_prereqs:
        issues.append(
            _issue("prerequisite", idx, f"Missing prerequisite(s): {', '.join(missing_prereqs)}.")
        )

    # Quest prerequisites
    quest_reqs = objective.requires_quests
    unreachable_quests = dead_gates or set()
    for qreq in quest_reqs:
        if qreq in unreachable_quests:
            issues.append(
                ValidationIssue(
                    severity="error",
                    step_idx=idx,
                    kind="unreachable",
                    message=(
                        f"Quest prerequisite out of reach: {_quest_display_name(qreq, view)}. "
                        "Its window has closed; use the Song of Time to restart the cycle."
                    ),
                )
            )
            continue
        missing_chain = _quest_prerequisite_closure(qreq, game_state, plan, view, done_ids=done_ids)
        if missing_chain:
            # build message with transitive info
            if len(missing_chain) == 1 and missing_chain[0] == qreq:
                msg = (
                    f"Quest prerequisite missing: {_quest_display_name(qreq, view)}. "
                    "Complete this quest first."
                )
            else:
                # ancestors first, then the required quest
                parts = []
                for mq in missing_chain:
                    parts.append(_quest_display_name(mq, view))
                msg = (
                    f"Quest prerequisite missing: {', '.join(parts)}. Complete these quests first."
                )
            issues.append(
                ValidationIssue(
                    severity="error", step_idx=idx, kind="quest_prerequisite", message=msg
                )
            )

    for prereq in objective.prerequisites:
        for earlier in plan.steps[:idx]:
            if earlier.objective_ref != prereq:
                continue
            if _lt(step.window.start, earlier.window.end):
                issues.append(
                    _issue("sequence", idx, "Depends on a step that ends after this one starts.")
                )
    return issues


def _check_overlaps(plan: Plan) -> list[ValidationIssue]:
    """Flag consecutive plan steps whose windows overlap.

    The dependency check only follows prerequisite edges; unrelated steps can
    still collide. A plan is one linear schedule, so consecutive steps must not
    overlap either.

    args:
        plan (Plan): the plan being validated.

    returns:
        list[ValidationIssue]: one ``overlap`` error per colliding step.
    """
    issues: list[ValidationIssue] = []
    for idx in range(1, len(plan.steps)):
        previous = plan.steps[idx - 1]
        current = plan.steps[idx]
        if _lt(current.window.start, previous.window.end):
            issues.append(
                _issue(
                    "overlap",
                    idx,
                    f"Overlaps the previous step, which ends at {previous.window.end}.",
                )
            )
    return issues


def _provided_upstream(idx: int, plan: Plan, view: KnowledgeView) -> tuple[set[str], set[str]]:
    """Items and masks that earlier plan steps hand the player.

    A step that retrieves an item or a mask (an objective with
    ``provides_items`` / ``provides_masks``) makes that reward available to
    every later step, so a later requirement on it is satisfied even when the
    player does not yet own it at the start of the plan. The provider's
    objective is resolved through the knowledge view, never read from the
    step fields.

    args:
        idx (int): the step index whose upstream rewards are collected.
        plan (Plan): the whole plan, for earlier steps.
        view (KnowledgeView): authoritative objective lookups.

    returns:
        tuple[set[str], set[str]]: the provided items and masks, as sets.
    """
    items: set[str] = set()
    masks: set[str] = set()
    for prior in plan.steps[:idx]:
        obj = view.objective(prior.objective_ref)
        if obj is not None:
            items.update(obj.provides_items)
            masks.update(obj.provides_masks)
    return items, masks


def _missing_prerequisites(
    idx: int,
    objective: Objective,
    plan: Plan,
    game_state: GameState,
    view: KnowledgeView,
    done_ids: set[str] | None = None,
) -> list[str]:
    """Prerequisites of a step absent from the plan and not already satisfied.

    A prerequisite counts as satisfied when it appears earlier in the plan,
    its quest is marked done, or the player already owns everything the
    prerequisite objective provides (e.g. Kafei's letter is already in the
    inventory, so "retrieve the letter" may be skipped).

    args:
        idx (int): the step's index in the plan.
        objective (Objective): the step's authoritative knowledge objective.
        plan (Plan): the whole plan, for presence checks.
        game_state (GameState): the player's inventory, masks and progress.
        view (KnowledgeView): authoritative objective lookups.

    returns:
        list[str]: the ids of any unfulfilled prerequisites.
    """
    present = {s.objective_ref for s in plan.steps[:idx]}
    done = {qid for qid, status in (game_state.quest_progress or {}).items() if status == "done"}
    completed = done_ids or set(game_state.completed_objectives)
    missing = []
    for prereq in objective.prerequisites:
        if prereq in present:
            continue
        if prereq in completed:
            continue
        prereq_obj = view.objective(prereq)
        if prereq_obj is not None and view.quest_id(prereq) in done:
            continue
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
    return clock_key(a) < clock_key(b)


def _lte(a: ClockTime, b: ClockTime) -> bool:
    """Less-or-equal comparison of two clocks over the three-day cycle.

    args:
        a (ClockTime): first time.
        b (ClockTime): second time.

    returns:
        bool: True when ``a`` is before or equal to ``b``.
    """
    return clock_key(a) <= clock_key(b)


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
    plan_input = f"{len(state.plan.steps)} step(s)" if state.plan else "no plan"
    with traced_span("validation", kind="CHAIN", input_value=plan_input) as validation_span:
        result = validate_plan(state.plan, state.game_state, state.relevant_objectives)
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
