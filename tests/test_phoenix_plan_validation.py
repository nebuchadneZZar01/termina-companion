"""Every run's trace carries the Critic verdict as a span annotation."""

from __future__ import annotations

import json

import httpx
import pytest

from app.domain import ClockTime, GameState, Goal, ValidationIssue, ValidationResult
from app.phoenix import (
    plan_validation_annotation,
    publish_plan_validation,
)
from app.state import AttemptRecord, PlanningState


@pytest.fixture(autouse=True)
def _phoenix_env(monkeypatch):
    """A Phoenix endpoint is configured for every test unless it opts out."""
    monkeypatch.delenv("PHOENIX_BASE_URL", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://phoenix.test:6006")


def _game_state() -> GameState:
    return GameState(time=ClockTime(day=1, hour=8), location="clock-town")


def _state(validation: ValidationResult | None) -> PlanningState:
    return PlanningState(
        game_state=_game_state(),
        goal=Goal(description="Meet Anju in Clock Town"),
        validation=validation,
        attempt_log=[AttemptRecord(attempt=1, valid=validation is not None and validation.valid)],
        plan_model="llama3.2",
    )


def _invalid() -> ValidationResult:
    return ValidationResult(
        valid=False,
        issues=[
            ValidationIssue(severity="error", kind="prerequisite", message="Letter missing."),
            ValidationIssue(severity="warning", kind="time", message="Tight window."),
        ],
    )


def _capturing_client(status_code: int = 200) -> tuple[httpx.Client, list[httpx.Request]]:
    """A client whose POSTs are recorded and answered locally (no network)."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code, json={})

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def _traced_state(monkeypatch, validation: ValidationResult | None) -> PlanningState:
    """A run finished under a real root span, like run_pipeline does."""
    from app.trace import pipeline_span, setup_tracing

    # A real provider, but no exporter: the fixture's fake endpoint must not
    # leave a session-wide exporter pointing at a dead host (flushes would
    # stall every test that publishes).
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    setup_tracing()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://phoenix.test:6006")
    with pipeline_span("goal"):
        state = _state(validation)
    return state


def test_feasible_plan_scores_pass(monkeypatch):
    """The Critic's acceptance is a 1.0/PASS annotation with run metadata."""
    state = _traced_state(monkeypatch, ValidationResult(valid=True))

    annotation = plan_validation_annotation(state)

    assert annotation is not None
    assert annotation["name"] == "plan/validation"
    assert annotation["annotator_kind"] == "CODE"
    assert annotation["result"] == {
        "score": 1.0,
        "label": "PASS",
        "explanation": "Plan is feasible.",
    }
    assert annotation["metadata"]["attempts"] == 1
    assert annotation["metadata"]["replan_attempts"] == 0
    assert annotation["metadata"]["model"] == "llama3.2"
    assert annotation["metadata"]["goal"] == "Meet Anju in Clock Town"
    assert len(annotation["span_id"]) == 16
    assert annotation["identifier"].startswith("termina:")


def test_rejected_plan_scores_fail_and_names_the_issues(monkeypatch):
    """The Critic's rejection is 0/FAIL explaining every issue found."""
    state = _traced_state(monkeypatch, _invalid())

    annotation = plan_validation_annotation(state)

    assert annotation is not None
    assert annotation["result"]["score"] == 0.0
    assert annotation["result"]["label"] == "FAIL"
    assert "prerequisite: Letter missing." in annotation["result"]["explanation"]
    assert "time: Tight window." in annotation["result"]["explanation"]
    assert annotation["metadata"]["errors"] == 1
    assert annotation["metadata"]["warnings"] == 1


def test_no_critic_verdict_no_annotation(monkeypatch):
    """A run that died before the Critic has nothing to say; its span already
    carries the ERROR status."""
    state = _traced_state(monkeypatch, None)

    assert plan_validation_annotation(state) is None
    assert publish_plan_validation(state) is False


def test_no_span_no_annotation():
    """A run whose span never opened has nothing to attach a verdict to."""
    from app.trace import begin_run

    # begin_run clears the span ids, exactly like a run that dies before
    # its span exists.
    begin_run("orphan")

    assert plan_validation_annotation(_state(ValidationResult(valid=True))) is None


def test_publish_posts_the_documented_payload(monkeypatch):
    """The body matches Phoenix's AnnotateSpansRequestBody."""
    client, requests = _capturing_client()

    assert publish_plan_validation(_traced_state(monkeypatch, _invalid()), client=client) is True

    (request,) = requests
    assert request.url.path == "/v1/span_annotations"
    assert len(json.loads(request.content)["data"]) == 1


def test_publish_without_an_endpoint_is_silent(monkeypatch):
    """No endpoint configured means no attempt, not an error."""
    state = _traced_state(monkeypatch, ValidationResult(valid=True))
    monkeypatch.delenv("PHOENIX_BASE_URL", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    client, requests = _capturing_client()

    assert publish_plan_validation(state, client=client) is False
    assert requests == []


def test_publish_fails_soft_when_phoenix_rejects(monkeypatch):
    """A dead or angry Phoenix is a log line; the run must not notice."""
    client, _requests = _capturing_client(status_code=500)

    assert (
        publish_plan_validation(
            _traced_state(monkeypatch, ValidationResult(valid=True)), client=client
        )
        is False
    )


def test_publish_flushes_the_trace_before_posting(monkeypatch):
    """The annotation must not reach Phoenix before the trace it belongs to."""
    from app import phoenix as phoenix_module

    state = _traced_state(monkeypatch, ValidationResult(valid=True))
    flushed: list[bool] = []
    monkeypatch.setattr(phoenix_module, "flush_spans", lambda **kwargs: flushed.append(True))
    client, requests = _capturing_client()

    assert publish_plan_validation(state, client=client) is True
    assert flushed == [True]
    assert len(requests) == 1


def test_run_pipeline_annotates_the_critic_verdict(monkeypatch):
    """The end-to-end wiring: run_pipeline posts the verdict of its state."""
    from app import graph as graph_module

    published: list[PlanningState] = []

    class _FakeGraph:
        def invoke(self, state, config=None):
            state.validation = ValidationResult(valid=True)
            return state

    monkeypatch.setattr(graph_module, "build_graph", lambda: _FakeGraph())
    monkeypatch.setattr(graph_module, "publish_plan_validation", published.append)

    result = graph_module.run_pipeline(_game_state(), Goal(description="x"))

    assert published == [result]
    assert result.validation is not None and result.validation.valid
