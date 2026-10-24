"""Evaluation scores reach Phoenix as span annotations, best-effort and offline."""

from __future__ import annotations

import json

import httpx
import pytest

from app.evaluation.models import EvaluationIssue, ScenarioResult
from app.evaluation.phoenix import (
    annotation_base_url,
    annotations_for,
    publish_result_scores,
    publish_scores,
)
from app.evaluation.scenarios import SCENARIOS_BY_ID
from app.state import PlanningState


@pytest.fixture(autouse=True)
def _phoenix_env(monkeypatch):
    """A Phoenix endpoint is configured for every test unless it opts out."""
    monkeypatch.delenv("PHOENIX_BASE_URL", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://phoenix.test:6006")


def _failed_result(**overrides) -> ScenarioResult:
    defaults = dict(
        scenario_id="anju-kafei",
        passed=False,
        issues=[
            EvaluationIssue(
                severity="error",
                kind="temporal_ordering",
                message="Step 2 overlaps the previous step.",
                step_idx=1,
            ),
            EvaluationIssue(
                severity="warning",
                kind="proposal_fidelity",
                message="The LLM proposal omitted expected objectives: ak_get_kafei_mask.",
            ),
        ],
        model="llama3.2",
        run_id="abc12345",
        span_id="0123456789abcdef",
        trace_id="fedcba9876543210",
    )
    defaults.update(overrides)
    return ScenarioResult(**defaults)


def _capturing_client(status_code: int = 200) -> tuple[httpx.Client, list[httpx.Request]]:
    """A client whose POSTs are recorded and answered locally (no network)."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return client, requests


def test_failed_run_yields_overall_and_issue_annotations():
    """A failing run gets one overall score, one per issue, warnings unscored."""
    annotations = annotations_for(_failed_result())

    overall, error, warning = annotations
    assert overall["name"] == "evaluation/overall"
    assert overall["result"]["score"] == 0.0
    assert overall["result"]["label"] == "FAIL"
    assert "temporal_ordering" in overall["result"]["explanation"]
    assert overall["metadata"]["scenario_id"] == "anju-kafei"
    assert overall["identifier"] == "termina:abc12345:overall"

    assert error["name"] == "evaluation/temporal_ordering"
    assert error["result"]["score"] == 0.0
    assert error["metadata"]["step_idx"] == 1

    assert warning["name"] == "evaluation/proposal_fidelity"
    assert "score" not in warning["result"]
    assert warning["result"]["label"] == "warning"

    for annotation in annotations:
        assert annotation["annotator_kind"] == "CODE"
        assert annotation["span_id"] == "0123456789abcdef"


def test_passing_run_scores_one_overall_annotation():
    """A clean run is a single PASS annotation with a perfect score."""
    annotations = annotations_for(_failed_result(passed=True, issues=[]))

    assert len(annotations) == 1
    assert annotations[0]["result"]["score"] == 1.0
    assert annotations[0]["result"]["label"] == "PASS"
    assert annotations[0]["result"]["explanation"] == "All checks passed."


def test_run_error_is_explained_on_the_overall_annotation():
    """A crashed run reports why it never produced a plan."""
    result = _failed_result(issues=[], error="PlanningAgentError: LLM returned an empty plan")

    annotations = annotations_for(result)

    assert len(annotations) == 1
    assert "empty plan" in annotations[0]["result"]["explanation"]
    assert annotations[0]["result"]["score"] == 0.0


def test_without_a_span_id_there_are_no_annotations():
    """A hand-built result (no traced run) has nothing to attach a score to."""
    assert annotations_for(_failed_result(span_id="")) == []


def test_base_url_prefers_phoenix_base_url(monkeypatch):
    """The explicit Phoenix URL wins over the OTLP endpoint when both are set."""
    monkeypatch.setenv("PHOENIX_BASE_URL", "http://phoenix.local:6006/")

    assert annotation_base_url() == "http://phoenix.local:6006"

    monkeypatch.delenv("PHOENIX_BASE_URL")
    assert annotation_base_url() == "http://phoenix.test:6006"

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    assert annotation_base_url() is None


def test_publish_posts_the_documented_payload():
    """The body matches Phoenix's AnnotateSpansRequestBody: data, list, ids."""
    client, requests = _capturing_client()

    assert publish_result_scores(_failed_result(), client=client) is True

    (request,) = requests
    assert request.url.path == "/v1/span_annotations"
    body = json.loads(request.content)
    assert len(body["data"]) == 3
    assert body["data"][0]["name"] == "evaluation/overall"
    assert body["data"][0]["span_id"] == "0123456789abcdef"


def test_publish_without_an_endpoint_is_silent(monkeypatch):
    """No endpoint configured means no attempt, not an error."""
    monkeypatch.delenv("PHOENIX_BASE_URL", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    client, requests = _capturing_client()

    assert annotation_base_url() is None
    assert publish_result_scores(_failed_result(), client=client) is False
    assert requests == []


def test_publish_fails_soft_when_phoenix_rejects():
    """A dead or angry Phoenix is a log line; the sweep must not notice."""
    client, _requests = _capturing_client(status_code=500)

    assert publish_result_scores(_failed_result(), client=client) is False


def test_publish_scores_flushes_spans_and_counts(monkeypatch):
    """The sweep endpoint flushes pending spans, then annotates every run."""
    from app.evaluation import phoenix as phoenix_module

    flushed: list[int] = []
    monkeypatch.setattr(phoenix_module, "flush_spans", lambda **kwargs: flushed.append(kwargs))
    client, requests = _capturing_client()
    results = [_failed_result(), _failed_result(span_id="", run_id="")]

    assert publish_scores(results, client=client) == 1
    assert len(flushed) == 1
    assert len(requests) == 1


def test_publish_scores_is_a_noop_without_a_span(monkeypatch):
    """A sweep that never ran a traced pipeline does not touch the network."""
    from app.evaluation import phoenix as phoenix_module

    monkeypatch.setattr(phoenix_module, "flush_spans", lambda **kwargs: pytest.fail("flush called"))
    client, requests = _capturing_client()

    assert publish_scores([_failed_result(span_id="")], client=client) == 0
    assert requests == []


def test_run_scenario_records_the_root_span_ids(monkeypatch):
    """The result carries the ids of the run it measured, for report↔trace."""
    from app.evaluation import runner as runner_module
    from app.trace import current_run_id, pipeline_span, setup_tracing

    # Install a real (exporter-less) provider: the fixture's fake endpoint
    # must not leave a session-wide exporter pointing at a dead host.
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    setup_tracing()

    def fake_run_pipeline(game_state, goal, preferences=None):
        with pipeline_span(goal.description):
            pass
        return PlanningState(game_state=game_state, goal=goal)

    monkeypatch.setattr(runner_module, "run_pipeline", fake_run_pipeline)

    result = runner_module.run_scenario(SCENARIOS_BY_ID["anju-kafei"])

    assert result.run_id == current_run_id()
    assert len(result.span_id) == 16
    assert len(result.trace_id) == 32
    assert int(result.span_id, 16) > 0
    assert int(result.trace_id, 16) > 0
