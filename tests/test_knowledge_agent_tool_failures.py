"""Knowledge Agent degrades gracefully when MCP tools fail.

A failing MCP tool must not abort the Knowledge Agent: it logs a warning and
continues with the structured data it could gather, so the graph can still
reach planning with whatever is authoritative and available.
"""

import pytest

from app.agents import knowledge_agent
from app.agents.planning_agent import PlanningAgentError
from app.data.mock_knowledge import Objective
from app.domain import ClockTime, GameState, Goal, TimeWindow
from app.graph import run_pipeline
from app.rag.retriever import RetrievalResult
from app.state import PlanningState

pytestmark = pytest.mark.usefixtures("fake_planner_model")


def _state() -> PlanningState:
    """Build a PlanningState on the Anju & Kafei goal for tests."""
    gs = GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn")
    return PlanningState(
        game_state=gs,
        goal=Goal(description="Reunite Anju and Kafei"),
    )


def _objective() -> dict:
    return Objective(
        id="anju_talk",
        title="Talk to Anju",
        location="Stockpot Inn",
        window=TimeWindow(start=ClockTime(day=2, hour=8), end=ClockTime(day=2, hour=22)),
        npc_id="anju",
        event_ref="anju_kafei_meeting",
        keywords=["anju", "kafei"],
    ).model_dump(mode="json")


def _fake_retrieve(*_args, **_kwargs):
    return RetrievalResult(query="", evidence=[], engine="test", status="cache_hit")


def test_search_quests_failure_degrades_to_empty_context(monkeypatch):
    """A failing search_quests leaves the agent with no objectives, not a crash."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("search backend down")

    monkeypatch.setattr(knowledge_agent, "search_quests", boom)
    result = knowledge_agent.run(_state())

    assert result["relevant_objectives"] == []
    assert result["knowledge_engine"] == "deterministic"
    assert "[RAG evidence: no matching passage.]" in result["retrieved_context"]


def test_npc_schedule_failure_is_skipped(monkeypatch):
    """A failing get_npc_schedule keeps the objective and continues."""
    quests = [{"quest_id": "q1", "quest_name": "Q", "objectives": [_objective()]}]

    def boom(*_args, **_kwargs):
        raise ValueError("Unknown NPC: anju")

    monkeypatch.setattr(knowledge_agent, "search_quests", lambda *a, **k: quests)
    monkeypatch.setattr(knowledge_agent, "get_npc_schedule", boom)
    monkeypatch.setattr(knowledge_agent, "get_event", lambda *a, **k: {"name": "Party"})
    monkeypatch.setattr(knowledge_agent, "retrieve", _fake_retrieve)

    result = knowledge_agent.run(_state())

    assert len(result["relevant_objectives"]) == 1
    assert "schedule" not in result["retrieved_context"]


def test_event_failure_is_skipped(monkeypatch):
    """A failing get_event keeps the objective and continues."""
    quests = [{"quest_id": "q1", "quest_name": "Q", "objectives": [_objective()]}]

    def boom(*_args, **_kwargs):
        raise ValueError("Unknown event: anju_kafei_meeting")

    monkeypatch.setattr(knowledge_agent, "search_quests", lambda *a, **k: quests)
    monkeypatch.setattr(
        knowledge_agent,
        "get_npc_schedule",
        lambda *a, **k: {"name": "Anju", "schedule": ["Day 2 08:00"]},
    )
    monkeypatch.setattr(knowledge_agent, "get_event", boom)
    monkeypatch.setattr(knowledge_agent, "retrieve", _fake_retrieve)

    result = knowledge_agent.run(_state())

    assert len(result["relevant_objectives"]) == 1
    assert "Anju: schedule" in result["retrieved_context"]


def test_invalid_objective_payload_is_skipped(monkeypatch):
    """A malformed objective payload does not abort the remaining objectives."""
    quests = [
        {
            "quest_id": "q1",
            "quest_name": "Q",
            "objectives": [{"bogus": "payload"}, _objective()],
        }
    ]

    monkeypatch.setattr(knowledge_agent, "search_quests", lambda *a, **k: quests)
    monkeypatch.setattr(
        knowledge_agent,
        "get_npc_schedule",
        lambda *a, **k: {"name": "Anju", "schedule": ["Day 2 08:00"]},
    )
    monkeypatch.setattr(knowledge_agent, "get_event", lambda *a, **k: {"name": "Party"})
    monkeypatch.setattr(knowledge_agent, "retrieve", _fake_retrieve)

    result = knowledge_agent.run(_state())

    assert [o.id for o in result["relevant_objectives"]] == ["anju_talk"]


# ---------------------------------------------------------------------------
# Graph-level integration: a tool failure must not abort the whole pipeline
# ---------------------------------------------------------------------------


def _boom(*_args, **_kwargs):
    raise RuntimeError("tool backend down")


def test_pipeline_all_mcp_tools_failing_fails_explicitly(monkeypatch):
    """With no tool data there is nothing to plan: the run fails with a clear message.

    The Knowledge Agent degrades to zero objectives instead of crashing; the
    Planning Agent then reports the real cause instead of a misleading LLM error.
    """
    monkeypatch.setattr(knowledge_agent, "search_quests", _boom)
    monkeypatch.setattr(knowledge_agent, "get_npc_schedule", _boom)
    monkeypatch.setattr(knowledge_agent, "get_event", _boom)
    monkeypatch.setattr(knowledge_agent, "retrieve", _fake_retrieve)

    with pytest.raises(PlanningAgentError, match="No relevant objectives"):
        run_pipeline(
            GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn"),
            Goal(description="Reunite Anju and Kafei"),
        )


def test_pipeline_continues_when_only_one_tool_fails(monkeypatch):
    """One failing tool still leaves enough context to finish a validated run."""
    monkeypatch.setattr(knowledge_agent, "get_npc_schedule", _boom)
    monkeypatch.setattr(knowledge_agent, "retrieve", _fake_retrieve)

    result = run_pipeline(
        GameState(
            time=ClockTime(day=1, hour=6),
            location="Stockpot Inn",
            inventory=["Hookshot"],
            masks=["Garo's Mask"],
        ),
        Goal(description="Reunite Anju and Kafei before the dawn of the Third Day"),
    )

    assert result.relevant_objectives
    assert result.validation is not None
    assert result.validation.valid
