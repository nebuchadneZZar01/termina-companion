"""Trajectory checks for evaluated runs."""

from __future__ import annotations

from collections.abc import Sequence

from app.data.mock_knowledge import Objective
from app.domain import Plan, ValidationResult
from app.evaluation.models import EvaluationIssue, PlanScenario
from app.graph import MAX_PLANNING_ATTEMPTS
from app.state import AttemptRecord


def _check_trajectory(
    objectives: list[Objective],
    tool_calls: Sequence[str],
    validation: ValidationResult | None,
    issues: list[EvaluationIssue],
) -> None:
    """Check that the run reached its plan through the expected agents.

    The planner must not work from its own knowledge: when the goal has
    objectives to retrieve, the Knowledge Agent must have called the MCP
    tools first, and the Critic must have run before the plan was returned.

    args:
        objectives (list[Objective]): the retrieved objectives.
        tool_calls (Sequence[str]): the MCP tools the Knowledge Agent invoked.
        validation (ValidationResult | None): the Critic's verdict.
        issues (list[EvaluationIssue]): the issue list to append to.

    returns:
        None: appends to ``issues``.
    """
    if objectives and not tool_calls:
        issues.append(
            EvaluationIssue(
                severity="error",
                kind="trajectory_order",
                message="The plan was produced without any MCP lookup.",
            )
        )
    if validation is None:
        issues.append(
            EvaluationIssue(
                severity="error",
                kind="trajectory_order",
                message="The Critic never validated the plan.",
            )
        )


def _check_replan(attempt_log: Sequence[AttemptRecord], issues: list[EvaluationIssue]) -> None:
    """Check that re-planning stayed bounded and did not need a rescue.

    args:
        attempt_log (Sequence[AttemptRecord]): one record per planning
            attempt, oldest first.
        issues (list[EvaluationIssue]): the issue list to append to.

    returns:
        None: appends to ``issues``.
    """
    attempts = len(attempt_log)
    if attempts == 0:
        return
    if attempts > MAX_PLANNING_ATTEMPTS:
        issues.append(
            EvaluationIssue(
                severity="error",
                kind="replan_bound",
                message=f"The run made {attempts} attempts, more than the allowed "
                f"{MAX_PLANNING_ATTEMPTS}.",
            )
        )
        return
    if attempts >= 2 and attempt_log[-1].valid:
        issues.append(
            EvaluationIssue(
                severity="warning",
                kind="replan_bound",
                message=f"The plan was accepted only after {attempts} attempts.",
            )
        )


def _check_proposal(
    scenario: PlanScenario,
    plan_proposal: Plan | None,
    by_id: dict[str, Objective],
    issues: list[EvaluationIssue],
) -> None:
    """Compare the LLM's raw proposal with what the scenario expected.

    The deterministic rebuild (grounding, dedup, chain reconciliation) may
    repair a proposal, but a proposal that misses expected objectives means
    the LLM contributed less than it should have. The message names the
    objectives by title, so the report stays readable without knowing the
    internal refs.

    args:
        scenario (PlanScenario): the expectations to compare against.
        plan_proposal (Plan | None): the LLM's proposal before repair.
        by_id (dict[str, Objective]): the objectives the goal retrieved, keyed
            by ref, used to resolve titles.
        issues (list[EvaluationIssue]): the issue list to append to.

    returns:
        None: appends to ``issues``.
    """
    if plan_proposal is None:
        return
    refs = {step.objective_ref for step in plan_proposal.steps}
    missing = [ref for ref in scenario.required_objective_refs if ref not in refs]
    if missing:
        titles = [by_id[ref].title if ref in by_id else ref for ref in missing]
        issues.append(
            EvaluationIssue(
                severity="warning",
                kind="proposal_fidelity",
                message="The LLM proposal omitted expected objectives: " + ", ".join(titles),
            )
        )
