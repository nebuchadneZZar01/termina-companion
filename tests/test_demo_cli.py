"""The headless demo's offline mode: deterministic engine, no wiki, no LLM."""

from __future__ import annotations

import os

import pytest

from app.__main__ import main


@pytest.fixture
def seen_rag_flag(monkeypatch):
    """Capture the RAG flag seen by the knowledge agent during the run."""
    from app.agents import knowledge_agent

    offline = knowledge_agent.retrieve
    seen: dict[str, str | None] = {}

    def spy(query, **kwargs):
        seen["flag"] = os.environ.get("RAG_ENABLED")
        return offline(query, **kwargs)

    monkeypatch.setattr(knowledge_agent, "retrieve", spy)
    return seen


def test_offline_demo_runs_without_an_llm(monkeypatch, capsys, seen_rag_flag):
    """--deterministic --no-rag completes with no provider and no network."""
    for key in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    before = os.environ.get("RAG_ENABLED")

    code = main(["--deterministic", "--no-rag"])

    out = capsys.readouterr().out
    assert code == 0
    assert "Planning failed" not in out
    assert "Planner engine: deterministic" in out
    assert "--- Plan" in out
    assert "Outcome: feasible plan." in out
    assert seen_rag_flag["flag"] == "0"
    assert os.environ.get("RAG_ENABLED") == before


def test_offline_demo_keeps_a_healthy_plan(monkeypatch, capsys):
    """The offline run is a real plan, not an empty unreachable verdict."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("RAG_ENABLED", "1")

    code = main(["--deterministic", "--no-rag"])

    out = capsys.readouterr().out
    assert code == 0
    assert "Valid!" in out
    assert "goal not reachable" not in out
    assert os.environ["RAG_ENABLED"] == "1"
