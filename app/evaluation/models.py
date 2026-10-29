"""Contracts for the plan-evaluation harness.

A scenario states a player state, a goal and the outcome the plan is expected
to reach. The evaluator turns a produced plan into a :class:`ScenarioResult`
with an explicit PASS/FAIL and one issue per failed check.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from app.domain import GameState

Severity = Literal["error", "warning"]
ChangeStatus = Literal["regressed", "improved", "same", "new", "missing"]
#: What a scenario expects the run to produce: a plan, or the explicit
#: temporal verdict of a clock that has already closed the whole chain.
ExpectedOutcome = Literal["plan", "unreachable"]


class PlanScenario(BaseModel):
    """One evaluation scenario: a state, a goal and the expected outcome."""

    id: str
    name: str = ""
    description: str = ""
    goal: str
    game_state: GameState
    # ``"plan"`` expects the objectives below to be planned; ``"unreachable"``
    # expects no plan at all plus an ``unreachable`` Critic verdict.
    expected_outcome: ExpectedOutcome = "plan"
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
        """Reject scenarios that expect nothing, or expect the impossible.

        A ``"plan"`` scenario must name at least one objective to reach. An
        ``"unreachable"`` scenario is the opposite expectation — no plan at all
        — so a plan-level expectation there is a contradiction, not a stricter
        test: it would either never be checked or turn a correct verdict into a
        failure.

        args:
            (none)

        returns:
            PlanScenario: the validated scenario.
        """
        if not self.goal.strip():
            raise ValueError("evaluation scenario needs a goal")
        if self.expected_outcome == "unreachable":
            contradictions = [
                name
                for name, expected in (
                    ("required_objective_refs", bool(self.required_objective_refs)),
                    ("terminal_objective_ref", bool(self.terminal_objective_ref)),
                    ("expected_order", bool(self.expected_order)),
                    ("min_steps", self.min_steps > 0),
                )
                if expected
            ]
            if contradictions:
                raise ValueError(
                    "an unreachable scenario cannot expect a plan: set "
                    + ", ".join(contradictions)
                    + " to an empty value"
                )
            return self
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
    # Model that produced the plan (its name, falling back to its engine).
    model: str = ""
    # Set when the run itself failed (LLM error, no plan produced).
    error: str = ""
    # Ids of the run's root span, so the report links back to the Phoenix
    # trace (and evaluation scores can be posted onto it). Empty when the
    # run happened without a traced pipeline (hand-built results, no tracer).
    run_id: str = ""
    span_id: str = ""
    trace_id: str = ""

    @computed_field
    @property
    def error_count(self) -> int:
        """Number of error-severity findings.

        A crashed run counts as one error, so a failure is never reported as
        "no issues".

        args:
            (none)

        returns:
            int: the count of errors.
        """
        issues = sum(1 for issue in self.issues if issue.severity == "error")
        return issues + (1 if self.error else 0)

    @computed_field
    @property
    def warning_count(self) -> int:
        """Number of warning-severity findings.

        Warnings never fail a scenario, but they still have to be visible: a
        report that said "0 issues" next to a warning would read as a bug.

        args:
            (none)

        returns:
            int: the count of warnings.
        """
        return sum(1 for issue in self.issues if issue.severity == "warning")


class EvaluationReport(BaseModel):
    """Aggregate metrics over a set of evaluated scenarios."""

    results: list[ScenarioResult] = Field(default_factory=list)
    # Sweep metadata, so two saved reports can be compared. None/empty means
    # the sweep did not record it (hand-built reports and older reports).
    rag_on: bool | None = None
    repeats: int = 1
    created_at: str = ""

    @computed_field
    @property
    def wiki_retrieval(self) -> str:
        """What the supplemental wiki retrieval actually did during the sweep.

        The ``rag_on`` flag only says what was requested: a run can still
        degrade (a locked store, a dead wiki). The per-scenario statuses tell
        the truth, so this reports the degraded one instead of repeating the
        flag.

        ``wiki_miss`` is deliberately not degraded: it is also the ordinary
        outcome of a wiki that had nothing relevant for a query, and labelling
        those sweeps as broken would hide the failures that matter.

        args:
            (none)

        returns:
            str: ``"off"``, ``"on"``, ``"degraded"`` or ``"unknown"``.
        """
        if self.rag_on is False:
            return "off"
        statuses = {result.retrieval_status for result in self.results if result.retrieval_status}
        if not statuses:
            return "on" if self.rag_on else "unknown"
        if "unavailable" in statuses:
            return "degraded"
        return "on"

    @computed_field
    @property
    def models(self) -> str:
        """Distinct models that produced the plans, comma-joined.

        args:
            (none)

        returns:
            str: the model names, empty when nothing was recorded.
        """
        names = {result.model for result in self.results if result.model}
        return ", ".join(sorted(names))

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

        A scenario whose run crashed counts under the ``run_error`` kind, so a
        sweep that never produced a plan is not reported as "no failures".

        args:
            (none)

        returns:
            dict: check kind to number of failing scenarios.
        """
        counts: dict[str, int] = {}
        for result in self.results:
            if result.error:
                counts["run_error"] = counts.get("run_error", 0) + 1
            kinds = {issue.kind for issue in result.issues if issue.severity == "error"}
            for kind in kinds:
                counts[kind] = counts.get(kind, 0) + 1
        return counts


