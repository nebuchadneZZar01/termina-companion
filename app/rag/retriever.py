"""Adaptive cache-aside retrieval over persistent Qdrant and Zelda Wiki."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
import unicodedata
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from filelock import FileLock
from filelock import Timeout as FileLockTimeout
from pydantic import BaseModel, Field, model_validator

from app.rag.chunking import chunk_document
from app.rag.embeddings import (
    DEFAULT_FASTEMBED_MODEL,
    EmbeddingError,
    EmbeddingProvider,
    get_embedding_provider,
)
from app.rag.models import Document, IndexedSource, RetrievalResult, RetrievedChunk
from app.rag.store import QdrantVectorStore, VectorStore, VectorStoreError
from app.rag.wiki import MediaWikiClient, WikiError, WikiPageReference

logger = logging.getLogger(__name__)

DEFAULT_QDRANT_PATH = Path(".cache/termina-companion/qdrant")
DEFAULT_EMBEDDING_MODEL = DEFAULT_FASTEMBED_MODEL
# Pull a wider candidate pool from the store before applying diversity rules,
# so a per-source cap can still fill the requested top-k from other pages.
_CANDIDATE_MULTIPLIER = 4
_MAX_CANDIDATES = 50
_NEAR_DUPLICATE_JACCARD = 0.8
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = {
    "a",
    "about",
    "after",
    "all",
    "also",
    "an",
    "and",
    "are",
    "at",
    "be",
    "before",
    "but",
    "by",
    "can",
    "come",
    "con",
    "da",
    "dal",
    "dei",
    "del",
    "della",
    "di",
    "do",
    "e",
    "find",
    "for",
    "from",
    "get",
    "give",
    "how",
    "i",
    "il",
    "in",
    "is",
    "it",
    "la",
    "le",
    "make",
    "me",
    "my",
    "of",
    "on",
    "or",
    "per",
    "prima",
    "take",
    "the",
    "to",
    "un",
    "una",
    "use",
    "want",
    "what",
    "when",
    "where",
    "with",
}


class RAGError(RuntimeError):
    """Raised when adaptive retrieval cannot complete."""


class WikiSource(Protocol):
    """Minimal source seam used by the adaptive retriever."""

    def search(
        self,
        query: str,
        limit: int = 3,
        terms: list[str] | tuple[str, ...] | None = None,
        deadline: float | None = None,
    ) -> list[WikiPageReference]:
        """Find candidate page references."""

    def fetch_pages(
        self, references: list[WikiPageReference], deadline: float | None = None
    ) -> list[Document]:
        """Fetch and clean candidate pages."""

    def current_revisions(
        self, page_ids: list[int], deadline: float | None = None
    ) -> dict[int, int]:
        """Return the current revision ID for each page that still exists."""


class RAGSettings(BaseModel):
    """Runtime settings for persistent adaptive RAG."""

    qdrant_path: Path = DEFAULT_QDRANT_PATH
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    similarity_threshold: float = Field(default=0.72, ge=-1.0, le=1.0)
    top_k: int = Field(default=4, gt=0, le=50)
    max_pages_per_miss: int = Field(default=3, gt=0, le=20)
    max_chunks_per_source: int = Field(default=2, gt=0, le=50)
    request_timeout_seconds: float = Field(default=20.0, gt=0, le=300)
    wiki_budget_seconds: float = Field(default=60.0, ge=0.0, le=3600)
    cache_ttl_seconds: float = Field(default=604800.0, ge=0.0)
    min_term_coverage: float = Field(default=0.15, ge=0.0, le=1.0)
    chunk_max_chars: int = Field(default=1200, gt=0)
    chunk_overlap: int = Field(default=120, ge=0)

    @model_validator(mode="after")
    def validate_chunking(self) -> "RAGSettings":
        if self.chunk_overlap >= self.chunk_max_chars:
            raise ValueError("chunk overlap must be smaller than chunk size")
        return self

    @classmethod
    def from_env(cls) -> RAGSettings:
        """Build settings from the documented environment variables."""
        values: dict[str, object] = {}
        mapping = {
            "qdrant_path": "RAG_QDRANT_PATH",
            "embedding_model": "RAG_EMBEDDING_MODEL",
            "similarity_threshold": "RAG_SIMILARITY_THRESHOLD",
            "top_k": "RAG_TOP_K",
            "max_pages_per_miss": "RAG_MAX_PAGES_PER_MISS",
            "max_chunks_per_source": "RAG_MAX_CHUNKS_PER_SOURCE",
            "request_timeout_seconds": "RAG_REQUEST_TIMEOUT_SECONDS",
            "wiki_budget_seconds": "RAG_WIKI_BUDGET_SECONDS",
            "cache_ttl_seconds": "RAG_CACHE_TTL_SECONDS",
        }
        for field_name, env_name in mapping.items():
            raw = os.getenv(env_name)
            if raw is None or not raw.strip():
                continue
            if field_name in {"top_k", "max_pages_per_miss", "max_chunks_per_source"}:
                values[field_name] = int(raw)
            elif field_name in {
                "similarity_threshold",
                "request_timeout_seconds",
                "wiki_budget_seconds",
                "cache_ttl_seconds",
            }:
                values[field_name] = float(raw)
            else:
                values[field_name] = raw
        return cls(**values)

    @property
    def collection_name(self) -> str:
        """Return a stable, model-specific Qdrant collection name."""
        digest = hashlib.sha256(self.embedding_model.encode("utf-8")).hexdigest()[:12]
        slug = re.sub(r"[^a-z0-9]+", "_", self.embedding_model.casefold()).strip("_")
        return f"termina_wiki_{slug[:32]}_{digest}"


class AdaptiveRetriever:
    """Search persistent vectors first, ingest wiki pages on a cache miss."""

    engine = "qdrant-fastembed"

    def __init__(
        self,
        store: VectorStore,
        wiki: WikiSource,
        embedding: EmbeddingProvider,
        settings: RAGSettings,
        lock_path: str | Path | None = None,
    ) -> None:
        self.store = store
        self.wiki = wiki
        self.embedding = embedding
        self.settings = settings
        lock_file = Path(lock_path) if lock_path else settings.qdrant_path.with_suffix(".lock")
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = lock_file

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        search_terms: list[str] | tuple[str, ...] | None = None,
    ) -> RetrievalResult:
        """Run one cache-aside retrieval and always query vectors after ingestion."""
        limit = self.settings.top_k if top_k is None else top_k
        if limit <= 0 or not query.strip():
            return RetrievalResult(
                query=query,
                engine=self.engine,
                status="wiki_miss",
            )
        try:
            query_vector = self.embedding.embed_query(query)
            initial = self._search_store(query_vector, limit)
            if self._sufficient(initial, query) and not self._is_stale(initial):
                return self._result(query, initial, "cache_hit")

            with FileLock(str(self.lock_path), timeout=self.settings.request_timeout_seconds):
                # Another request may have populated the same page while this
                # request waited for the ingestion lock.
                after_wait = self._search_store(query_vector, limit)
                if self._sufficient(after_wait, query) and not self._is_stale(after_wait):
                    return self._result(query, after_wait, "cache_hit")

                deadline = self._wiki_deadline()
                if self._sufficient(after_wait, query):
                    # Sufficient but stale: revalidate those specific pages
                    # instead of paying for a full wiki search.
                    return self._revalidate(query, query_vector, limit, after_wait, deadline)

                references = self.wiki.search(
                    query,
                    limit=self.settings.max_pages_per_miss,
                    terms=search_terms,
                    deadline=deadline,
                )
                if not references:
                    return self._result(query, [], "wiki_miss")

                documents = self.wiki.fetch_pages(references, deadline=deadline)
                ingested_pages, indexed_sources, ingest_warnings = self._ingest(documents)
                if not ingested_pages and ingest_warnings:
                    warning = ingest_warnings[0]
                    logger.warning("Adaptive RAG ingestion unavailable: %s", warning)
                    return RetrievalResult(
                        query=query,
                        engine=self.engine,
                        status="unavailable",
                        warning=warning,
                    )
                if not documents:
                    return self._result(query, [], "wiki_miss")

                # Mandatory second retrieval: fetched page text is never
                # returned directly to the caller or planner.
                final = self._search_store(query_vector, limit)
                status = "wiki_ingested" if final else "wiki_miss"
                warning = "; ".join(ingest_warnings)
                return self._result(
                    query,
                    final,
                    status,
                    ingested_pages=ingested_pages,
                    indexed_sources=indexed_sources,
                    warning=warning,
                )
        except FileLockTimeout as exc:
            return self._unavailable(query, f"Wiki ingestion lock timed out: {exc}")
        except (EmbeddingError, VectorStoreError, WikiError, OSError, ValueError) as exc:
            return self._unavailable(query, str(exc))
        except Exception as exc:  # defensive boundary for optional RAG
            logger.exception("Unexpected adaptive RAG failure")
            return self._unavailable(query, str(exc))

    def _revalidate(
        self,
        query: str,
        query_vector: Sequence[float],
        limit: int,
        evidence: list[RetrievedChunk],
        deadline: float | None,
    ) -> RetrievalResult:
        """Refresh stale cached pages, falling back to the cache when offline.

        Only the pages represented by the cached evidence are checked, so a
        stale hit stays much cheaper than a full wiki miss. A revalidation
        failure serves the cached evidence with a warning rather than degrading
        the whole retrieval to `unavailable`.
        """
        pages: dict[int, str] = {}
        indexed_revisions: dict[int, int | None] = {}
        document_ids: dict[int, str] = {}
        for item in evidence:
            metadata = item.chunk.metadata
            page_id = metadata.source_page_id
            if page_id is None:
                continue
            pages.setdefault(page_id, metadata.title)
            indexed_revisions[page_id] = metadata.source_revision_id
            document_ids[page_id] = item.chunk.document_id
        if not pages:
            return self._result(query, evidence, "cache_hit")

        try:
            current = self.wiki.current_revisions(list(pages), deadline=deadline)
        except WikiError as exc:
            logger.warning("Wiki revalidation failed, serving cached evidence: %s", exc)
            return self._result(
                query,
                evidence,
                "cache_hit",
                warning=f"Wiki revalidation failed: {exc}",
            )

        changed = [
            page_id for page_id in pages if current.get(page_id) != indexed_revisions[page_id]
        ]
        vanished = [page_id for page_id in changed if page_id not in current]
        for page_id in vanished:
            try:
                self.store.delete_document(document_ids[page_id])
            except VectorStoreError as exc:
                logger.warning("Cannot drop vanished wiki page %s: %s", page_id, exc)

        to_fetch = [page_id for page_id in changed if page_id in current]
        if not to_fetch:
            gone = set(vanished)
            remaining = [
                item for item in evidence if item.chunk.metadata.source_page_id not in gone
            ]
            return self._result(query, remaining, "cache_hit" if remaining else "wiki_miss")

        references = [
            WikiPageReference(page_id=page_id, title=pages[page_id]) for page_id in to_fetch
        ]
        documents = self.wiki.fetch_pages(references, deadline=deadline)
        ingested_pages, indexed_sources, ingest_warnings = self._ingest(documents)
        final = self._search_store(query_vector, limit)
        if not final:
            # Revalidation could not produce usable evidence; keep the stale
            # cache instead of returning an empty result.
            return self._result(
                query,
                evidence,
                "cache_hit",
                warning="; ".join(ingest_warnings),
            )
        return self._result(
            query,
            final,
            "wiki_ingested",
            ingested_pages=ingested_pages,
            indexed_sources=indexed_sources,
            warning="; ".join(ingest_warnings),
        )

    def _wiki_deadline(self) -> float | None:
        """Return the monotonic deadline for the wiki leg of one miss."""
        budget = self.settings.wiki_budget_seconds
        if budget <= 0:
            return None
        return time.monotonic() + budget

    def _is_stale(self, evidence: list[RetrievedChunk]) -> bool:
        """Report whether cached evidence is older than the configured TTL.

        A missing or unparseable timestamp cannot prove staleness, so it is
        treated as fresh; that keeps pre-existing cache entries usable and
        avoids revalidating them on every retrieval.
        """
        ttl = self.settings.cache_ttl_seconds
        if ttl <= 0 or not evidence:
            return False
        now = time.time()
        for item in evidence:
            age = _age_seconds(item.chunk.metadata.retrieved_at, now)
            if age is not None and age > ttl:
                return True
        return False

    def _ingest(
        self, documents: list[Document]
    ) -> tuple[list[str], list[IndexedSource], list[str]]:
        """Chunk, embed and replace each fetched wiki revision.

        Return the source manifest separately from evidence so pages indexed
        during a miss remain visible even when no chunk passes the final
        similarity threshold.
        """
        pages: list[str] = []
        indexed_sources: list[IndexedSource] = []
        warnings: list[str] = []
        for document in documents:
            try:
                chunks = chunk_document(
                    document,
                    max_chars=self.settings.chunk_max_chars,
                    overlap=self.settings.chunk_overlap,
                )
                vectors = self.embedding.embed_documents(
                    [
                        self._embedding_text(chunk.title, chunk.section, chunk.text)
                        for chunk in chunks
                    ]
                )
                self.store.upsert_document(document, chunks, vectors)
                pages.append(document.title)
                indexed_sources.append(IndexedSource.from_metadata(document.metadata))
            except (EmbeddingError, VectorStoreError, ValueError) as exc:
                warnings.append(f"{document.title}: {exc}")
                logger.warning("RAG ingestion failed for %s: %s", document.title, exc)
        return pages, indexed_sources, warnings

    def _search_store(self, query_vector: Sequence[float], top_k: int) -> list[RetrievedChunk]:
        # Query a wider candidate pool, then keep a diverse, non-redundant set:
        # a page cannot dominate the evidence and overlapping chunk windows
        # collapse to their best-scoring representative.
        candidates = min(max(top_k * _CANDIDATE_MULTIPLIER, top_k), _MAX_CANDIDATES)
        matches = self.store.similarity_search(
            query_vector,
            top_k=candidates,
            score_threshold=self.settings.similarity_threshold,
        )
        ranked = [RetrievedChunk(chunk=chunk, score=round(score, 6)) for chunk, score in matches]
        return _select_evidence(
            ranked,
            limit=top_k,
            max_per_source=self.settings.max_chunks_per_source,
        )

    def _sufficient(self, evidence: list[RetrievedChunk], query: str) -> bool:
        """Require semantic score plus a small meaningful term overlap."""
        if not evidence:
            return False
        terms = _query_terms(query)
        if not terms:
            return True
        for item in evidence:
            searchable = _normalized_words(
                " ".join(
                    [
                        item.chunk.title,
                        item.chunk.section,
                        item.chunk.text,
                    ]
                )
            )
            coverage = sum(term in searchable for term in terms) / min(len(terms), 8)
            if coverage >= self.settings.min_term_coverage:
                return True
        return False

    @staticmethod
    def _embedding_text(title: str, section: str, text: str) -> str:
        return "\n".join(part for part in (title, section, text) if part)

    def _result(
        self,
        query: str,
        evidence: list[RetrievedChunk],
        status: str,
        ingested_pages: list[str] | None = None,
        indexed_sources: list[IndexedSource] | None = None,
        warning: str = "",
    ) -> RetrievalResult:
        sources = self._merge_sources(indexed_sources or [], self._sources_from_evidence(evidence))
        return RetrievalResult(
            query=query,
            evidence=evidence,
            engine=self.engine,
            status=status,  # type: ignore[arg-type]
            ingested_pages=ingested_pages or [],
            indexed_sources=sources,
            warning=warning,
        )

    @staticmethod
    def _sources_from_evidence(evidence: list[RetrievedChunk]) -> list[IndexedSource]:
        """Expose provenance for sources represented by a warm-cache result."""
        sources: dict[str, IndexedSource] = {}
        for item in evidence:
            source = IndexedSource.from_metadata(item.chunk.metadata)
            key = source.id or f"{source.source_page_id}:{source.source_revision_id}"
            sources.setdefault(key, source)
        return list(sources.values())

    @staticmethod
    def _merge_sources(*groups: list[IndexedSource]) -> list[IndexedSource]:
        """Merge source manifests without duplicating page revisions."""
        merged: list[IndexedSource] = []
        seen: set[str] = set()
        for group in groups:
            for source in group:
                key = source.id or f"{source.source_page_id}:{source.source_revision_id}"
                if key in seen:
                    continue
                seen.add(key)
                merged.append(source)
        return merged

    @staticmethod
    def _unavailable(query: str, warning: str) -> RetrievalResult:
        logger.warning("Adaptive RAG retrieval unavailable: %s", warning)
        return RetrievalResult(
            query=query,
            engine="unavailable",
            status="unavailable",
            warning=warning,
        )

    def close(self) -> None:
        """Close owned persistent clients when possible."""
        close = getattr(self.store, "close", None)
        if callable(close):
            close()
        close = getattr(self.wiki, "close", None)
        if callable(close):
            close()


def _select_evidence(
    items: list[RetrievedChunk], limit: int, max_per_source: int
) -> list[RetrievedChunk]:
    """Keep a diverse, non-redundant top-k set from a wider candidate pool.

    Candidates arrive in descending score order. A candidate is dropped when it
    is a near-duplicate of an already-kept chunk (overlapping windows of the
    same passage) or when its page has already reached the per-source cap.
    """
    selected: list[RetrievedChunk] = []
    kept_tokens: list[set[str]] = []
    per_source: dict[str, int] = {}
    for item in items:
        if len(selected) >= limit:
            break
        source = item.chunk.document_id
        if per_source.get(source, 0) >= max_per_source:
            continue
        tokens = _normalized_words(item.chunk.text)
        if any(_jaccard(tokens, kept) >= _NEAR_DUPLICATE_JACCARD for kept in kept_tokens):
            continue
        selected.append(item)
        kept_tokens.append(tokens)
        per_source[source] = per_source.get(source, 0) + 1
    return selected


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union)


def _age_seconds(value: str, now: float) -> float | None:
    """Return the age of an ISO timestamp, or ``None`` when it is unreadable."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return now - parsed.timestamp()


