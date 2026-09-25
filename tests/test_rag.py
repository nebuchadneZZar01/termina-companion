"""Hermetic tests for adaptive cache-aside wiki RAG."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.agents import knowledge_agent
from app.domain import ClockTime, GameState, Goal
from app.rag.chunking import chunk_document
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.models import Document, RetrievalResult, SourceMetadata
from app.rag.retriever import AdaptiveRetriever, RAGSettings
from app.rag.store import InMemoryVectorStore
from app.rag.wiki import WikiError, WikiPageReference
from app.state import PlanningState


class FakeWiki:
    """In-memory wiki source with call counters and optional failure."""

    def __init__(self, documents: list[Document] | None = None) -> None:
        self.documents = documents or []
        self.search_calls: list[tuple[str, int, tuple[str, ...] | None]] = []
        self.fetch_calls = 0
        self.fail_search = False
        self.fail_fetch = False

    def search(
        self,
        query: str,
        limit: int = 3,
        terms: list[str] | tuple[str, ...] | None = None,
    ) -> list[WikiPageReference]:
        self.search_calls.append((query, limit, tuple(terms) if terms else None))
        if self.fail_search:
            raise WikiError("wiki offline")
        return [
            WikiPageReference(
                page_id=document.metadata.source_page_id or index,
                title=document.title,
            )
            for index, document in enumerate(self.documents, start=1)
        ][:limit]

    def fetch_pages(self, references: list[WikiPageReference]) -> list[Document]:
        self.fetch_calls += 1
        if self.fail_fetch:
            raise WikiError("wiki fetch offline")
        by_id = {document.metadata.source_page_id: document for document in self.documents}
        return [by_id[reference.page_id] for reference in references if reference.page_id in by_id]


def _document(
    *,
    page_id: int = 1,
    revision: int = 10,
    title: str = "Anju's Anguish",
    content: str = "# Anju's Anguish\n\nKafei and Anju reunite before dawn.",
) -> Document:
    metadata = SourceMetadata(
        id=f"wiki:{page_id}",
        title=title,
        source_type="wiki",
        source_url=f"https://zeldawiki.wiki/w/index.php?oldid={revision}",
        canonical_url="https://zeldawiki.wiki/wiki/Anju's_Anguish",
        source_page_id=page_id,
        source_revision_id=revision,
        source_revision_timestamp="2026-01-02T03:04:05Z",
        retrieved_at=datetime.now(UTC).isoformat(),
        language="en",
        license_note="GNU Free Documentation License 1.3",
        license_url="https://zeldawiki.wiki/wiki/Zelda_Wiki:GNU_Free_Documentation_License",
    )
    return Document(id=metadata.id, title=title, content=content, metadata=metadata)


def _settings(tmp_path: Path, **overrides) -> RAGSettings:
    values = {
        "qdrant_path": tmp_path / "qdrant",
        "similarity_threshold": 0.1,
        "top_k": 4,
        "max_pages_per_miss": 3,
        "request_timeout_seconds": 2,
        "chunk_max_chars": 120,
        "chunk_overlap": 20,
    }
    values.update(overrides)
    return RAGSettings(**values)


def _retriever(tmp_path: Path, wiki: FakeWiki, **overrides) -> AdaptiveRetriever:
    return AdaptiveRetriever(
        InMemoryVectorStore(),
        wiki,
        HashEmbeddingProvider(),
        _settings(tmp_path, **overrides),
        lock_path=tmp_path / "wiki.lock",
    )


def _state() -> PlanningState:
    return PlanningState(
        game_state=GameState(
            time=ClockTime(day=2, hour=8),
            location="Stockpot Inn",
            inventory=["Kafei's Letter"],
        ),
        goal=Goal(description="Reunite Anju and Kafei before dawn"),
    )


def test_chunking_preserves_heading_revision_and_provenance():
    document = _document(content="# First section\n\nAlpha text.\n\n## Second\n\nBeta text.")
    chunks = chunk_document(document, max_chars=80, overlap=10)

    assert len(chunks) == 2
    assert [chunk.section for chunk in chunks] == ["First section", "Second"]
    assert all(chunk.metadata.source_revision_id == 10 for chunk in chunks)
    assert all(chunk.metadata.license_note.startswith("GNU") for chunk in chunks)
    assert all(chunk.document_id == "wiki:1" for chunk in chunks)


def test_cold_miss_ingests_wiki_then_returns_second_vector_result(tmp_path):
    wiki = FakeWiki([_document()])
    retriever = _retriever(tmp_path, wiki)

    result = retriever.retrieve("Anju Kafei", search_terms=["Anju", "Kafei"])

    assert result.status == "wiki_ingested"
    assert result.evidence
    assert result.evidence[0].chunk.metadata.source_page_id == 1
    assert result.ingested_pages == ["Anju's Anguish"]
    assert wiki.fetch_calls == 1
    assert wiki.search_calls[0][2] == ("Anju", "Kafei")


def test_warm_cache_hit_does_not_call_wiki(tmp_path):
    wiki = FakeWiki([_document()])
    retriever = _retriever(tmp_path, wiki)
    first = retriever.retrieve("Anju Kafei")
    assert first.status == "wiki_ingested"

    wiki.search_calls.clear()
    wiki.fetch_calls = 0
    wiki.fail_search = True
    wiki.fail_fetch = True
    second = retriever.retrieve("Anju Kafei")

    assert second.status == "cache_hit"
    assert second.evidence
    assert wiki.search_calls == []
    assert wiki.fetch_calls == 0


def test_fetched_text_must_pass_vector_retrieval(tmp_path):
    wiki = FakeWiki([_document(content="Completely unrelated raw wiki text.")])
    retriever = _retriever(tmp_path, wiki, similarity_threshold=0.99)

    result = retriever.retrieve("Anju Kafei")

    assert result.status == "wiki_miss"
    assert result.evidence == []
    assert result.ingested_pages == ["Anju's Anguish"]


def test_wiki_failure_degrades_to_unavailable(tmp_path):
    wiki = FakeWiki([_document()])
    wiki.fail_search = True
    retriever = _retriever(tmp_path, wiki)

    result = retriever.retrieve("Anju Kafei")

    assert result.status == "unavailable"
    assert result.engine == "unavailable"
    assert "wiki offline" in result.warning
    assert result.evidence == []


def test_retrieve_never_raises_when_default_builder_fails(monkeypatch):
    from app.rag import retriever as retriever_module

    def broken_builder():
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(retriever_module, "build_default_retriever", broken_builder)
    result = retriever_module.retrieve("Anju Kafei")

    assert result.status == "unavailable"
    assert "model unavailable" in result.warning


def test_knowledge_agent_keeps_mcp_authoritative_and_reports_status(monkeypatch):
    evidence = chunk_document(_document())[0]
    fake_result = RetrievalResult(
        query="Anju Kafei",
        evidence=[{"chunk": evidence, "score": 0.91}],
        engine="qdrant-fastembed",
        status="cache_hit",
    )
    monkeypatch.setattr(knowledge_agent, "retrieve", lambda *_args, **_kwargs: fake_result)

    result = knowledge_agent.run(_state())

    assert result["knowledge_engine"] == "rule-based"
    assert result["retrieval_status"] == "cache_hit"
    assert "[ak_talk_to_anju]" in result["retrieved_context"]
    assert "Supplemental RAG evidence" in result["retrieved_context"]
    assert "oldid=10" in result["retrieved_context"]
    assert result["retrieval_ingested_pages"] == []


def test_knowledge_agent_search_terms_include_structured_entities(monkeypatch):
    captured: dict[str, object] = {}

    def capture(query, **kwargs):
        captured.update(kwargs)
        return RetrievalResult(query=query, engine="fake", status="wiki_miss")

    monkeypatch.setattr(knowledge_agent, "retrieve", capture)
    knowledge_agent.run(_state())

    terms = captured["search_terms"]
    assert "Anju" in terms
    assert "Kafei" in terms
    assert "Stockpot Inn" in terms


def test_knowledge_agent_unexpected_failure_keeps_structured_context(monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("index offline")

    monkeypatch.setattr(knowledge_agent, "retrieve", broken)
    result = knowledge_agent.run(_state())

    assert result["retrieval_status"] == "unavailable"
    assert result["retrieval_engine"] == "unavailable"
    assert result["retrieval_warning"] == "index offline"
    assert "[ak_talk_to_anju]" in result["retrieved_context"]


def test_empty_query_is_a_miss_without_wiki_call(tmp_path):
    wiki = FakeWiki([_document()])
    retriever = _retriever(tmp_path, wiki)

    result = retriever.retrieve("")

    assert result.status == "wiki_miss"
    assert wiki.search_calls == []


def test_ingestion_is_bounded_by_page_setting(tmp_path):
    documents = [_document(page_id=index, title=f"Page {index}") for index in range(1, 6)]
    wiki = FakeWiki(documents)
    retriever = _retriever(tmp_path, wiki, max_pages_per_miss=2)

    result = retriever.retrieve("Anju Kafei")

    assert len(result.ingested_pages) == 2
    assert wiki.search_calls[0][1] == 2
