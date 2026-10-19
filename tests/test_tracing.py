"""Phase 10 tracing: run collection, spans and the LLM callback.

These tests are hermetic: the default tracer is the no-op provider (no
``OTEL_EXPORTER_OTLP_ENDPOINT``), so nothing is exported and no backend is
needed. The exported-span tests patch the tracers onto a real SDK provider
with an ``InMemorySpanExporter`` and assert the OpenInference attributes
(Kind, Status, Input/Output) the Phoenix dashboard displays.
"""

from __future__ import annotations

import json
import logging
import re

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app import graph as graph_mod
from app import trace as trace_mod
from app.domain import ClockTime, GameState, Goal
from app.graph import _with_start, run_pipeline
from app.trace import (
    LLM_LOG_PAYLOAD_LIMIT,
    TraceCallback,
    current_run,
    pipeline_span,
)


def _llm_result(content: str = "done", usage: dict | None = None) -> LLMResult:
    """Build a minimal LLMResult with one AI message."""
    message = AIMessage(content=content, usage_metadata=usage)
    return LLMResult(generations=[[ChatGeneration(message=message)]])


@pytest.fixture
def memory_tracing(monkeypatch):
    """Patch the app tracers onto a real SDK provider exporting in memory."""
    exporter = InMemorySpanExporter()
    provider = SDKTracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("termina-tests")
    monkeypatch.setattr(trace_mod, "get_tracer", lambda *args, **kwargs: tracer)
    yield exporter, tracer
    provider.shutdown()


def test_pipeline_span_records_run_and_nodes(fake_planner_model):
    """A full headless run yields a run id, node timeline and no errors."""
    state = GameState(time=ClockTime(day=2, hour=9), location="Stockpot Inn")
    goal = Goal(description="Reunite Anju and Kafei")
    run_pipeline(state, goal)

    run = current_run()
    assert run is not None
    assert re.fullmatch(r"[0-9a-f]{8}", run.run_id)
    names = [node["name"] for node in run.nodes]
    # memory_store is not announced (no _with_start wrapper), the rest are.
    assert {"memory", "state", "knowledge", "plan", "critic"} <= set(names)
    assert all(node["status"] == "ok" for node in run.nodes)
    assert run.errors == []


def test_pipeline_span_records_goal():
    """The root span's run stores the goal text."""
    with pipeline_span("find Kafei") as run:
        assert run.goal == "find Kafei"
    assert current_run() is run


def test_node_error_is_recorded_and_reraised():
    """A failing node is logged to the run audit and re-raised."""

    def boom(_state):
        raise ValueError("node exploded")

    wrapped = _with_start("boom", boom)
    with pipeline_span("x"):
        with pytest.raises(ValueError, match="node exploded"):
            wrapped(None)
        run = current_run()
    errors = [e for e in run.errors if e["source"] == "boom"]
    assert len(errors) == 1
    assert "node exploded" in errors[0]["message"]
    assert any(n["name"] == "boom" and n["status"] == "error" for n in run.nodes)


def test_span_records_tool_error_and_reraised():
    """``app.trace.span`` records a failed tool call and re-raises."""
    with pipeline_span("x") as run:
        with pytest.raises(RuntimeError, match="tool down"):
            with trace_mod.span("mcp.get_event", event_id="e1"):
                raise RuntimeError("tool down")
    assert any(e["source"] == "mcp.get_event" for e in run.errors)


def test_callback_logs_bounded_prompts(caplog):
    """Prompts log at INFO and stay bounded, so no level floods the console."""
    long_system = "S" * (LLM_LOG_PAYLOAD_LIMIT + 500)
    callback = TraceCallback()
    messages = [[SystemMessage(content=long_system), HumanMessage(content="find Kafei")]]

    # INFO, not DEBUG: the prompts must be visible without a verbose run.
    with caplog.at_level(logging.INFO, logger="app.trace"):
        callback.on_chat_model_start({"kwargs": {"model_name": "llama3.2"}}, messages, run_id="r1")
        callback.on_llm_end(
            _llm_result("ok", usage={"input_tokens": 9, "output_tokens": 3, "total_tokens": 12}),
            run_id="r1",
        )

    info_text = "\n".join(r.getMessage() for r in caplog.records if r.levelno == logging.INFO)
    assert "find Kafei" in info_text
    assert "[truncated" in info_text
    # The truncated marker keeps the console line bounded.
    assert long_system not in info_text
    assert "tokens_in=9" in info_text


