"""Keyword, vector and hybrid retrieval over the local Clock Town corpus."""

from __future__ import annotations

import logging
import math
import os
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Sequence
from functools import lru_cache

from app.rag.chunking import chunk_documents
from app.rag.embeddings import EmbeddingError, EmbeddingProvider
from app.rag.loader import DocumentLoadError, load_documents
from app.rag.models import Chunk, RetrievalResult, RetrievedChunk
from app.rag.store import VectorStoreError, build_vector_store

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = {
    "a",
    "about",
    "after",
    "all",
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
    "take",
    "the",
    "to",
    "un",
    "una",
    "use",
    "what",
    "when",
    "where",
    "with",
}
_TOKEN_REPLACEMENTS = {"’": " ", "'": " "}


class RAGError(RuntimeError):
    """Base error for optional retrieval failures."""


class KeywordRetriever:
    """Deterministic BM25-like lexical retriever for local chunks."""

    engine = "keyword"

    def __init__(self, chunks: Sequence[Chunk]) -> None:
        """Build an in-memory lexical index.

        Args:
            chunks: chunks to index.
        """
        self.chunks = list(chunks)
        self._postings: dict[str, dict[int, int]] = defaultdict(dict)
        self._lengths: list[int] = []
        self._build_index()

    def retrieve(self, query: str, top_k: int = 4) -> RetrievalResult:
        """Return chunks matching query terms.

        Args:
            query: natural-language player goal.
            top_k: maximum number of evidence chunks.

        Returns:
            RetrievalResult: ranked lexical evidence.
        """
        terms = _terms(query)
        if not terms or not self.chunks or top_k <= 0:
            return RetrievalResult(query=query, evidence=[], engine=self.engine)
        scores: dict[int, float] = defaultdict(float)
        matched: dict[int, set[str]] = defaultdict(set)
        average_length = sum(self._lengths) / len(self._lengths)
        if not average_length:
            return RetrievalResult(query=query, evidence=[], engine=self.engine)
        for term in terms:
            postings = self._postings.get(term, {})
            if not postings:
                continue
            idf = math.log(1 + (len(self.chunks) - len(postings) + 0.5) / (len(postings) + 0.5))
            for index, frequency in postings.items():
                length = self._lengths[index] or 1
                denominator = frequency + 1.5 * (0.25 + 0.75 * length / average_length)
                scores[index] += idf * frequency * 2.5 / denominator
                matched[index].add(term)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], self.chunks[item[0]].id))[
            :top_k
        ]
        evidence = [
            RetrievedChunk(
                chunk=self.chunks[index],
                score=round(score, 6),
                matched_terms=sorted(matched[index]),
            )
            for index, score in ranked
            if score > 0
        ]
        return RetrievalResult(query=query, evidence=evidence, engine=self.engine)

    def _build_index(self) -> None:
        """Populate term postings and document-length statistics."""
        for index, chunk in enumerate(self.chunks):
            searchable = " ".join(
                [
                    chunk.title,
                    chunk.metadata.quest_id,
                    chunk.metadata.area,
                    chunk.text,
                ]
            )
            counts = Counter(_terms(searchable))
            self._lengths.append(sum(counts.values()))
            for term, frequency in counts.items():
                self._postings[term][index] = frequency


class VectorRetriever:
    """Local embedding retriever backed by an in-memory vector store."""

    engine = "vector-local"

    def __init__(self, chunks: Sequence[Chunk], provider: EmbeddingProvider) -> None:
        """Build a vector index.

        Args:
            chunks: chunks to index.
            provider: embedding adapter.

        Raises:
            RAGError: if the provider cannot embed the corpus.
        """
        self.chunks = list(chunks)
        self.provider = provider
        try:
            self.store = build_vector_store(self.chunks, provider)
        except Exception as exc:
            if isinstance(exc, (EmbeddingError, VectorStoreError)):
                raise RAGError(str(exc)) from exc
            raise RAGError(f"Embedding provider failed: {exc}") from exc

    def retrieve(self, query: str, top_k: int = 4) -> RetrievalResult:
        """Return chunks nearest to the query embedding.

        Args:
            query: natural-language player goal.
            top_k: maximum number of evidence chunks.

        Returns:
            RetrievalResult: ranked vector evidence.

        Raises:
            RAGError: if query embedding or store lookup fails.
        """
        if top_k <= 0 or not self.chunks:
            return RetrievalResult(query=query, evidence=[], engine=self.engine)
        try:
            vector = self.provider.embed_query(query)
            matches = self.store.similarity_search(vector, top_k=top_k)
        except Exception as exc:
            if isinstance(exc, (EmbeddingError, VectorStoreError, ValueError)):
                raise RAGError(str(exc)) from exc
            raise RAGError(f"Embedding query failed: {exc}") from exc
        return RetrievalResult(
            query=query,
            evidence=[
                RetrievedChunk(chunk=chunk, score=round(score, 6), matched_terms=[])
                for chunk, score in matches
                if score > 0
            ],
            engine=self.engine,
        )


