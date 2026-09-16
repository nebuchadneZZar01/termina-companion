import logging

from app.agents import planning_agent, state_agent
from app.data.mock_knowledge import Objective
from app.domain import ClockTime, GameState, Goal
from app.mcp.tools import search_quests
from app.state import PlanningState


def _relevant(description: str) -> list[Objective]:
    """Objectives matched by the MCP search tool for a goal text."""
    groups = search_quests(description)
    return [Objective.model_validate(obj) for group in groups for obj in group["objectives"]]


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


def test_planning_agent_logs_llm_fallback(caplog, monkeypatch):
    """The Planning Agent logs when the LLM path fails and it falls back."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda: _RaisingModel())
    state = PlanningState(
        game_state=GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn"),
        goal=Goal(description="Reunite Anju and Kafei"),
    )
    with caplog.at_level(logging.WARNING, logger="app.agents.planning_agent"):
        planning_agent.run(state)
    assert any("falling back to rule-based" in r.message for r in caplog.records)


def test_planning_agent_rule_based_still_emits_plan(caplog, monkeypatch):
    """The rule-based Planning Agent still emits a plan and logs itself."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda: None)
    gs = GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn")
    state = PlanningState(
        game_state=gs,
        goal=Goal(description="Reunite Anju and Kafei"),
        relevant_objectives=_relevant("kafei letter"),
    )
    with caplog.at_level(logging.INFO, logger="app.agents.planning_agent"):
        result = planning_agent.run(state)
    assert result["plan"] is not None and result["plan"].steps
    assert any("Planning Agent [rule-based]" in r.message for r in caplog.records)
