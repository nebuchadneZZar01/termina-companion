"""Run the evaluation scenarios against the live pipeline.

Both entry points use this module, so the CLI harness and the Streamlit
evaluation tab measure exactly the same thing:

* ``scripts/evaluate_plans.py`` — the maintainer tool, prints a report and
  exits non-zero on failure.
* the *Evaluation* tab of the Streamlit UI — the same sweep, in the browser.

The memory store is cleared before every scenario, so a scenario never sees
the episodes of the previous ones and the sweep stays reproducible.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Sequence

from app.domain import Goal
from app.evaluation.evaluator import evaluate_plan
from app.evaluation.models import EvaluationReport, PlanScenario, ScenarioResult
from app.evaluation.phoenix import publish_scores
from app.graph import run_pipeline
from app.memory.store import get_memory_store
from app.trace import current_run_id, current_span_ids

logger = logging.getLogger(__name__)

RAG_ENV_VAR = "RAG_ENABLED"


def run_scenario(scenario: PlanScenario) -> ScenarioResult:
    """Run the pipeline for one scenario and evaluate the produced plan.

    A failed run (missing LLM, planner error, timeout) is reported as an
    error-severity result, never as an exception: one broken scenario must
    not abort the whole sweep.

    args:
        scenario (PlanScenario): the scenario to run.

    returns:
        ScenarioResult: the evaluation outcome.
    """
    get_memory_store().clear()
    started = time.perf_counter()
    try:
        state = run_pipeline(scenario.game_state, Goal(description=scenario.goal))
    except Exception as exc:  # noqa: BLE001 - a failed run is a result, not a crash
        logger.warning("Evaluation: scenario %s failed: %s", scenario.id, exc)
        span_id, trace_id = current_span_ids()
        return ScenarioResult(
            scenario_id=scenario.id,
            passed=False,
            duration_s=round(time.perf_counter() - started, 1),
            error=f"{type(exc).__name__}: {exc}",
            run_id=current_run_id(),
            span_id=span_id,
            trace_id=trace_id,
        )
    outcome = evaluate_plan(
        state.plan,
        scenario,
        tool_calls=state.tool_calls,
        validation=state.validation,
        plan_proposal=state.plan_proposal,
        attempt_log=state.attempt_log,
        plan_engine=state.plan_engine,
    )
    outcome.duration_s = round(time.perf_counter() - started, 1)
    outcome.retrieval_status = state.retrieval_status
    outcome.model = state.plan_model or state.plan_engine
    # The trace ids of this run's root span, kept in the report so the score
    # can be posted onto the Phoenix trace and the report links back to it.
    outcome.run_id = current_run_id()
    outcome.span_id, outcome.trace_id = current_span_ids()
    return outcome


def run_scenarios(
    scenarios: Sequence[PlanScenario],
    rag_on: bool = True,
    on_progress: Callable[[PlanScenario, ScenarioResult], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> EvaluationReport:
    """Run every scenario in order and collect the results.

    args:
        scenarios (Sequence[PlanScenario]): the scenarios to run.
        rag_on (bool, default True): whether the supplemental wiki retrieval
            runs during the sweep. The flag is restored when the sweep ends.
        on_progress (Callable[..., None] | None, default None): called after
            each scenario with the scenario and its result.
        should_stop (Callable[[], bool] | None, default None): polled before
            each scenario; when it returns True the sweep stops early.

    returns:
        EvaluationReport: the aggregated results, tagged with the sweep
        metadata (the RAG flag and, from the runs, the producing models).
    """
    previous = os.environ.get(RAG_ENV_VAR)
    os.environ[RAG_ENV_VAR] = "1" if rag_on else "0"
    results: list[ScenarioResult] = []
    try:
        for scenario in scenarios:
            if should_stop is not None and should_stop():
                break
            result = run_scenario(scenario)
            results.append(result)
            if on_progress is not None:
                on_progress(scenario, result)
    finally:
        if previous is None:
            os.environ.pop(RAG_ENV_VAR, None)
        else:
            os.environ[RAG_ENV_VAR] = previous
    publish_scores(results)
    return EvaluationReport(results=results, rag_on=rag_on)