@lru_cache(maxsize=1)
def build_default_retriever() -> AdaptiveRetriever:
    """Build the process-wide persistent adaptive retriever once."""
    try:
        settings = RAGSettings.from_env()
        embedding = get_embedding_provider(
            "fastembed",
            model_name=settings.embedding_model,
        )
        store = QdrantVectorStore(
            path=settings.qdrant_path,
            collection_name=settings.collection_name,
            dimensions=embedding.dimensions,
        )
        wiki = MediaWikiClient(timeout_seconds=settings.request_timeout_seconds)
        return AdaptiveRetriever(store, wiki, embedding, settings)
    except Exception as exc:
        raise RAGError(f"Cannot build adaptive RAG: {exc}") from exc


def retrieve(
    query: str,
    top_k: int | None = None,
    search_terms: list[str] | tuple[str, ...] | None = None,
) -> RetrievalResult:
    """Retrieve wiki evidence without allowing optional failures to escape."""
    try:
        return build_default_retriever().retrieve(
            query,
            top_k=top_k,
            search_terms=search_terms,
        )
    except Exception as exc:
        logger.warning("Adaptive RAG unavailable: %s", exc)
        return RetrievalResult(
            query=query,
            engine="unavailable",
            status="unavailable",
            warning=str(exc),
        )


def safe_retrieve(
    query: str,
    top_k: int | None = None,
    search_terms: list[str] | tuple[str, ...] | None = None,
) -> RetrievalResult:
    """Backward-compatible alias for :func:`retrieve`."""
    return retrieve(query, top_k=top_k, search_terms=search_terms)


def _query_terms(query: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", query.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return [
        token
        for token in _TOKEN_RE.findall(normalized)
        if len(token) > 2 and token not in _STOP_WORDS
    ][:16]


def _normalized_words(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return set(_TOKEN_RE.findall(normalized))
