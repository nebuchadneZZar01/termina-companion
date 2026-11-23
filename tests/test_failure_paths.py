"""Failure paths: explicit messages, recorded errors, safe degradation.

The matrix complements the targeted tests: the Knowledge Agent's tool failures
and the RAG wiki/store outages live in their own modules, so this file covers
the boundaries those tests do not reach — the CLI, the graph node wrapper, a
malformed LLM answer and an unusable save directory.
"""

from __future__ import annotations

import pytest

import app.__main__ as demo_cli
from app.agents import planning_agent, state_agent
from app.agents.planning_agent import PlanningAgentError
from app.data.mock_knowledge import Objective
from app.domain import ClockTime, GameState, Goal
from app.graph import run_pipeline
from app.mcp.tools import search_quests
from app.save import load_state, save_state
from app.state import PlanningState
from app.trace import current_run


def _game_state() -> GameState:
    """A feasible Day 1 player state."""
    return GameState(
        time=ClockTime(day=1, hour=8, minute=0),
        location="Stockpot Inn",
        inventory=["Hookshot"],
        masks=["Garo's Mask"],
    )


def _objectives() -> list[Objective]:
    """The Anju & Kafei chain, as the Knowledge Agent retrieves it."""
    return [
        Objective.model_validate(raw)
        for group in search_quests("Reunite Anju and Kafei")
        for raw in group["objectives"]
    ]


def _planning_state() -> PlanningState:
    """A state the Planning Agent can attempt."""
    return PlanningState(
        game_state=_game_state(),
        goal=Goal(description="Reunite Anju and Kafei"),
        relevant_objectives=_objectives(),
    )


def _snapshot() -> dict:
    """A valid save payload."""
    return {
        "version": 3,
        "day": 1,
        "time": {"day": 1, "hour": 8, "minute": 0},
        "location": "Stockpot Inn",
    }


def _break_save_dir(tmp_path, monkeypatch) -> None:
    """Point the save store at a directory that cannot exist."""
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cache" / "saves").write_text("not a directory")
    monkeypatch.setenv("RAG_QDRANT_PATH", str(tmp_path / "cache" / "qdrant"))


def test_cli_reports_a_missing_llm_without_a_traceback(capsys):
    """No provider is an actionable message and exit 1, not a crash."""
    code = demo_cli.main([])

    out = capsys.readouterr().out
    assert code == 1
    assert "Planning failed" in out
    assert "LLM_PROVIDER" in out
    assert "Traceback" not in out


def test_cli_reports_an_unexpected_node_failure(monkeypatch, capsys):
    """An unmapped exception becomes one readable line, not a raw crash."""

    def boom(planner=None):
        raise RuntimeError("state exploded")

    monkeypatch.setattr(demo_cli, "demo", boom)

    code = demo_cli.main(["--deterministic", "--no-rag"])

    out = capsys.readouterr().out
    assert code == 1
    assert "Planning failed: RuntimeError: state exploded" in out
    assert "Traceback" not in out


def test_node_failure_is_recorded_on_the_run(monkeypatch):
    """A failing node is recorded for the audit before the error propagates."""

    def boom(_state):
        raise RuntimeError("state exploded")

    monkeypatch.setattr(state_agent, "run", boom)

    with pytest.raises(RuntimeError, match="state exploded"):
        run_pipeline(_game_state(), Goal(description="Reunite Anju and Kafei"))

    run = current_run()
    assert run is not None
    assert any(
        error["source"] == "state" and "state exploded" in error["message"] for error in run.errors
    )


def test_malformed_llm_output_is_a_planning_error(monkeypatch):
    """A structurally broken answer fails as PlanningAgentError, not pydantic."""

    class BadModel:
        model_name = "bad-model"

        def with_structured_output(self, _schema):
            return self

        def invoke(self, _messages, **_kwargs):
            return {"goal": "reunite", "steps": [{"window": "not-a-window"}]}

    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **_kwargs: BadModel())

    with pytest.raises(PlanningAgentError, match="LLM invocation failed"):
        planning_agent.run(_planning_state())


def test_save_write_failure_is_explicit(tmp_path, monkeypatch):
    """A broken save directory fails the save instead of pretending success."""
    _break_save_dir(tmp_path, monkeypatch)

    with pytest.raises(OSError):
        save_state(_snapshot())


def test_load_state_survives_a_broken_save_directory(tmp_path, monkeypatch):
    """Loading degrades to None, so the sidebar never crashes on a bad path."""
    _break_save_dir(tmp_path, monkeypatch)

    assert load_state() is None