class HybridRetriever:
    """Combine lexical and vector rankings while allowing vector fallback."""

    engine = "hybrid"

    def __init__(
        self,
        chunks: Sequence[Chunk],
        provider: EmbeddingProvider | None = None,
        vector_weight: float = 0.4,
    ) -> None:
        """Build lexical and optional vector indexes.

        Args:
            chunks: chunks to index.
            provider: optional embedding adapter.
            vector_weight: vector contribution in [0, 1].

        Raises:
            ValueError: if vector_weight is outside [0, 1].
            RAGError: if a supplied provider cannot build its index.
        """
        if not 0 <= vector_weight <= 1:
            raise ValueError("vector_weight must be between 0 and 1")
        self.keyword = KeywordRetriever(chunks)
        self.vector: VectorRetriever | None = None
        self.vector_weight = vector_weight
        self.vector_failed = False
        self.vector_warning = ""
        if provider is not None:
            try:
                self.vector = VectorRetriever(self.keyword.chunks, provider)
            except RAGError as exc:
                self.vector_failed = True
                self.vector_warning = str(exc)
                logger.warning("RAG vector index unavailable: %s", exc)

    def retrieve(self, query: str, top_k: int = 4) -> RetrievalResult:
        """Return hybrid evidence, falling back to keyword-only if needed.

        Args:
            query: natural-language player goal.
            top_k: maximum number of evidence chunks.

        Returns:
            RetrievalResult: ranked evidence and optional warning.
        """
        lexical = self.keyword.retrieve(query, top_k=max(top_k * 3, top_k))
        if self.vector is None:
            update = {"evidence": lexical.evidence[:top_k], "engine": self.engine}
            if self.vector_failed:
                update["engine"] = "keyword-fallback"
                update["warning"] = self.vector_warning
            return lexical.model_copy(update=update)
        try:
            vector = self.vector.retrieve(query, top_k=max(top_k * 3, top_k))
        except RAGError as exc:
            result = lexical.model_copy(
                update={"evidence": lexical.evidence[:top_k], "warning": str(exc)}
            )
            result.engine = "keyword-fallback"
            return result
        lexical_scores = _normalize_scores(lexical.evidence)
        vector_scores = _normalize_scores(vector.evidence)
        combined: dict[str, tuple[Chunk, float, set[str]]] = {}
        for item in lexical.evidence:
            key = item.chunk.id
            score = (1 - self.vector_weight) * lexical_scores.get(key, 0.0)
            combined[key] = (item.chunk, score, set(item.matched_terms))
        for item in vector.evidence:
            key = item.chunk.id
            previous = combined.get(key)
            score = self.vector_weight * vector_scores.get(key, 0.0)
            terms = set(previous[2]) if previous else set()
            combined[key] = (
                item.chunk,
                (previous[1] if previous else 0.0) + score,
                terms,
            )
        ranked = sorted(combined.values(), key=lambda item: (-item[1], item[0].id))
        evidence = [
            RetrievedChunk(
                chunk=chunk,
                score=round(score, 6),
                matched_terms=sorted(terms),
            )
            for chunk, score, terms in ranked[:top_k]
            if score > 0
        ]
        return RetrievalResult(query=query, evidence=evidence, engine=self.engine)


@lru_cache(maxsize=1)
def build_default_retriever() -> KeywordRetriever:
    """Load and index the checked-in Clock Town corpus once.

    Returns:
        KeywordRetriever: cached lexical retriever.

    Raises:
        RAGError: if the local corpus cannot be loaded.
    """
    try:
        documents = load_documents()
        chunks = chunk_documents(documents)
    except (DocumentLoadError, ValueError) as exc:
        raise RAGError(f"Cannot build default RAG index: {exc}") from exc
    return KeywordRetriever(chunks)


def retrieve(query: str, top_k: int = 4) -> RetrievalResult:
    """Retrieve local evidence without allowing optional failures to escape.

    This is the public Knowledge Agent seam. Structured MCP context remains
    usable when the corpus cannot be loaded or indexed.

    Args:
        query: natural-language player goal.
        top_k: maximum evidence chunks.

    Returns:
        RetrievalResult: evidence, engine label and optional warning.
    """
    if not _rag_enabled():
        return RetrievalResult(query=query, evidence=[], engine="disabled")
    try:
        return build_default_retriever().retrieve(query, top_k=top_k)
    except Exception as exc:
        logger.warning("RAG retrieval unavailable: %s", exc)
        return RetrievalResult(
            query=query,
            evidence=[],
            engine="unavailable",
            warning=str(exc),
        )


def safe_retrieve(query: str, top_k: int = 4) -> RetrievalResult:
    """Backward-compatible alias for :func:`retrieve`.

    Args:
        query: natural-language player goal.
        top_k: maximum evidence chunks.

    Returns:
        RetrievalResult: evidence or a degraded result.
    """
    return retrieve(query, top_k=top_k)


def _terms(text: str) -> list[str]:
    """Normalize English/Italian text into searchable terms.

    Args:
        text: source or query text.

    Returns:
        list[str]: normalized non-stop-word terms.
    """
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    for old, new in _TOKEN_REPLACEMENTS.items():
        normalized = normalized.replace(old, new)
    return [
        term for term in _TOKEN_RE.findall(normalized) if term not in _STOP_WORDS and len(term) > 1
    ]


def _normalize_scores(evidence: Sequence[RetrievedChunk]) -> dict[str, float]:
    """Normalize positive evidence scores to [0, 1] by maximum value.

    Args:
        evidence: ranked evidence items.

    Returns:
        dict[str, float]: chunk-id to normalized score.
    """
    if not evidence:
        return {}
    maximum = max(item.score for item in evidence)
    if maximum <= 0:
        return {item.chunk.id: 0.0 for item in evidence}
    return {item.chunk.id: item.score / maximum for item in evidence}


def _rag_enabled() -> bool:
    """Read the optional local RAG switch.

    Returns:
        bool: whether retrieval should run; defaults to enabled.
    """
    value = os.getenv("RAG_ENABLED", "1").strip().casefold()
    return value not in {"0", "false", "no", "off"}
