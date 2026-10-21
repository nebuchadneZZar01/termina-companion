"""Plan evaluation for Termina Companion (Phase 11).

The package measures whether a plan produced by the multi-agent pipeline
actually achieves the player's goal, and whether the run used the knowledge
tools it needed. It is a test bench for the whole product: the scenarios
declare what a correct plan looks like, the evaluator turns a produced plan
into an explicit PASS/FAIL, and the report aggregates the outcome.
"""

from app.evaluation.evaluator import evaluate_plan, relevant_objectives
from app.evaluation.models import (
    EvaluationIssue,
    EvaluationReport,
    PlanScenario,
    ScenarioResult,
)
from app.evaluation.runner import run_scenario, run_scenarios
from app.evaluation.scenarios import EVALUATION_SCENARIOS, SCENARIOS_BY_ID

__all__ = [
    "EVALUATION_SCENARIOS",
    "SCENARIOS_BY_ID",
    "EvaluationIssue",
    "EvaluationReport",
    "PlanScenario",
    "ScenarioResult",
    "evaluate_plan",
    "relevant_objectives",
    "run_scenario",
    "run_scenarios",
]
