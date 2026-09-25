"""Tests for the local Clock Town RAG corpus and retrieval layer."""

from __future__ import annotations

from datetime import date

import pytest

from app.agents import knowledge_agent
from app.domain import ClockTime, GameState, Goal
from app.graph import run_pipeline
from app.rag.chunking import chunk_documents
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.loader import load_documents
from app.rag.retriever import (
    HybridRetriever,
    KeywordRetriever,
    VectorRetriever,
    retrieve,
)
from app.state import PlanningState


def _state() -> PlanningState:
    """Build a small Anju & Kafei state for Knowledge Agent tests."""
    return PlanningState(
        game_state=GameState(
            time=ClockTime(day=2, hour=8),
            location="Stockpot Inn",
            inventory=["Kafei's Letter"],
        ),
        goal=Goal(description="Reunite Anju and Kafei before dawn"),
    )


def test_curated_corpus_loads_with_provenance():
    """The local corpus contains the researched Clock Town slice and sources."""
    documents = load_documents()

    assert len(documents) == 9
    assert {document.id for document in documents} >= {
        "clock_town",
        "anju_kafei",
        "stock_pot_inn",
        "post_office_and_postman",
        "curiosity_shop_and_laundry_pool",
        "bombers_secret_society",
    }
    assert all(document.metadata.source_url for document in documents)
    assert all(date.fromisoformat(document.metadata.retrieved_at) for document in documents)
    assert all("it" in document.metadata.language for document in documents)


def test_chunking_preserves_source_and_respects_limit():
    """Chunks retain document metadata and stay below the requested size."""
    documents = load_documents()
    chunks = chunk_documents(documents, max_chars=700, overlap=80)

    assert chunks
    assert all(len(chunk.text) <= 700 for chunk in chunks)
    assert len({chunk.document_id for chunk in chunks}) == len(documents)
    for chunk in chunks:
        source = next(document for document in documents if document.id == chunk.document_id)
        assert chunk.metadata.source_url == source.metadata.source_url
        assert chunk.title == source.title


def test_keyword_retrieval_finds_quest_in_english():
    """English goals return relevant Anju/Kafei evidence with provenance."""
    result = retrieve("Reunite Anju and Kafei before dawn", top_k=4)

    assert result.engine == "keyword"
    assert result.evidence
    assert "anju_kafei" in {item.chunk.document_id for item in result.evidence}
    assert all(item.chunk.metadata.source_url for item in result.evidence)


def test_keyword_retrieval_supports_italian_aliases():
    """Italian aliases retrieve the same researched quest material."""
    result = retrieve("riunire Anju e Kafei prima dell'alba", top_k=4)

    assert result.evidence
    assert "anju_kafei" in {item.chunk.document_id for item in result.evidence}
    assert "corpus_terms_en_it" in {item.chunk.document_id for item in result.evidence}


def test_keyword_retrieval_is_empty_for_unrelated_query():
    """A query with no indexed terms returns no fabricated evidence."""
    result = KeywordRetriever(chunk_documents(load_documents())).retrieve(
        "completely unrelated quantum paperwork", top_k=4
    )

    assert result.evidence == []


def test_hash_embeddings_use_independent_sign_material():
    """The offline baseline must not force every collision to be positive."""
    provider = HashEmbeddingProvider()
    left = provider.embed_query("token25")
    right = provider.embed_query("token92")

    assert sum(a * b for a, b in zip(left, right, strict=True)) < 0


def test_vector_retrieval_uses_local_embeddings():
    """The vector adapter ranks a matching chunk without an external service."""
    chunks = chunk_documents(load_documents(), max_chars=900, overlap=100)
    result = VectorRetriever(chunks, HashEmbeddingProvider()).retrieve(
        "Kafei letter postman", top_k=4
    )

    assert result.engine == "vector-local"
    assert result.evidence
    assert "post_office_and_postman" in {item.chunk.document_id for item in result.evidence}


