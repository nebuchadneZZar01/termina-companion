import logging

from app.agents import planning_agent, state_agent
from app.domain import ClockTime, GameState, Goal
from app.state import PlanningState


def test_state_agent_logs_rule_based_path(caplog):
    state = PlanningState(
        game_state=GameState(time=ClockTime(day=2, hour=8), location="stockpot inn"),
        goal=Goal(description="Reunite Anju and Kafei"),
    )
    with caplog.at_level(logging.INFO, logger="app.agents.state_agent"):
        state_agent.run(state)
    assert any("State Agent [rule-based]" in r.message for r in caplog.records)


class _RaisingModel:
    def with_structured_output(self, schema):
        def _invoke(*args, **kwargs):
            raise RuntimeError("boom")

        return _invoke


def test_planning_agent_logs_llm_fallback(caplog, monkeypatch):
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda: _RaisingModel())
    state = PlanningState(
        game_state=GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn"),
        goal=Goal(description="Reunite Anju and Kafei"),
    )
    with caplog.at_level(logging.WARNING, logger="app.agents.planning_agent"):
        planning_agent.run(state)
    assert any("falling back to rule-based" in r.message for r in caplog.records)


def test_planning_agent_rule_based_still_emits_plan(caplog, monkeypatch):
    from app.data.mock_knowledge import build_default_knowledge

    monkeypatch.setattr(planning_agent, "get_chat_model", lambda: None)
    gs = GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn")
    state = PlanningState(
        game_state=gs,
        goal=Goal(description="Reunite Anju and Kafei"),
        relevant_objectives=build_default_knowledge().retrieve(
            gs, Goal(description="kafei letter")
        ),
    )
    with caplog.at_level(logging.INFO, logger="app.agents.planning_agent"):
        result = planning_agent.run(state)
    assert result["plan"] is not None and result["plan"].steps
    assert any("Planning Agent [rule-based]" in r.message for r in caplog.records)
