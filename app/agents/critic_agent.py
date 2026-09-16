"""Critic/Validator Agent: checks whether the plan is feasible.

Runs deterministic feasibility rules against the player's state and the
knowledge base. This is the important domain logic kept dependency-free so it
can be unit-tested directly.
"""

from __future__ import annotations

import logging

from app.data.mock_knowledge import NPC, Objective, build_default_knowledge
from app.domain import (
    ClockTime,
    GameState,
    Plan,
    PlanStep,
    ValidationIssue,
    ValidationResult,
)
from app.state import PlanningState

logger = logging.getLogger(__name__)


def validate_plan(
    plan: Plan | None,
    game_state: GameState,
    objectives: list[Objective],
    npcs: list[NPC] | None = None,
) -> ValidationResult:
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


def _check_step(
    step: PlanStep,
    idx: int,
    plan: Plan,
    game_state: GameState,
    by_id: dict[str, Objective],
    npc_by_id: dict[str, NPC],
) -> list[ValidationIssue]:
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

    missing = [item for item in step.requires_items if item not in game_state.inventory]
    if missing:
        issues.append(_issue("item", idx, f"Missing item(s): {', '.join(missing)}."))

    for earlier in step.depends_on:
        if earlier >= idx:
            continue
        if _lt(step.window.start, plan.steps[earlier].window.end):
            issues.append(
                _issue("sequence", idx, "Depends on a step that ends after this one starts.")
            )
    return issues


def _lt(a: ClockTime, b: ClockTime) -> bool:
    return (a.day, a.hour, a.minute) < (b.day, b.hour, b.minute)


def _lte(a: ClockTime, b: ClockTime) -> bool:
    return (a.day, a.hour, a.minute) <= (b.day, b.hour, b.minute)


def _issue(kind: str, step_idx: int, message: str) -> ValidationIssue:
    return ValidationIssue(severity="error", step_idx=step_idx, kind=kind, message=message)


def run(state: PlanningState) -> dict:
    npcs = _KB.npcs
    result = validate_plan(state.plan, state.game_state, state.relevant_objectives, npcs)
    _log_result(result)
    return {"validation": result, "critic_engine": "rule-based"}


def _log_result(result: ValidationResult) -> None:
    if result.valid:
        logger.info("Critic [rules]: VALID")
        return
    logger.info("Critic [rules]: INVALID — %d issue(s)", len(result.issues))
    for issue in result.issues:
        step = f"step {issue.step_idx + 1}" if issue.step_idx is not None else "plan"
        logger.info("  - [%s/%s] %s: %s", issue.severity, issue.kind, step, issue.message)


_KB = build_default_knowledge()
