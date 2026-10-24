"""Embedding providers used by the persistent RAG store."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence
from typing import Any, Protocol

from fastembed import TextEmbedding

from app.settings import DEFAULT_FASTEMBED_MODEL

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

_KNOWN_DIMENSIONS = {DEFAULT_FASTEMBED_MODEL: 384}


class EmbeddingProvider(Protocol):
    """Minimal interface required by the vector store and adaptive retriever."""

    name: str
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of source texts."""

    def embed_query(self, text: str) -> list[float]:
        """Embed one query text."""


class EmbeddingError(RuntimeError):
    """Raised when an embedding provider cannot produce valid vectors."""


class HashEmbeddingProvider:
    """Dependency-free hashed bag-of-words provider for tests and experiments."""

    name = "hash-local"

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.dimensions = dimensions

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _tokens(text):
            index_digest = hashlib.blake2b(f"index:{token}".encode(), digest_size=8).digest()
            sign_digest = hashlib.blake2b(f"sign:{token}".encode(), digest_size=8).digest()
            index = int.from_bytes(index_digest, "big") % self.dimensions
            sign = 1.0 if int.from_bytes(sign_digest, "big") & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector


class FastEmbedProvider:
    """Local multilingual semantic embeddings backed by FastEmbed/ONNX."""

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        self.model_name = model_name.strip()
        if not self.model_name:
            raise EmbeddingError("Embedding model name must not be empty")
        self.name = f"fastembed:{self.model_name}"
        self.cache_dir = cache_dir
        self._model: TextEmbedding | None = None
        self.dimensions = self._find_dimensions(self.model_name)

    @staticmethod
    def _find_dimensions(model_name: str) -> int:
        """Read vector dimensionality without requiring registry access.

        The default model is fixed by this project, so keeping its dimension
        local keeps warm-cache startup usable when the machine is offline.
        Custom models still use FastEmbed's registry and fail soft at runtime
        when that metadata cannot be reached.
        """
        known_dimension = _KNOWN_DIMENSIONS.get(model_name)
        if known_dimension is not None:
            return known_dimension
        try:
            models = TextEmbedding.list_supported_models()
        except Exception as exc:  # pragma: no cover - provider/runtime dependent
            raise EmbeddingError(f"Cannot inspect FastEmbed models: {exc}") from exc
        for model in models:
            if model.get("model") == model_name:
                dimensions = model.get("dim")
                if isinstance(dimensions, int) and dimensions > 0:
                    return dimensions
        raise EmbeddingError(f"Unsupported FastEmbed embedding model: {model_name}")

    def _get_model(self) -> TextEmbedding:
        if self._model is None:
            try:
                self._model = TextEmbedding(
                    model_name=self.model_name,
                    cache_dir=self.cache_dir,
                    lazy_load=True,
                )
            except Exception as exc:
                message = f"Cannot load FastEmbed model {self.model_name}: {exc}"
                raise EmbeddingError(message) from exc
        return self._model

    @staticmethod
    def _as_floats(value: Any) -> list[float]:
        try:
            return [float(item) for item in value]
        except (TypeError, ValueError) as exc:
            message = f"Embedding backend returned a non-numeric vector: {value!r}"
            raise EmbeddingError(message) from exc

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        texts = list(texts)
        if not texts:
            return []
        try:
            vectors = self._get_model().embed(texts)
            result = [self._as_floats(vector) for vector in vectors]
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"FastEmbed document embedding failed: {exc}") from exc
        if len(result) != len(texts) or any(len(vector) != self.dimensions for vector in result):
            raise EmbeddingError("FastEmbed returned vectors with an unexpected shape")
        return result

    def embed_query(self, text: str) -> list[float]:
        if not text.strip():
            raise EmbeddingError("Embedding query must not be empty")
        try:
            vectors = list(self._get_model().query_embed(text))
        except Exception as exc:
            raise EmbeddingError(f"FastEmbed query embedding failed: {exc}") from exc
        if len(vectors) != 1:
            raise EmbeddingError("FastEmbed returned an unexpected number of query vectors")
        vector = self._as_floats(vectors[0])
        if len(vector) != self.dimensions:
            raise EmbeddingError("FastEmbed returned a query vector with an unexpected dimension")
        return vector


def _tokens(text: str) -> list[str]:
    """Normalize text into stable tokens for the hashed baseline provider."""
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.replace("'", " ").replace("’", " ")
    return _TOKEN_RE.findall(normalized)


def get_embedding_provider(
    name: str = "fastembed",
    model_name: str = DEFAULT_FASTEMBED_MODEL,
    cache_dir: str | None = None,
) -> EmbeddingProvider:
    """Return a configured embedding provider."""
    normalized = name.strip().casefold()
    if normalized in {"hash", "hash-local", "local-hash"}:
        return HashEmbeddingProvider()
    if normalized in {"fastembed", "semantic", "local-semantic"}:
        return FastEmbedProvider(model_name=model_name, cache_dir=cache_dir)
    raise EmbeddingError(f"Unknown embedding provider: {name}")