class ScenarioChange(BaseModel):
    """How one scenario's outcome changed between two sweeps."""

    scenario_id: str
    # Outcome in the baseline/current sweep; None marks the scenario as
    # absent there (a partial sweep never counts as a regression).
    previous: bool | None = None
    current: bool | None = None
    status: ChangeStatus
    # Error-severity check kinds that the baseline did not have (regressed only).
    new_failure_kinds: list[str] = Field(default_factory=list)


class SweepComparison(BaseModel):
    """Difference between a sweep and the stored sweep it was compared with.

    Both sides are summarized here (pass counts, model, wiki flag, repeats),
    so a renderer never needs the two reports again and the comparison can be
    serialized on its own.
    """

    baseline_created_at: str = ""
    baseline_model: str = ""
    baseline_rag: str = ""
    baseline_passed: int = 0
    baseline_total: int = 0
    baseline_repeats: int = 1
    current_model: str = ""
    current_rag: str = ""
    current_passed: int = 0
    current_total: int = 0
    current_repeats: int = 1
    changes: list[ScenarioChange] = Field(default_factory=list)

    @computed_field
    @property
    def regressions(self) -> list[ScenarioChange]:
        """The scenarios that went from pass to fail.

        args:
            (none)

        returns:
            list[ScenarioChange]: the regressed scenarios.
        """
        return [change for change in self.changes if change.status == "regressed"]

    @computed_field
    @property
    def improvements(self) -> list[ScenarioChange]:
        """The scenarios that went from fail to pass.

        args:
            (none)

        returns:
            list[ScenarioChange]: the improved scenarios.
        """
        return [change for change in self.changes if change.status == "improved"]

    @computed_field
    @property
    def has_regressions(self) -> bool:
        """Whether any scenario regressed against the baseline.

        args:
            (none)

        returns:
            bool: True when at least one scenario went from pass to fail.
        """
        return bool(self.regressions)

    @computed_field
    @property
    def baseline_pass_rate(self) -> float:
        """Pass rate of the baseline sweep.

        args:
            (none)

        returns:
            float: the baseline pass rate, 0.0 when it evaluated nothing.
        """
        return self.baseline_passed / self.baseline_total if self.baseline_total else 0.0

    @computed_field
    @property
    def current_pass_rate(self) -> float:
        """Pass rate of this sweep.

        args:
            (none)

        returns:
            float: the current pass rate, 0.0 when it evaluated nothing.
        """
        return self.current_passed / self.current_total if self.current_total else 0.0

    @computed_field
    @property
    def pass_rate_delta(self) -> float:
        """Signed change of pass rate against the baseline.

        args:
            (none)

        returns:
            float: current minus baseline pass rate, rounded to 3 decimals.
        """
        return round(self.current_pass_rate - self.baseline_pass_rate, 3)

    @computed_field
    @property
    def model_changed(self) -> bool:
        """Whether the two sweeps were produced by different models.

        args:
            (none)

        returns:
            bool: True when the recorded models differ.
        """
        return self.current_model != self.baseline_model

    @computed_field
    @property
    def rag_changed(self) -> bool:
        """Whether the two sweeps ran with different wiki retrieval.

        args:
            (none)

        returns:
            bool: True when the recorded retrieval states differ.
        """
        return self.current_rag != self.baseline_rag

    @computed_field
    @property
    def repeats_changed(self) -> bool:
        """Whether the two sweeps used a different repeat count.

        args:
            (none)

        returns:
            bool: True when the repeat counts differ.
        """
        return self.current_repeats != self.baseline_repeats
