"""Phase 8 memory: store ranking, nodes and graph integration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agents import memory_agent, planning_agent
from app.domain import ClockTime, GameState, Goal
from app.graph import run_pipeline
from app.memory.models import Episode, PlayerPreferences
from app.memory.store import InMemoryMemoryStore, get_memory_store
from app.state import PlanningState


@pytest.fixture
def store(monkeypatch):
    import app.agents.memory_agent as memory_agent_module
    import app.graph as graph_module
    import app.memory.store as store_module

    fresh = InMemoryMemoryStore()
    monkeypatch.setattr(store_module, "get_memory_store", lambda: fresh)
    monkeypatch.setattr(memory_agent_module, "get_memory_store", lambda: fresh)
    monkeypatch.setattr(graph_module, "get_memory_store", lambda: fresh)
    fresh.clear()
    return fresh


def _episode(goal: str, location: str = "", days_ago: int = 0) -> Episode:
    return Episode(
        id=f"ep-{goal[:8]}-{location[:4]}",
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        goal=goal,
        location=location,
        time=ClockTime(day=2, hour=8),
        plan_summary=f"plan for {goal}",
        objective_refs=["ak_talk_to_anju"],
        valid=True,
    )


def test_search_prefers_goal_and_location_match(store):
    store.save_episode(_episode("Defend ranch from aliens", "Ranch House"))
    store.save_episode(_episode("Reunite Anju and Kafei", "Stockpot Inn"))
    hits = store.search_episodes("Reunite Anju and Kafei", "Stockpot Inn")
    assert hits[0].goal == "Reunite Anju and Kafei"


def test_search_returns_empty_when_no_match(store):
    """An unrelated query never injects an unrelated past plan."""
    store.save_episode(_episode("old goal", days_ago=2))
    store.save_episode(_episode("newer goal", days_ago=0))
    assert store.search_episodes("something unrelated xyz", "Nowhere") == []


def test_search_respects_limit(store):
    for i in range(5):
        store.save_episode(_episode(f"goal number {i}"))
    assert len(store.search_episodes("goal", limit=3)) == 3


def test_preferences_roundtrip(store):
    prefs = PlayerPreferences(playstyle="completionist", avoid=["night-events"])
    store.save_preferences(prefs)
    assert store.get_preferences().playstyle == "completionist"


def test_retrieve_run_loads_memory(store):
    store.save_episode(_episode("Reunite Anju and Kafei", "Stockpot Inn"))
    store.save_preferences(PlayerPreferences(playstyle="speedrun"))
    state = PlanningState(
        game_state=GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn"),
        goal=Goal(description="Reunite Anju and Kafei"),
    )
    out = memory_agent.retrieve_run(state)
    assert out["memory_engine"] == "in-memory"
    assert len(out["relevant_episodes"]) == 1
    assert out["preferences"].playstyle == "speedrun"


def test_store_run_is_noop_without_plan(store):
    state = PlanningState(
        game_state=GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn"),
        goal=Goal(description="g"),
    )
    assert memory_agent.store_run(state)["memory_engine"] == "in-memory"
    assert store.recent_episodes() == []


def test_graph_second_run_sees_first_episode(store, fake_planner_model):
    gs = GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn")
    goal = Goal(description="Reunite Anju and Kafei")
    first = run_pipeline(gs, goal)
    assert first.plan is not None
    assert len(store.recent_episodes()) == 1
    second = run_pipeline(gs, goal)
    assert len(second.relevant_episodes) >= 1
    assert second.memory_engine == "in-memory"


def test_planning_prompt_includes_preferences(monkeypatch, store):
    from app.domain import Plan, PlanStep, TimeWindow

    class _CaptureModel:
        _invoked: list = []
        model_name = "capture-model"

        def with_structured_output(self, _schema):
            return self

        def invoke(self, msgs):
            _CaptureModel._invoked = msgs
            w = TimeWindow(start=ClockTime(day=2, hour=9), end=ClockTime(day=2, hour=10))
            return Plan(
                goal="x",
                steps=[
                    PlanStep(
                        title="s",
                        objective_ref="ak_talk_to_anju",
                        location="Stockpot Inn",
                        window=w,
                    )
                ],
            )

    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **kw: _CaptureModel())
    store.save_preferences(PlayerPreferences(playstyle="completionista"))
    gs = GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn")
    state = PlanningState(
        game_state=gs,
        goal=Goal(description="Reunite Anju and Kafei"),
        state_summary="Stockpot Inn at Day 2",
        retrieved_context="- [ak_talk_to_anju] x",
        relevant_episodes=[],
        preferences=PlayerPreferences(playstyle="completionista"),
    )
    planning_agent.run(state)
    human = next(m.content for m in _CaptureModel._invoked if m.type == "human")
    assert "completionista" in human


def test_clean_memory_singleton():
    get_memory_store().clear()
    assert get_memory_store().recent_episodes() == []