def test_callback_error_records_on_run():
    """An LLM failure is added to the current run audit."""
    callback = TraceCallback()
    with pipeline_span("x") as run:
        callback.on_llm_start({}, ["prompt"], run_id="r2")
        callback.on_llm_error(ValueError("bad key"), run_id="r2")
    assert any(e["source"] == "llm.chat" and "bad key" in e["message"] for e in run.errors)


def test_noop_tracing_without_endpoint(monkeypatch):
    """Without an OTLP endpoint the tracer is a cheap no-op."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    # setup_tracing is idempotent; call it, it must not open any connection.
    trace_mod.setup_tracing()
    with pipeline_span("offline"):
        pass
    assert current_run() is not None


def test_otlp_traces_url_resolution():
    """The base endpoint resolves to Phoenix's /v1/traces signal URL."""
    assert trace_mod._otlp_traces_url("http://localhost:6006") == "http://localhost:6006/v1/traces"
    assert trace_mod._otlp_traces_url("http://localhost:6006/") == "http://localhost:6006/v1/traces"
    # A URL that already carries the signal path is used as-is (no doubling).
    assert (
        trace_mod._otlp_traces_url("http://phoenix:6006/v1/traces")
        == "http://phoenix:6006/v1/traces"
    )


def test_phoenix_ui_url_derivation(monkeypatch):
    """The Phoenix UI link is scheme + host of the endpoint, port 6006."""
    # exercised through the UI helper, which reads the same env
    from app.ui import _phoenix_ui_url

    # Canonical Phoenix endpoint: UI and OTLP/HTTP share :6006.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:6006")
    assert _phoenix_ui_url() == "http://localhost:6006"
    # Another host, trailing slash: port is still forced to the UI port.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://phoenix:6006/")
    assert _phoenix_ui_url() == "http://phoenix:6006"
    # Any other port (e.g. a hypothetical gRPC base) still maps to the UI port.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://phoenix:4317")
    assert _phoenix_ui_url() == "http://phoenix:6006"
    # Unset -> default local UI.
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert _phoenix_ui_url() == "http://localhost:6006"


def test_exported_spans_carry_kind_status_and_io(memory_tracing):
    """Spans end with OpenInference kind, explicit OK status and input/output."""
    exporter, _tracer = memory_tracing
    with pipeline_span("find Kafei") as run:
        with trace_mod.span(
            "mcp.get_event", kind="TOOL", input_value="e1", event_id="e1"
        ) as tool_span:
            trace_mod.set_output(tool_span, {"id": "e1", "title": "Missing Sword"})
    spans = {span.name: span for span in exporter.get_finished_spans()}

    root = spans["pipeline.run"]
    assert root.attributes[trace_mod.SPAN_KIND_ATTR] == "CHAIN"
    assert root.attributes[trace_mod.INPUT_VALUE_ATTR] == "find Kafei"
    assert root.status.status_code is StatusCode.OK
    root_output = json.loads(root.attributes[trace_mod.OUTPUT_VALUE_ATTR])
    assert root_output["run_id"] == run.run_id
    assert root.attributes["termina.run_id"] == run.run_id

    tool = spans["mcp.get_event"]
    assert tool.attributes[trace_mod.SPAN_KIND_ATTR] == "TOOL"
    assert tool.attributes[trace_mod.INPUT_VALUE_ATTR] == "e1"
    assert tool.attributes["event_id"] == "e1"  # plain attributes still work
    assert tool.status.status_code is StatusCode.OK
    assert json.loads(tool.attributes[trace_mod.OUTPUT_VALUE_ATTR])["id"] == "e1"
    assert tool.attributes["termina.duration_ms"] >= 0


