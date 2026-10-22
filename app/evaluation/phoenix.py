"""Best-effort publication of evaluation scores to Phoenix span annotations.

Each evaluated scenario is annotated on its own ``pipeline.run`` trace:

* ``evaluation/overall`` — score 1/0 with a PASS/FAIL label and an
  explanation naming what failed (the failed checks, or the run error);
* one ``evaluation/<kind>`` annotation per **failed** check (score 0);
* warnings (e.g. ``proposal_fidelity``) get the same annotation with a
  ``warning`` label and **no score**, so they never read as a failure.

Everything here is optional telemetry (see :mod:`app.phoenix` for the
shared client): without a Phoenix endpoint, or when the run produced no
span id, publishing is a no-op, and any transport error is a log line — an
unreachable Phoenix must never fail a sweep.
"""

from __future__ import annotations

import logging

import httpx

from app.evaluation.models import EvaluationIssue, ScenarioResult
from app.phoenix import ANNOTATOR_KIND, annotation_base_url, clip, identifier, post_annotations
from app.trace import flush_spans

logger = logging.getLogger(__name__)


def _overall(result: ScenarioResult) -> dict:
    """The PASS/FAIL annotation every run gets."""
    if result.error:
        explanation = clip(f"Run failed before a plan was produced: {result.error}")
    else:
        failed = [issue for issue in result.issues if issue.severity == "error"]
        warnings = [issue for issue in result.issues if issue.severity == "warning"]
        if failed:
            explanation = clip("; ".join(f"{i.kind}: {i.message}" for i in failed))
        else:
            explanation = "All checks passed."
        if warnings:
            explanation = clip(f"{explanation} ({len(warnings)} warning(s))")
    return {
        "name": "evaluation/overall",
        "annotator_kind": ANNOTATOR_KIND,
        "span_id": result.span_id,
        "identifier": identifier(result.run_id, "overall"),
        "result": {
            "score": 1.0 if result.passed else 0.0,
            "label": "PASS" if result.passed else "FAIL",
            "explanation": explanation,
        },
        "metadata": {
            "scenario_id": result.scenario_id,
            "run_id": result.run_id,
            "model": result.model,
            "duration_s": result.duration_s,
            "retrieval_status": result.retrieval_status,
        },
    }


def _issue_annotation(result: ScenarioResult, issue: EvaluationIssue) -> dict:
    """One annotation per issue: failed checks score 0, warnings carry no score."""
    body: dict = {
        "name": f"evaluation/{issue.kind}",
        "annotator_kind": ANNOTATOR_KIND,
        "span_id": result.span_id,
        "identifier": identifier(result.run_id, f"{issue.kind}:{issue.severity}:{issue.step_idx}"),
        "result": {"label": "warning", "explanation": clip(issue.message)},
        "metadata": {"severity": issue.severity, "step_idx": issue.step_idx},
    }
    if issue.severity == "error":
        body["result"] = {
            "score": 0.0,
            "label": "FAIL",
            "explanation": clip(issue.message),
        }
    return body


def annotations_for(result: ScenarioResult) -> list[dict]:
    """Build every span annotation for one evaluated scenario.

    args:
        result (ScenarioResult): the evaluated scenario.

    returns:
        list[dict]: Phoenix ``SpanAnnotationData`` bodies (empty when the
        run produced no span id).
    """
    if not result.span_id:
        return []
    return [_overall(result), *(_issue_annotation(result, i) for i in result.issues)]


def publish_result_scores(result: ScenarioResult, *, client: httpx.Client | None = None) -> bool:
    """Post one scenario's annotations to Phoenix; never raises.

    args:
        result (ScenarioResult): the evaluated scenario to annotate.
        client (httpx.Client | None, default None): injectable client for
            tests; a short-lived default client is used otherwise.

    returns:
        bool: True when Phoenix accepted the annotations.
    """
    return post_annotations(
        annotations_for(result),
        description=f"scores for {result.scenario_id}",
        client=client,
    )


def publish_scores(results: list[ScenarioResult], *, client: httpx.Client | None = None) -> int:
    """Post the scores of a whole sweep, flushing pending spans first.

    The flush matters: spans are exported asynchronously, and an annotation
    posted before Phoenix ingested the trace would point at nothing.

    args:
        results (list[ScenarioResult]): every evaluated scenario of the sweep.
        client (httpx.Client | None, default None): injectable client for tests.

    returns:
        int: how many scenarios were annotated.
    """
    if annotation_base_url() is None:
        return 0
    if not any(result.span_id for result in results):
        return 0
    flush_spans()
    published = sum(1 for result in results if publish_result_scores(result, client=client))
    logger.info("Phoenix: %d of %d scenario scores published", published, len(results))
    return published
