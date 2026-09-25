"""Adaptive cache-aside retrieval over persistent Qdrant and Zelda Wiki."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import unicodedata
from collections.abc import Sequence
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
from app.rag.models import Document, RetrievalResult, RetrievedChunk
from app.rag.store import QdrantVectorStore, VectorStore, VectorStoreError
from app.rag.wiki import MediaWikiClient, WikiError, WikiPageReference

logger = logging.getLogger(__name__)

DEFAULT_QDRANT_PATH = Path(".cache/termina-companion/qdrant")
DEFAULT_EMBEDDING_MODEL = DEFAULT_FASTEMBED_MODEL
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
    ) -> list[WikiPageReference]:
        """Find candidate page references."""

    def fetch_pages(self, references: list[WikiPageReference]) -> list[Document]:
        """Fetch and clean candidate pages."""


class RAGSettings(BaseModel):
    """Runtime settings for persistent adaptive RAG."""

    qdrant_path: Path = DEFAULT_QDRANT_PATH
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    similarity_threshold: float = Field(default=0.72, ge=-1.0, le=1.0)
    top_k: int = Field(default=4, gt=0, le=50)
    max_pages_per_miss: int = Field(default=3, gt=0, le=20)
    request_timeout_seconds: float = Field(default=20.0, gt=0, le=300)
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
            "request_timeout_seconds": "RAG_REQUEST_TIMEOUT_SECONDS",
        }
        for field_name, env_name in mapping.items():
            raw = os.getenv(env_name)
            if raw is None or not raw.strip():
                continue
            if field_name in {"top_k", "max_pages_per_miss"}:
                values[field_name] = int(raw)
            elif field_name in {"similarity_threshold", "request_timeout_seconds"}:
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
            if self._sufficient(initial, query):
                return self._result(query, initial, "cache_hit")

            with FileLock(str(self.lock_path), timeout=self.settings.request_timeout_seconds):
                # Another request may have populated the same page while this
                # request waited for the ingestion lock.
                after_wait = self._search_store(query_vector, limit)
                if self._sufficient(after_wait, query):
                    return self._result(query, after_wait, "cache_hit")

                references = self.wiki.search(
                    query,
                    limit=self.settings.max_pages_per_miss,
                    terms=search_terms,
                )
                if not references:
                    return self._result(query, [], "wiki_miss")

                documents = self.wiki.fetch_pages(references)
                ingested_pages, ingest_warnings = self._ingest(documents)
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
                    warning=warning,
                )
        except FileLockTimeout as exc:
            return self._unavailable(query, f"Wiki ingestion lock timed out: {exc}")
        except (EmbeddingError, VectorStoreError, WikiError, OSError, ValueError) as exc:
            return self._unavailable(query, str(exc))
        except Exception as exc:  # defensive boundary for optional RAG
            logger.exception("Unexpected adaptive RAG failure")
            return self._unavailable(query, str(exc))

    def _ingest(self, documents: list[Document]) -> tuple[list[str], list[str]]:
        """Chunk, embed and atomically replace each fetched wiki revision."""
        pages: list[str] = []
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
            except (EmbeddingError, VectorStoreError, ValueError) as exc:
                warnings.append(f"{document.title}: {exc}")
                logger.warning("RAG ingestion failed for %s: %s", document.title, exc)
        return pages, warnings

    def _search_store(self, query_vector: Sequence[float], top_k: int) -> list[RetrievedChunk]:
        matches = self.store.similarity_search(
            query_vector,
            top_k=top_k,
            score_threshold=self.settings.similarity_threshold,
        )
        return [RetrievedChunk(chunk=chunk, score=round(score, 6)) for chunk, score in matches]

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
        warning: str = "",
    ) -> RetrievalResult:
        return RetrievalResult(
            query=query,
            evidence=evidence,
            engine=self.engine,
            status=status,  # type: ignore[arg-type]
            ingested_pages=ingested_pages or [],
            warning=warning,
        )

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
