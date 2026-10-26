"""Vector stores used by the adaptive wiki retriever."""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.rag.models import Chunk, Document


class VectorStoreError(RuntimeError):
    """Raised when vectors cannot be added or queried consistently."""


class VectorStore(Protocol):
    """Persistence seam required by :class:`AdaptiveRetriever`."""

    name: str

    def upsert_document(
        self, document: Document, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> None:
        """Replace one source document's indexed revision."""

    def similarity_search(
        self,
        query_vector: Sequence[float],
        top_k: int = 4,
        score_threshold: float | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Return the most similar stored chunks."""

    def count(self) -> int:
        """Return number of indexed chunks."""

    def delete_document(self, document_id: str) -> None:
        """Delete all chunks belonging to a source document."""


def _validate_aligned(chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> int:
    if len(chunks) != len(vectors):
        raise VectorStoreError("chunks and vectors must have the same length")
    if not vectors:
        return 0
    dimensions = len(vectors[0])
    if dimensions == 0:
        raise VectorStoreError("vectors must not be empty")
    if any(len(vector) != dimensions for vector in vectors):
        raise VectorStoreError("all vectors must have the same dimension")
    return dimensions


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


class InMemoryVectorStore:
    """Small deterministic store useful for unit tests and dependency injection."""

    name = "memory"

    def __init__(self) -> None:
        self._entries: dict[str, tuple[Chunk, list[float]]] = {}

    @property
    def chunks(self) -> list[Chunk]:
        return [chunk for chunk, _vector in self._entries.values()]

    def count(self) -> int:
        return len(self._entries)

    def upsert_document(
        self, document: Document, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> None:
        _validate_aligned(chunks, vectors)
        self.delete_document(document.id)
        for chunk, vector in zip(chunks, vectors, strict=True):
            self._entries[chunk.id] = (chunk.model_copy(deep=True), list(vector))

    def similarity_search(
        self,
        query_vector: Sequence[float],
        top_k: int = 4,
        score_threshold: float | None = None,
    ) -> list[tuple[Chunk, float]]:
        if top_k <= 0 or not self._entries:
            return []
        dimension = len(next(iter(self._entries.values()))[1])
        if len(query_vector) != dimension:
            raise VectorStoreError(
                f"query vector has dimension {len(query_vector)}, expected {dimension}"
            )
        ranked = [
            (chunk, _cosine(query_vector, vector)) for chunk, vector in self._entries.values()
        ]
        if score_threshold is not None:
            ranked = [item for item in ranked if item[1] >= score_threshold]
        ranked.sort(key=lambda item: (-item[1], item[0].id))
        return ranked[:top_k]

    def delete_document(self, document_id: str) -> None:
        self._entries = {
            chunk_id: entry
            for chunk_id, entry in self._entries.items()
            if entry[0].document_id != document_id
        }


class QdrantVectorStore:
    """Persistent Qdrant local-mode store; no Qdrant server is required."""

    name = "qdrant"

    def __init__(
        self,
        path: str | Path,
        collection_name: str,
        dimensions: int,
    ) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.dimensions = dimensions
        try:
            self._client = QdrantClient(
                path=str(self.path),
                force_disable_check_same_thread=True,
            )
            self._ensure_collection()
        except Exception as exc:
            client = getattr(self, "_client", None)
            if client is not None:
                client.close()
            raise VectorStoreError(f"Cannot open Qdrant store at {self.path}: {exc}") from exc

    def _ensure_collection(self) -> None:
        if self._client.collection_exists(self.collection_name):
            self._validate_collection()
            return
        try:
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.dimensions,
                    distance=models.Distance.COSINE,
                ),
            )
        except Exception as exc:
            # Another local process may have created it between the existence
            # check and create call. Re-check and validate before surfacing the
            # failure.
            if not self._client.collection_exists(self.collection_name):
                raise VectorStoreError(f"Cannot create Qdrant collection: {exc}") from exc
            self._validate_collection()

    def _validate_collection(self) -> None:
        try:
            collection = self._client.get_collection(self.collection_name)
            params = getattr(getattr(collection, "config", None), "params", None)
            vectors = getattr(params, "vectors", None)
            if isinstance(vectors, dict):
                if len(vectors) != 1:
                    raise VectorStoreError(
                        "Qdrant collection must use one unnamed vector configuration"
                    )
                vectors = next(iter(vectors.values()))
            size = getattr(vectors, "size", None)
            if size != self.dimensions:
                raise VectorStoreError(
                    f"Qdrant collection vector dimension is {size}, expected {self.dimensions}"
                )
            distance = getattr(vectors, "distance", None)
            if distance not in {models.Distance.COSINE, "Cosine"}:
                raise VectorStoreError(f"Qdrant collection distance is {distance}, expected cosine")
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError(
                f"Cannot inspect Qdrant collection {self.collection_name!r}: {exc}"
            ) from exc

    def count(self) -> int:
        try:
            return int(self._client.count(self.collection_name, exact=True).count)
        except Exception as exc:
            raise VectorStoreError(f"Cannot count Qdrant collection: {exc}") from exc

    def upsert_document(
        self, document: Document, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> None:
        dimensions = _validate_aligned(chunks, vectors)
        if dimensions and dimensions != self.dimensions:
            raise VectorStoreError(
                f"document vectors have dimension {dimensions}, expected {self.dimensions}"
            )
        if not chunks:
            self.delete_document(document.id)
            return

        points = [
            models.PointStruct(
                id=self._point_id(chunk),
                vector=list(vector),
                payload={
                    "document_id": document.id,
                    "revision_id": document.metadata.source_revision_id,
                    "chunk": chunk.model_dump(mode="json"),
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        try:
            # Write the new revision first, then remove only points from the
            # previous revision. A failed cleanup leaves searchable old points
            # but never destroys the newly indexed revision.
            self._client.upsert(self.collection_name, points=points, wait=True)
            self._client.delete(
                self.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id",
                                match=models.MatchValue(value=document.id),
                            )
                        ],
                        must_not=[
                            models.HasIdCondition(
                                has_id=[self._point_id(chunk) for chunk in chunks]
                            )
                        ],
                    )
                ),
                wait=True,
            )
        except Exception as exc:
            raise VectorStoreError(f"Cannot upsert document {document.id!r}: {exc}") from exc

    def similarity_search(
        self,
        query_vector: Sequence[float],
        top_k: int = 4,
        score_threshold: float | None = None,
    ) -> list[tuple[Chunk, float]]:
        if top_k <= 0:
            return []
        if len(query_vector) != self.dimensions:
            raise VectorStoreError(
                f"query vector has dimension {len(query_vector)}, expected {self.dimensions}"
            )
        try:
            response = self._client.query_points(
                self.collection_name,
                query=list(query_vector),
                limit=top_k,
                score_threshold=score_threshold,
                with_payload=True,
            )
        except Exception as exc:
            raise VectorStoreError(f"Qdrant query failed: {exc}") from exc
        results: list[tuple[Chunk, float]] = []
        for point in response.points:
            payload = point.payload or {}
            raw_chunk = payload.get("chunk")
            if not raw_chunk:
                continue
            try:
                chunk = Chunk.model_validate(raw_chunk)
            except Exception as exc:
                raise VectorStoreError(f"Qdrant returned an invalid chunk payload: {exc}") from exc
            results.append((chunk, float(point.score)))
        return results

    def delete_document(self, document_id: str) -> None:
        try:
            self._client.delete(
                self.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id",
                                match=models.MatchValue(value=document_id),
                            )
                        ]
                    )
                ),
                wait=True,
            )
        except Exception as exc:
            raise VectorStoreError(f"Cannot delete document {document_id!r}: {exc}") from exc

    @staticmethod
    def _point_id(chunk: Chunk) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"termina-companion:{chunk.id}"))

    def close(self) -> None:
        """Close the embedded Qdrant client and release its local files."""
        self._client.close()