def test_exported_span_error_status_is_not_lost(memory_tracing):
    """A failing span ends with ERROR status, set before the span ends."""
    exporter, _tracer = memory_tracing
    with pipeline_span("x") as run:
        with pytest.raises(RuntimeError, match="tool down"):
            with trace_mod.span("mcp.get_event", kind="TOOL", input_value="e1"):
                raise RuntimeError("tool down")
    spans = {span.name: span for span in exporter.get_finished_spans()}

    tool = spans["mcp.get_event"]
    assert tool.status.status_code is StatusCode.ERROR
    assert "tool down" in (tool.status.description or "")
    # The root span itself succeeded: the failure was audited, not propagated.
    assert spans["pipeline.run"].status.status_code is StatusCode.OK
    assert any(e["source"] == "mcp.get_event" for e in run.errors)


def test_exported_pipeline_error_span(memory_tracing):
    """A crash inside the pipeline marks the root span ERROR with an output."""
    exporter, _tracer = memory_tracing
    with pytest.raises(RuntimeError, match="run exploded"):
        with pipeline_span("x"):
            raise RuntimeError("run exploded")
    root = {span.name: span for span in exporter.get_finished_spans()}["pipeline.run"]
    assert root.status.status_code is StatusCode.ERROR
    assert "run exploded" in (root.status.description or "")
    output = json.loads(root.attributes[trace_mod.OUTPUT_VALUE_ATTR])
    assert output["errors"]


def test_exported_node_span_kind_status_and_io(memory_tracing, monkeypatch):
    """Node spans carry CHAIN kind, OK status and a structured output."""
    exporter, tracer = memory_tracing
    monkeypatch.setattr(graph_mod, "get_tracer", lambda *args, **kwargs: tracer)
    wrapped = _with_start("state", lambda _state: {"state_summary": "On day 2 at Stockpot Inn"})
    with pipeline_span("x"):
        wrapped(None)
    node = {span.name: span for span in exporter.get_finished_spans()}["node.state"]
    assert node.attributes[trace_mod.SPAN_KIND_ATTR] == "CHAIN"
    assert node.status.status_code is StatusCode.OK
    assert "On day 2" in node.attributes[trace_mod.OUTPUT_VALUE_ATTR]


def test_exported_node_error_span_status(memory_tracing, monkeypatch):
    """A crashing node ends its span with ERROR status."""
    exporter, tracer = memory_tracing
    monkeypatch.setattr(graph_mod, "get_tracer", lambda *args, **kwargs: tracer)

    def boom(_state):
        raise ValueError("node exploded")

    wrapped = _with_start("boom", boom)
    with pipeline_span("x"):
        with pytest.raises(ValueError, match="node exploded"):
            wrapped(None)
    node = {span.name: span for span in exporter.get_finished_spans()}["node.boom"]
    assert node.status.status_code is StatusCode.ERROR
    assert "node exploded" in (node.status.description or "")


def test_exported_callback_span_kind_and_io(memory_tracing):
    """The gen_ai.chat span shows LLM kind and the full prompt/answer."""
    exporter, _tracer = memory_tracing
    callback = TraceCallback()
    messages = [[SystemMessage(content="be brief"), HumanMessage(content="find Kafei")]]
    callback.on_chat_model_start({"kwargs": {"model_name": "llama3.2"}}, messages, run_id="r3")
    callback.on_llm_end(_llm_result("seven steps"), run_id="r3")
    chat = {span.name: span for span in exporter.get_finished_spans()}["gen_ai.chat"]
    assert chat.attributes[trace_mod.SPAN_KIND_ATTR] == "LLM"
    assert "[system] be brief" in chat.attributes[trace_mod.INPUT_VALUE_ATTR]
    assert "[user] find Kafei" in chat.attributes[trace_mod.INPUT_VALUE_ATTR]
    assert chat.attributes[trace_mod.OUTPUT_VALUE_ATTR] == "seven steps"
    assert chat.status.status_code is StatusCode.OK
