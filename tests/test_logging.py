import logging

import pytest

from app.agents import planning_agent, state_agent
from app.agents.planning_agent import PlanningAgentError
from app.data.mock_knowledge import build_default_knowledge
from app.domain import ClockTime, GameState, Goal
from app.state import PlanningState


def _kafei_objectives():
    """Objectives matched for the Anju & Kafei goal, for prompt-only tests."""
    kb = build_default_knowledge()
    return [obj for quest in kb.quests for obj in quest.objectives if obj.id.startswith("ak_")]


def test_state_agent_logs_rule_based_path(caplog):
    """The State Agent logs that it used the rule-based path."""
    state = PlanningState(
        game_state=GameState(time=ClockTime(day=2, hour=8), location="stockpot inn"),
        goal=Goal(description="Reunite Anju and Kafei"),
    )
    with caplog.at_level(logging.INFO, logger="app.agents.state_agent"):
        state_agent.run(state)
    assert any("State Agent [rule-based]" in r.message for r in caplog.records)


class _RaisingModel:
    def with_structured_output(self, schema):
        """Return an invoke callable that always raises."""

        def _invoke(*args, **kwargs):
            raise RuntimeError("boom")

        return _invoke


def test_planning_agent_logs_llm_failure(caplog, monkeypatch):
    """The Planning Agent logs an LLM failure and does not fall back."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda: _RaisingModel())
    state = PlanningState(
        game_state=GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn"),
        goal=Goal(description="Reunite Anju and Kafei"),
        relevant_objectives=_kafei_objectives(),
    )
    with caplog.at_level(logging.ERROR, logger="app.agents.planning_agent"):
        with pytest.raises(PlanningAgentError, match="LLM invocation failed"):
            planning_agent.run(state)
    assert any("LLM invocation failed" in r.message for r in caplog.records)
