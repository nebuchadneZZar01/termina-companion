"""Phoenix span-annotation client shared by every publisher.

Posting an annotation is optional telemetry: without a Phoenix endpoint it
is a no-op, and any transport error is a log line — an unreachable Phoenix
must never fail a run or a sweep. The endpoint is shared with tracing
(``PHOENIX_BASE_URL`` if set, otherwise ``OTEL_EXPORTER_OTLP_ENDPOINT``),
so annotations always land where the traces do.

Two publishers use this seam:

* :func:`publish_plan_validation` — the Critic's verdict of **every** run
  (``plan/validation``), called by ``run_pipeline``;
* ``app.evaluation.phoenix`` — the deterministic harness scores of a sweep
  (``evaluation/*``).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import httpx

from app.trace import current_run_id, current_span_ids, flush_spans

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from app.state import PlanningState

logger = logging.getLogger(__name__)

#: Deterministic code, not a model or a human, for Phoenix's column.
ANNOTATOR_KIND = "CODE"
#: Bound for a single explanation, so one huge issue message cannot bloat
#: the annotation payload (the report keeps the full text).
EXPLANATION_LIMIT = 500
REQUEST_TIMEOUT_S = 5.0


def annotation_base_url() -> str | None:
    """Where span annotations should be posted, or None to stay silent.

    args:
        (none)

    returns:
        str | None: the Phoenix base URL (no trailing slash), or None when
        neither ``PHOENIX_BASE_URL`` nor ``OTEL_EXPORTER_OTLP_ENDPOINT`` is
        configured.
    """
    for name in ("PHOENIX_BASE_URL", "OTEL_EXPORTER_OTLP_ENDPOINT"):
        raw = os.getenv(name, "").strip().removesuffix("/")
        if raw:
            return raw
    return None


def clip(text: str) -> str:
    """Bound one explanation to :data:`EXPLANATION_LIMIT` characters."""
    text = " ".join(str(text).split())
    if len(text) <= EXPLANATION_LIMIT:
        return text
    return text[: EXPLANATION_LIMIT - 1] + "…"


def identifier(run_id: str, suffix: str) -> str:
    """Stable upsert key, so re-publishing the same run updates in place."""
    if not run_id:
        return ""
    return f"termina:{run_id}:{suffix}"


def post_annotations(
    annotations: list[dict],
    *,
    description: str,
    client: httpx.Client | None = None,
) -> bool:
    """Post span annotations to Phoenix; never raises.

    args:
        annotations (list[dict]): Phoenix ``SpanAnnotationData`` bodies
            (empty means nothing to do).
        description (str): what is being annotated, for the log lines.
        client (httpx.Client | None, default None): injectable client for
            tests; a short-lived default client is used otherwise.

    returns:
        bool: True when Phoenix accepted the annotations.
    """
    base = annotation_base_url()
    if base is None or not annotations:
        return False
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=REQUEST_TIMEOUT_S)
    try:
        response = client.post(f"{base}/v1/span_annotations", json={"data": annotations})
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - telemetry must never break a run
        logger.warning("Phoenix: could not publish %s: %s", description, exc)
        return False
    finally:
        if owns_client:
            client.close()
    logger.info("Phoenix: published %d annotation(s) for %s", len(annotations), description)
    return True


def plan_validation_annotation(state: PlanningState) -> dict | None:
    """Build the Critic-verdict annotation for one finished run.

    args:
        state (PlanningState): the final workflow state of the run.

    returns:
        dict | None: a ``plan/validation`` SpanAnnotationData body, or None
        when the run has no Critic verdict or no traced span to attach to.
    """
    if state.validation is None:
        return None
    span_id, _trace_id = current_span_ids()
    if not span_id:
        return None
    validation = state.validation
    run_id = current_run_id()
    if validation.valid:
        explanation = "Plan is feasible."
    else:
        explanation = (
            clip("; ".join(f"{i.kind}: {i.message}" for i in validation.issues))
            or "Plan is not feasible."
        )
    return {
        "name": "plan/validation",
        "annotator_kind": ANNOTATOR_KIND,
        "span_id": span_id,
        "identifier": identifier(run_id, "plan-validation"),
        "result": {
            "score": 1.0 if validation.valid else 0.0,
            "label": "PASS" if validation.valid else "FAIL",
            "explanation": explanation,
        },
        "metadata": {
            "run_id": run_id,
            "goal": clip(state.goal.description),
            "attempts": len(state.attempt_log),
            "replan_attempts": state.replan_attempts,
            "model": state.plan_model or state.plan_engine,
            "errors": sum(1 for i in validation.issues if i.severity == "error"),
            "warnings": sum(1 for i in validation.issues if i.severity == "warning"),
        },
    }


def publish_plan_validation(state: PlanningState, *, client: httpx.Client | None = None) -> bool:
    """Annotate the run's trace with the Critic's verdict; never raises.

    Called by ``run_pipeline`` after the pipeline span closed, so the trace
    is exportable; :func:`flush_spans` pushes it out before the POST, or the
    annotation could arrive before the trace Phoenix should attach it to.

    args:
        state (PlanningState): the final workflow state of the run.
        client (httpx.Client | None, default None): injectable client for tests.

    returns:
        bool: True when the verdict was annotated.
    """
    annotation = plan_validation_annotation(state)
    if annotation is None:
        return False
    if annotation_base_url() is None:
        return False
    flush_spans()
    return post_annotations([annotation], description="plan validation", client=client)
