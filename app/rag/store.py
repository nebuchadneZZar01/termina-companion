"""Small in-memory vector store used by the RAG prototype."""

from __future__ import annotations

import math
from collections.abc import Sequence

from app.rag.embeddings import EmbeddingProvider
from app.rag.models import Chunk


class VectorStoreError(RuntimeError):
    """Raised when vectors cannot be added or queried consistently."""


class InMemoryVectorStore:
    """Store chunk vectors in process memory and rank by cosine similarity."""

    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._vectors: list[list[float]] = []

    @property
    def chunks(self) -> list[Chunk]:
        """Return a copy of the stored chunks."""
        return list(self._chunks)

    def add(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        """Add aligned chunks and vectors to the store.

        Args:
            chunks: chunks to index.
            vectors: one vector per chunk.

        Raises:
            VectorStoreError: if lengths or dimensions do not align.
        """
        if len(chunks) != len(vectors):
            raise VectorStoreError("chunks and vectors must have the same length")
        if not vectors:
            return
        dimension = len(vectors[0])
        if dimension == 0:
            raise VectorStoreError("vectors must not be empty")
        for vector in vectors:
            if len(vector) != dimension:
                raise VectorStoreError("all vectors must have the same dimension")
        self._chunks.extend(chunks)
        self._vectors.extend([list(vector) for vector in vectors])

    def similarity_search(
        self, query_vector: Sequence[float], top_k: int = 4
    ) -> list[tuple[Chunk, float]]:
        """Return the most similar stored chunks.

        Args:
            query_vector: query embedding.
            top_k: maximum number of results.

        Returns:
            list[tuple[Chunk, float]]: chunks and cosine scores, descending.

        Raises:
            VectorStoreError: if the query dimension does not match the store.
        """
        if top_k <= 0:
            return []
        if not self._vectors:
            return []
        dimension = len(self._vectors[0])
        if len(query_vector) != dimension:
            raise VectorStoreError(
                f"query vector has dimension {len(query_vector)}, expected {dimension}"
            )
        ranked = [
            (chunk, _cosine(query_vector, vector))
            for chunk, vector in zip(self._chunks, self._vectors, strict=True)
        ]
        ranked.sort(key=lambda item: (-item[1], item[0].id))
        return ranked[:top_k]


def build_vector_store(chunks: Sequence[Chunk], provider: EmbeddingProvider) -> InMemoryVectorStore:
    """Embed chunks and build a local vector store.

    Args:
        chunks: chunks to index.
        provider: embedding adapter.

    Returns:
        InMemoryVectorStore: populated store.
    """
    store = InMemoryVectorStore()
    if chunks:
        store.add(
            chunks,
            provider.embed_documents(
                [f"{chunk.title}\n{chunk.metadata.area}\n{chunk.text}" for chunk in chunks]
            ),
        )
    return store


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Calculate cosine similarity, treating zero vectors as unrelated.

    Args:
        left: first vector.
        right: second vector.

    Returns:
        float: similarity in [-1, 1], or 0 for a zero vector.
    """
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
