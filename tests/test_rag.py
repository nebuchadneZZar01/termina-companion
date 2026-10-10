"""Hermetic tests for adaptive cache-aside wiki RAG."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.agents import knowledge_agent
from app.domain import ClockTime, GameState, Goal
from app.rag.chunking import chunk_document
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.models import (
    Chunk,
    Document,
    IndexedSource,
    RetrievalResult,
    RetrievedChunk,
    SourceMetadata,
)
from app.rag.retriever import AdaptiveRetriever, RAGSettings, _select_evidence
from app.rag.store import InMemoryVectorStore
from app.rag.wiki import WikiError, WikiPageReference, WikiUnavailableError
from app.state import PlanningState


class FakeWiki:
    """In-memory wiki source with call counters and optional failure."""

    def __init__(self, documents: list[Document] | None = None) -> None:
        self.documents = documents or []
        self.search_calls: list[tuple[str, int, tuple[str, ...] | None]] = []
        self.fetch_calls = 0
        self.revision_calls = 0
        self.fail_search = False
        self.fail_fetch = False
        self.fail_revisions = False
        # Failures default to an unreachable wiki; tests can override the
        # exception to model a reachable wiki that returns an API error.
        self.search_error: Exception = WikiUnavailableError("wiki offline")
        self.fetch_error: Exception = WikiUnavailableError("wiki fetch offline")
        self.revisions_error: Exception = WikiUnavailableError("wiki revisions offline")

    def search(
        self,
        query: str,
        limit: int = 3,
        terms: list[str] | tuple[str, ...] | None = None,
        deadline: float | None = None,
    ) -> list[WikiPageReference]:
        self.search_calls.append((query, limit, tuple(terms) if terms else None))
        if self.fail_search:
            raise self.search_error
        return [
            WikiPageReference(
                page_id=document.metadata.source_page_id or index,
                title=document.title,
            )
            for index, document in enumerate(self.documents, start=1)
        ][:limit]

    def fetch_pages(
        self, references: list[WikiPageReference], deadline: float | None = None
    ) -> list[Document]:
        self.fetch_calls += 1
        if self.fail_fetch:
            raise self.fetch_error
        by_id = {document.metadata.source_page_id: document for document in self.documents}
        return [by_id[reference.page_id] for reference in references if reference.page_id in by_id]

    def current_revisions(
        self, page_ids: list[int], deadline: float | None = None
    ) -> dict[int, int]:
        self.revision_calls += 1
        if self.fail_revisions:
            raise self.revisions_error
        wanted = set(page_ids)
        return {
            document.metadata.source_page_id: document.metadata.source_revision_id
            for document in self.documents
            if document.metadata.source_page_id in wanted
            and document.metadata.source_revision_id is not None
        }


def _document(
    *,
    page_id: int = 1,
    revision: int = 10,
    title: str = "Anju's Anguish",
    content: str = "# Anju's Anguish\n\nKafei and Anju reunite before dawn.",
    retrieved_at: str | None = None,
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
        retrieved_at=retrieved_at or datetime.now(UTC).isoformat(),
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
    assert [source.title for source in result.indexed_sources] == ["Anju's Anguish"]
    assert result.indexed_sources[0].source_page_id == 1
    assert result.indexed_sources[0].source_revision_id == 10
    assert result.indexed_sources[0].source_url.endswith("oldid=10")
    assert result.indexed_sources[0].canonical_url.endswith("Anju's_Anguish")
    assert result.indexed_sources[0].license_note.startswith("GNU")
    assert result.indexed_sources[0].retrieved_at
    assert wiki.fetch_calls == 1
    assert wiki.search_calls[0][2] == ("Anju", "Kafei")


def test_cold_miss_emits_ordered_progress_phases(tmp_path):
    wiki = FakeWiki([_document()])
    retriever = _retriever(tmp_path, wiki)
    seen: list[dict] = []

    retriever.retrieve("Anju Kafei", search_terms=["Anju", "Kafei"], on_progress=seen.append)

    assert [event["phase"] for event in seen] == [
        "cache_search",
        "wiki_search",
        "wiki_refs",
        "wiki_fetch",
        "wiki_indexed",
        "reretrieve",
    ]
    assert seen[2]["n"] == 1
    assert seen[3]["titles"] == ["Anju's Anguish"]


def test_warm_cache_hit_emits_cache_hit_progress(tmp_path):
    wiki = FakeWiki([_document()])
    retriever = _retriever(tmp_path, wiki)
    retriever.retrieve("Anju Kafei", search_terms=["Anju", "Kafei"])
    seen: list[dict] = []

    result = retriever.retrieve(
        "Anju Kafei", search_terms=["Anju", "Kafei"], on_progress=seen.append
    )

    assert result.status == "cache_hit"
    assert [event["phase"] for event in seen] == ["cache_search", "cache_hit"]


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
    assert second.wiki_unreachable is False
    assert [source.title for source in second.indexed_sources] == ["Anju's Anguish"]
    assert wiki.search_calls == []
    assert wiki.fetch_calls == 0


def test_fetched_text_must_pass_vector_retrieval(tmp_path):
    wiki = FakeWiki([_document(content="Completely unrelated raw wiki text.")])
    retriever = _retriever(tmp_path, wiki, similarity_threshold=0.99)

    result = retriever.retrieve("Anju Kafei")

    assert result.status == "wiki_miss"
    assert result.evidence == []
    assert result.ingested_pages == ["Anju's Anguish"]
    assert [source.title for source in result.indexed_sources] == ["Anju's Anguish"]


def test_manifest_keeps_every_page_indexed_during_miss(tmp_path):
    documents = [
        _document(page_id=1, title="Anju's Anguish", content="Kafei and Anju reunite."),
        _document(page_id=2, title="Unrelated Page", content="Completely unrelated text."),
    ]
    retriever = _retriever(tmp_path, FakeWiki(documents), similarity_threshold=0.99)

    result = retriever.retrieve("Anju Kafei")

    assert result.status == "wiki_miss"
    assert result.evidence == []
    assert result.ingested_pages == ["Anju's Anguish", "Unrelated Page"]
    assert [source.title for source in result.indexed_sources] == [
        "Anju's Anguish",
        "Unrelated Page",
    ]
    assert all(isinstance(source, IndexedSource) for source in result.indexed_sources)


def test_wiki_search_failure_degrades_to_miss(tmp_path):
    wiki = FakeWiki([_document()])
    wiki.fail_search = True
    retriever = _retriever(tmp_path, wiki)

    result = retriever.retrieve("Anju Kafei")

    assert result.status == "wiki_miss"
    assert result.engine == "qdrant-fastembed"
    assert result.wiki_unreachable is True
    assert "wiki offline" in result.warning
    assert result.evidence == []


def test_wiki_fetch_failure_degrades_to_miss(tmp_path):
    wiki = FakeWiki([_document()])
    wiki.fail_fetch = True
    retriever = _retriever(tmp_path, wiki)

    result = retriever.retrieve("Anju Kafei")

    assert result.status == "wiki_miss"
    assert result.engine == "qdrant-fastembed"
    assert result.wiki_unreachable is True
    assert "wiki fetch offline" in result.warning
    assert result.evidence == []


def test_wiki_api_error_is_reachable_not_unreachable(tmp_path):
    wiki = FakeWiki([_document()])
    wiki.fail_search = True
    wiki.search_error = WikiError("invalid page")
    retriever = _retriever(tmp_path, wiki)

    result = retriever.retrieve("Anju Kafei")

    assert result.status == "wiki_miss"
    assert result.wiki_unreachable is False
    assert "invalid page" in result.warning


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
        indexed_sources=[IndexedSource.from_metadata(evidence.metadata)],
    )
    monkeypatch.setattr(knowledge_agent, "retrieve", lambda *_args, **_kwargs: fake_result)

    result = knowledge_agent.run(_state())

    assert result["knowledge_engine"] == "rule-based"
    assert result["retrieval_status"] == "cache_hit"
    assert result["retrieval_wiki_unreachable"] is False
    assert "[ak_talk_to_anju]" in result["retrieved_context"]
    assert "Supplemental RAG evidence" in result["retrieved_context"]
    assert "oldid=10" in result["retrieved_context"]
    assert result["retrieval_ingested_pages"] == []
    assert len(result["retrieval_indexed_sources"]) == 1
    assert result["retrieval_indexed_sources"][0].source_page_id == 1


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


def test_knowledge_agent_reports_unreachable_wiki(monkeypatch):
    fake_result = RetrievalResult(
        query="Anju Kafei",
        engine="qdrant-fastembed",
        status="wiki_miss",
        warning="Wiki source unreachable: wiki offline",
        wiki_unreachable=True,
    )
    monkeypatch.setattr(knowledge_agent, "retrieve", lambda *_args, **_kwargs: fake_result)

    result = knowledge_agent.run(_state())

    assert result["retrieval_wiki_unreachable"] is True
    assert "wiki unreachable" in result["retrieved_context"]
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


def _raw_chunk(document_id: str, ordinal: int, text: str) -> Chunk:
    metadata = SourceMetadata(id=document_id, title=document_id)
    return Chunk(
        id=f"{document_id}::chunk-{ordinal:03d}",
        document_id=document_id,
        title=document_id,
        text=text,
        ordinal=ordinal,
        metadata=metadata,
    )


def test_select_evidence_caps_chunks_per_source():
    items = [
        RetrievedChunk(
            chunk=_raw_chunk("wiki:1", index, f"passage {index}"),
            score=1.0 - index * 0.1,
        )
        for index in range(4)
    ]

    selected = _select_evidence(items, limit=4, max_per_source=2)

    assert len(selected) == 2
    assert [item.chunk.document_id for item in selected] == ["wiki:1", "wiki:1"]


def test_select_evidence_drops_near_duplicate_chunks():
    text = "Kafei and Anju reunite at the Stockpot Inn before dawn"
    items = [
        RetrievedChunk(chunk=_raw_chunk("wiki:1", 0, text), score=0.9),
        RetrievedChunk(chunk=_raw_chunk("wiki:2", 0, text), score=0.8),
        RetrievedChunk(chunk=_raw_chunk("wiki:3", 0, "Romani Ranch hides the aliens"), score=0.7),
    ]

    selected = _select_evidence(items, limit=4, max_per_source=2)

    assert [item.chunk.document_id for item in selected] == ["wiki:1", "wiki:3"]


def test_search_store_keeps_evidence_diverse(tmp_path):
    store = InMemoryVectorStore()
    provider = HashEmbeddingProvider()
    metadata = SourceMetadata(id="wiki:1", title="Anju's Anguish", source_page_id=1)
    texts = [
        "Kafei hides in the Stockpot Inn laundry room",
        "Anju waits at the Stockpot Inn front desk",
        "The postman delivers a letter to Kafei",
        "Skull Kid steals the Ocarina of Time",
    ]
    chunks = [_raw_chunk("wiki:1", index, text) for index, text in enumerate(texts)]
    vectors = provider.embed_documents(texts)
    store.upsert_document(
        Document(id="wiki:1", title="Anju's Anguish", content="x", metadata=metadata),
        chunks,
        vectors,
    )
    retriever = AdaptiveRetriever(
        store,
        FakeWiki([]),
        provider,
        _settings(tmp_path, similarity_threshold=-1.0, max_chunks_per_source=2),
        lock_path=tmp_path / "wiki.lock",
    )

    evidence = retriever._search_store(provider.embed_query("Anju Kafei"), top_k=4)

    assert len(evidence) == 2


def test_stale_cache_revalidates_and_reindexes_changed_page(tmp_path):
    stale = "2000-01-01T00:00:00+00:00"
    wiki = FakeWiki([_document(revision=10, retrieved_at=stale)])
    retriever = _retriever(tmp_path, wiki, cache_ttl_seconds=1)
    first = retriever.retrieve("Anju Kafei")
    assert first.status == "wiki_ingested"

    wiki.documents = [_document(revision=11, retrieved_at=stale)]
    wiki.search_calls.clear()
    wiki.fetch_calls = 0
    result = retriever.retrieve("Anju Kafei")

    assert result.status == "wiki_ingested"
    assert wiki.search_calls == []
    assert wiki.fetch_calls == 1
    assert result.evidence[0].chunk.metadata.source_revision_id == 11
    assert result.indexed_sources[0].source_revision_id == 11


def test_stale_cache_with_unchanged_revision_serves_cache(tmp_path):
    stale = "2000-01-01T00:00:00+00:00"
    wiki = FakeWiki([_document(retrieved_at=stale)])
    retriever = _retriever(tmp_path, wiki, cache_ttl_seconds=1)
    retriever.retrieve("Anju Kafei")

    wiki.fetch_calls = 0
    result = retriever.retrieve("Anju Kafei")

    assert result.status == "cache_hit"
    assert wiki.revision_calls == 1
    assert wiki.fetch_calls == 0


def test_fresh_cache_hit_skips_revalidation(tmp_path):
    wiki = FakeWiki([_document()])
    retriever = _retriever(tmp_path, wiki, cache_ttl_seconds=3600)
    retriever.retrieve("Anju Kafei")

    wiki.revision_calls = 0
    result = retriever.retrieve("Anju Kafei")

    assert result.status == "cache_hit"
    assert result.wiki_unreachable is False
    assert wiki.revision_calls == 0


def test_revalidation_failure_serves_stale_cache_with_warning(tmp_path):
    stale = "2000-01-01T00:00:00+00:00"
    wiki = FakeWiki([_document(retrieved_at=stale)])
    retriever = _retriever(tmp_path, wiki, cache_ttl_seconds=1)
    retriever.retrieve("Anju Kafei")

    wiki.fail_revisions = True
    result = retriever.retrieve("Anju Kafei")

    assert result.status == "cache_hit"
    assert result.evidence
    assert result.wiki_unreachable is True
    assert "revalidation failed" in result.warning.lower()


def test_revalidation_fetch_failure_serves_stale_cache(tmp_path):
    stale = "2000-01-01T00:00:00+00:00"
    wiki = FakeWiki([_document(retrieved_at=stale)])
    retriever = _retriever(tmp_path, wiki, cache_ttl_seconds=1)
    retriever.retrieve("Anju Kafei")

    # The revision changed, so revalidation wants to refetch, but the wiki
    # fetch fails: the stale cache must still be served instead of going miss.
    wiki.documents = [_document(revision=11, retrieved_at=stale)]
    wiki.fail_fetch = True
    result = retriever.retrieve("Anju Kafei")

    assert result.status == "cache_hit"
    assert result.evidence
    assert result.wiki_unreachable is True
    assert "revalidation failed" in result.warning.lower()


def test_stale_cache_drops_vanished_page(tmp_path):
    stale = "2000-01-01T00:00:00+00:00"
    wiki = FakeWiki([_document(retrieved_at=stale)])
    retriever = _retriever(tmp_path, wiki, cache_ttl_seconds=1)
    retriever.retrieve("Anju Kafei")

    wiki.documents = []  # the page was deleted upstream
    result = retriever.retrieve("Anju Kafei")

    assert result.status == "wiki_miss"
    assert result.evidence == []
    assert retriever.store.count() == 0


def test_close_at_exit_releases_clients_and_swallows_errors(tmp_path):
    from app.rag import retriever as retriever_module

    retriever = _retriever(tmp_path, FakeWiki())

    class Recorder:
        def __init__(self) -> None:
            self.closed = 0

        def close(self) -> None:
            self.closed += 1

    store = Recorder()
    retriever.store = store

    retriever_module._close_at_exit(retriever)
    retriever_module._close_at_exit(retriever)

    assert store.closed == 2

    class Exploding:
        def close(self) -> None:
            raise RuntimeError("cleanup failed")

    retriever.store = Exploding()
    retriever.wiki = Exploding()
    retriever_module._close_at_exit(retriever)  # must not raise


def test_build_default_retriever_registers_atexit_closer(monkeypatch, tmp_path):
    from app.rag import retriever as retriever_module

    registered: list[tuple] = []
    monkeypatch.setattr(
        retriever_module.atexit,
        "register",
        lambda fn, *args: registered.append((fn, args)),
    )
    monkeypatch.setattr(
        retriever_module.RAGSettings,
        "from_env",
        classmethod(lambda cls: _settings(tmp_path)),
    )
    monkeypatch.setattr(
        retriever_module,
        "get_embedding_provider",
        lambda *args, **kwargs: HashEmbeddingProvider(),
    )
    monkeypatch.setattr(
        retriever_module, "QdrantVectorStore", lambda **kwargs: InMemoryVectorStore()
    )
    monkeypatch.setattr(retriever_module, "MediaWikiClient", lambda **kwargs: FakeWiki())

    retriever_module.build_default_retriever.cache_clear()
    try:
        retriever = retriever_module.build_default_retriever()
    finally:
        retriever_module.build_default_retriever.cache_clear()

    assert registered == [(retriever_module._close_at_exit, (retriever,))]
