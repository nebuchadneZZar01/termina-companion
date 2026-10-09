"""Persistence and revision tests for the Qdrant RAG store."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.chunking import chunk_document
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.models import Document, SourceMetadata
from app.rag.retriever import AdaptiveRetriever, RAGSettings
from app.rag.store import QdrantVectorStore, VectorStoreError
from app.rag.wiki import WikiError, WikiPageReference


def _document(revision: int, content: str) -> Document:
    metadata = SourceMetadata(
        id="wiki:4819",
        title="Anju's Anguish",
        source_page_id=4819,
        source_revision_id=revision,
        source_revision_timestamp=f"2026-01-0{revision}T00:00:00Z",
    )
    return Document(
        id=metadata.id,
        title=metadata.title,
        content=content,
        metadata=metadata,
    )


def _index(store: QdrantVectorStore, embedding: HashEmbeddingProvider, document: Document):
    chunks = chunk_document(document, max_chars=40, overlap=5)
    vectors = embedding.embed_documents([chunk.text for chunk in chunks])
    store.upsert_document(document, chunks, vectors)
    return chunks


class _UnavailableWiki:
    def search(self, query, limit=3, terms=None, deadline=None):
        raise WikiError("offline")

    def fetch_pages(self, references, deadline=None):
        raise AssertionError("warm cache must not fetch pages")


class _OnePageWiki:
    def search(self, query, limit=3, terms=None, deadline=None):
        return [WikiPageReference(page_id=4819, title="Anju's Anguish")]

    def fetch_pages(self, references, deadline=None):
        return [_document(4819, "Kafei and Anju reunite before dawn.")]

    def current_revisions(self, page_ids, deadline=None):
        return {4819: 1}


def test_qdrant_local_store_persists_after_reopen(tmp_path: Path):
    path = tmp_path / "qdrant"
    embedding = HashEmbeddingProvider()
    first = QdrantVectorStore(path, "wiki_test", embedding.dimensions)
    try:
        _index(first, embedding, _document(1, "Kafei and Anju reunite before dawn."))
        assert first.count() == 1
    finally:
        first.close()

    second = QdrantVectorStore(path, "wiki_test", embedding.dimensions)
    try:
        results = second.similarity_search(embedding.embed_query("Kafei Anju"), top_k=2)
        assert second.count() == 1
        assert results[0][0].metadata.source_revision_id == 1
    finally:
        second.close()


def test_retriever_cache_survives_store_reopen_and_wiki_outage(tmp_path: Path):
    path = tmp_path / "qdrant"
    embedding = HashEmbeddingProvider()
    settings = RAGSettings(
        qdrant_path=path,
        similarity_threshold=0.1,
        chunk_max_chars=120,
        chunk_overlap=20,
    )
    first = AdaptiveRetriever(
        QdrantVectorStore(path, "wiki_test", embedding.dimensions),
        _OnePageWiki(),
        embedding,
        settings,
        lock_path=tmp_path / "wiki.lock",
    )
    first_result = first.retrieve("Anju Kafei")
    first.close()
    assert first_result.status == "wiki_ingested"

    second = AdaptiveRetriever(
        QdrantVectorStore(path, "wiki_test", embedding.dimensions),
        _UnavailableWiki(),
        embedding,
        settings,
        lock_path=tmp_path / "wiki.lock",
    )
    try:
        second_result = second.retrieve("Anju Kafei")
    finally:
        second.close()

    assert second_result.status == "cache_hit"
    assert second_result.evidence


def test_revision_upsert_removes_older_chunks(tmp_path: Path):
    store = QdrantVectorStore(tmp_path / "qdrant", "wiki_test", HashEmbeddingProvider().dimensions)
    embedding = HashEmbeddingProvider()
    try:
        old = _document(1, "Old revision with several words and a longer passage.")
        new = _document(2, "New revision is short.")
        _index(store, embedding, old)
        old_count = store.count()
        _index(store, embedding, new)

        assert old_count > 1
        assert store.count() == 1
        results = store.similarity_search(embedding.embed_query("new revision"), top_k=4)
        assert len(results) == 1
        assert results[0][0].metadata.source_revision_id == 2
    finally:
        store.close()


def test_same_revision_reindex_removes_stale_chunk_count(tmp_path: Path):
    store = QdrantVectorStore(tmp_path / "qdrant", "wiki_test", HashEmbeddingProvider().dimensions)
    embedding = HashEmbeddingProvider()
    try:
        first = _document(7, "First revision has several words and a longer passage.")
        second = _document(7, "Short replacement.")
        _index(store, embedding, first)
        assert store.count() > 1
        _index(store, embedding, second)
        assert store.count() == 1
    finally:
        store.close()


def test_qdrant_rejects_existing_collection_dimension_mismatch(tmp_path: Path):
    path = tmp_path / "qdrant"
    first = QdrantVectorStore(path, "wiki_test", 2)
    first.close()

    with pytest.raises(VectorStoreError, match="dimension"):
        QdrantVectorStore(path, "wiki_test", 384)


def test_qdrant_rejects_wrong_embedding_dimension(tmp_path: Path):
    store = QdrantVectorStore(tmp_path / "qdrant", "wiki_test", 384)
    try:
        document = _document(1, "A passage.")
        chunks = chunk_document(document)
        with pytest.raises(VectorStoreError, match="dimension"):
            store.upsert_document(document, chunks, [[0.0] * 2])
    finally:
        store.close()
