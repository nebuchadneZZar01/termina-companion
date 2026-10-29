"""Keep test runs hermetic: never hit a real LLM unless a test opts in."""

from __future__ import annotations

import os
import re

import pytest

from app.agents import knowledge_agent, planning_agent
from app.data.mock_knowledge import build_default_knowledge
from app.domain import Plan, PlanStep
from app.rag.models import RetrievalResult

_ENV = (
    "LLM_PROVIDER",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_BASE_URL",
    "LOG_LEVEL",
    "PLANNER",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "PHOENIX_BASE_URL",
    "RAG_ENABLED",
    "RAG_QDRANT_PATH",
    "RAG_EMBEDDING_MODEL",
    "RAG_SIMILARITY_THRESHOLD",
    "RAG_TOP_K",
    "RAG_MAX_PAGES_PER_MISS",
    "RAG_MAX_CHUNKS_PER_SOURCE",
    "RAG_REQUEST_TIMEOUT_SECONDS",
    "RAG_WIKI_BUDGET_SECONDS",
    "RAG_WIKI_FAILURE_THRESHOLD",
    "RAG_WIKI_COOLDOWN_SECONDS",
    "RAG_CACHE_TTL_SECONDS",
)
_KB = build_default_knowledge()
_OBJECTIVES = {objective.id: objective for quest in _KB.quests for objective in quest.objectives}


class _TestPlannerModel:
    """Small test-only model that returns one grounded objective step."""

    model_name = "test-model"

    def with_structured_output(self, _schema):
        return self

    def invoke(self, messages, **_kwargs):
        context = next(
            message.content for message in messages if getattr(message, "type", "") == "human"
        )
        ids = re.findall(r"- \[([^]]+)\]", context)
        objective = next(
            (_OBJECTIVES[objective_id] for objective_id in ids if objective_id in _OBJECTIVES),
            None,
        )
        if objective is None:
            return Plan(goal="test", steps=[])
        return Plan(
            goal="test",
            steps=[
                PlanStep(
                    title=objective.title,
                    objective_ref=objective.id,
                    location=objective.location,
                    window=objective.window,
                )
            ],
        )


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    """Point the save and evaluation stores inside pytest's tmp_path."""
    path = tmp_path / "cache" / "qdrant"
    monkeypatch.setenv("RAG_QDRANT_PATH", str(path))
    return path


@pytest.fixture
def fake_planner_model(monkeypatch):
    """Inject a deterministic model for graph tests without a network call."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **_kwargs: _TestPlannerModel())


@pytest.fixture(autouse=True)
def _hermetic_rag(monkeypatch):
    """Keep graph tests independent from Qdrant, FastEmbed and the live wiki."""

    def offline_retrieve(query: str, **_kwargs) -> RetrievalResult:
        return RetrievalResult(
            query=query,
            engine="test-offline",
            status="wiki_miss",
        )

    monkeypatch.setattr(knowledge_agent, "retrieve", offline_retrieve)


@pytest.fixture(autouse=True)
def _clear_llm_env():
    """Clear LLM/RAG environment variables and restore them after each test.

    args:
        (none)

    returns:
        generator: a fixture that restores the original environment after each
        test.
    """
    saved = {k: os.environ.get(k) for k in _ENV}
    for key in _ENV:
        os.environ.pop(key, None)
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
