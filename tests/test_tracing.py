"""Phase 10 tracing: run collection, spans and the LLM callback.

These tests are hermetic: the tracer runs with its default no-op provider (no
``OTEL_EXPORTER_OTLP_ENDPOINT``), so nothing is exported and no backend is
needed. They assert the in-memory run audit and the console behaviour.
"""

from __future__ import annotations

import logging
import re

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, LLMResult

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


def test_callback_logs_truncated_messages_at_debug(caplog):
    """Full prompts go to spans; DEBUG console shows bounded content."""
    long_system = "S" * (LLM_LOG_PAYLOAD_LIMIT + 500)
    callback = TraceCallback()
    messages = [[SystemMessage(content=long_system), HumanMessage(content="find Kafei")]]

    with caplog.at_level(logging.DEBUG, logger="app.trace"):
        callback.on_chat_model_start({"kwargs": {"model_name": "llama3.2"}}, messages, run_id="r1")
        callback.on_llm_end(
            _llm_result("ok", usage={"input_tokens": 9, "output_tokens": 3, "total_tokens": 12}),
            run_id="r1",
        )

    debug_text = "\n".join(r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG)
    assert "find Kafei" in debug_text
    assert "[truncated" in debug_text
    # The truncated marker keeps the console line bounded.
    assert long_system not in debug_text
    info_text = "\n".join(r.getMessage() for r in caplog.records if r.levelno == logging.INFO)
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


def test_phoenix_ui_url_derivation(monkeypatch):
    """The Phoenix UI link swaps the OTLP trace port for the UI port."""
    # exercised through the UI helper, which reads the same env
    from app.ui import _phoenix_ui_url

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    assert _phoenix_ui_url() == "http://localhost:6006"
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://phoenix:4318/")
    assert _phoenix_ui_url() == "http://phoenix:6006"
