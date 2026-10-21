"""Contracts for the Phase 11 plan-evaluation harness.

A scenario states a player state, a goal and the outcome the plan is expected
to reach. The evaluator turns a produced plan into a :class:`ScenarioResult`
with an explicit PASS/FAIL and one issue per failed check.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from app.domain import GameState

Severity = Literal["error", "warning"]


class PlanScenario(BaseModel):
    """One evaluation scenario: a state, a goal and the expected outcome."""

    id: str
    name: str = ""
    description: str = ""
    goal: str
    game_state: GameState
    # Objective refs the plan must contain to achieve the goal.
    required_objective_refs: list[str] = Field(default_factory=list)
    # The objective that completes the goal; expected as the final step.
    terminal_objective_ref: str = ""
    # Objective refs that must not appear (already satisfied, irrelevant...).
    forbidden_objective_refs: list[str] = Field(default_factory=list)
    # Pairs of objective refs that must appear in this order.
    expected_order: list[tuple[str, str]] = Field(default_factory=list)
    min_steps: int = Field(default=1, ge=0)
    # 0 means "no upper bound".
    max_steps: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def require_expectations(self) -> "PlanScenario":
        """Reject scenarios that expect nothing.

        args:
            (none)

        returns:
            PlanScenario: the validated scenario.
        """
        if not self.goal.strip():
            raise ValueError("evaluation scenario needs a goal")
        if not self.required_objective_refs and not self.terminal_objective_ref:
            raise ValueError("evaluation scenario needs at least one expected objective")
        return self


class EvaluationIssue(BaseModel):
    """One failed expectation, with the check that produced it."""

    severity: Severity = "error"
    kind: str
    message: str
    step_idx: int | None = None


class ScenarioResult(BaseModel):
    """Outcome of one evaluated scenario."""

    scenario_id: str
    passed: bool = False
    issues: list[EvaluationIssue] = Field(default_factory=list)
    step_count: int = 0
    objective_refs: list[str] = Field(default_factory=list)
    duration_s: float = 0.0
    retrieval_status: str = ""
    # Set when the run itself failed (LLM error, no plan produced).
    error: str = ""

    @computed_field
    @property
    def error_count(self) -> int:
        """Number of error-severity issues.

        args:
            (none)

        returns:
            int: the count of errors.
        """
        return sum(1 for issue in self.issues if issue.severity == "error")


class EvaluationReport(BaseModel):
    """Aggregate metrics over a set of evaluated scenarios."""

    results: list[ScenarioResult] = Field(default_factory=list)

    @computed_field
    @property
    def total(self) -> int:
        """Number of evaluated scenarios.

        args:
            (none)

        returns:
            int: the scenario count.
        """
        return len(self.results)

    @computed_field
    @property
    def passed(self) -> int:
        """Number of passing scenarios.

        args:
            (none)

        returns:
            int: the passing scenario count.
        """
        return sum(1 for result in self.results if result.passed)

    @computed_field
    @property
    def failed(self) -> int:
        """Number of failing scenarios.

        args:
            (none)

        returns:
            int: the failing scenario count.
        """
        return self.total - self.passed

    @computed_field
    @property
    def pass_rate(self) -> float:
        """Fraction of scenarios that passed.

        args:
            (none)

        returns:
            float: the pass rate, 0.0 when nothing was evaluated.
        """
        return self.passed / self.total if self.total else 0.0

    @computed_field
    @property
    def failures_by_kind(self) -> dict[str, int]:
        """Count of failed checks per check kind.

        args:
            (none)

        returns:
            dict: check kind to number of failing scenarios.
        """
        counts: dict[str, int] = {}
        for result in self.results:
            kinds = {issue.kind for issue in result.issues if issue.severity == "error"}
            for kind in kinds:
                counts[kind] = counts.get(kind, 0) + 1
        return counts