def test_hybrid_retrieval_combines_local_indexes():
    """Hybrid retrieval returns bounded evidence and a stable engine label."""
    chunks = chunk_documents(load_documents(), max_chars=900, overlap=100)
    result = HybridRetriever(chunks, HashEmbeddingProvider()).retrieve("Bombers Notebook", top_k=3)

    assert result.engine == "hybrid"
    assert 0 < len(result.evidence) <= 3
    assert "bombers_secret_society" in {item.chunk.document_id for item in result.evidence}


class _BrokenEmbeddingProvider:
    """Test provider that cannot build a vector index."""

    name = "broken"

    def embed_documents(self, _texts):
        """Fail while embedding the corpus."""
        raise RuntimeError("embedding backend down")

    def embed_query(self, _text):
        """Fail while embedding a query."""
        raise RuntimeError("embedding backend down")


def test_hybrid_retriever_reports_vector_fallback():
    """A failed vector index degrades to labelled keyword-only evidence."""
    chunks = chunk_documents(load_documents(), max_chars=900, overlap=100)
    result = HybridRetriever(chunks, _BrokenEmbeddingProvider()).retrieve(
        "Bombers Notebook", top_k=3
    )

    assert result.engine == "keyword-fallback"
    assert "embedding backend down" in result.warning
    assert result.evidence


def test_knowledge_agent_appends_rag_without_replacing_mcp_context(monkeypatch):
    """Knowledge output keeps structured objectives and adds source evidence."""
    monkeypatch.setenv("RAG_ENABLED", "1")
    result = knowledge_agent.run(_state())

    assert result["knowledge_engine"] == "rule-based"
    assert result["retrieval_engine"] == "keyword"
    assert result["retrieved_evidence"]
    assert "[ak_talk_to_anju]" in result["retrieved_context"]
    assert "Supplemental RAG evidence" in result["retrieved_context"]
    assert "Source: https://" in result["retrieved_context"]
    rag_section = result["retrieved_context"].split("Supplemental RAG evidence", 1)[1]
    assert "RAG evidence " in rag_section
    assert " - [" not in rag_section


def test_knowledge_agent_survives_unexpected_retrieval_failure(monkeypatch):
    """An unexpected RAG failure is degraded, not propagated into planning."""
    monkeypatch.setattr(
        knowledge_agent,
        "retrieve",
        lambda _query, top_k=4: (_ for _ in ()).throw(RuntimeError("index offline")),
    )

    result = knowledge_agent.run(_state())

    assert result["retrieval_engine"] == "unavailable"
    assert result["retrieval_warning"] == "index offline"
    assert "[ak_talk_to_anju]" in result["retrieved_context"]
    assert result["relevant_objectives"]


def test_pipeline_continues_when_retrieval_fails(monkeypatch, fake_planner_model):
    """A retrieval outage degrades evidence without aborting the graph."""
    monkeypatch.setattr(
        knowledge_agent,
        "retrieve",
        lambda _query, top_k=4: (_ for _ in ()).throw(RuntimeError("index offline")),
    )

    result = run_pipeline(_state().game_state, _state().goal)

    assert result.retrieval_engine == "unavailable"
    assert result.retrieval_warning == "index offline"
    assert result.plan and result.plan.steps
    assert result.validation and result.validation.valid


def test_retrieval_can_be_disabled(monkeypatch):
    """RAG is optional for local debugging and can be disabled by environment."""
    monkeypatch.setenv("RAG_ENABLED", "0")
    result = retrieve("Anju and Kafei", top_k=4)

    assert result.engine == "disabled"
    assert result.evidence == []


def test_invalid_chunk_sizes_are_rejected():
    """Chunking validates its overlap and size contract."""
    documents = load_documents()

    with pytest.raises(ValueError, match="max_chars"):
        chunk_documents(documents, max_chars=0)
    with pytest.raises(ValueError, match="overlap"):
        chunk_documents(documents, max_chars=100, overlap=100)
