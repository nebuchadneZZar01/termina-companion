"""Embedding adapter seam and deterministic local baseline embeddings."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence
from typing import Protocol

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class EmbeddingProvider(Protocol):
    """Minimal interface required by the local vector store."""

    name: str

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of source texts."""

    def embed_query(self, text: str) -> list[float]:
        """Embed one query text."""


class EmbeddingError(RuntimeError):
    """Raised when an embedding provider cannot produce valid vectors."""


class HashEmbeddingProvider:
    """Dependency-free hashed bag-of-words provider for local experiments.

    This is a deterministic baseline, not a semantic model. It makes the
    vector-store seam executable offline and gives tests a stable provider;
    a semantic provider can replace it without changing the retriever API.
    """

    name = "hash-local"

    def __init__(self, dimensions: int = 256) -> None:
        """Create a provider.

        Args:
            dimensions: number of output dimensions; must be positive.

        Raises:
            ValueError: if dimensions is not positive.
        """
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.dimensions = dimensions

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of documents.

        Args:
            texts: source texts.

        Returns:
            list[list[float]]: one normalized vector per input text.
        """
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """Embed a query.

        Args:
            text: query text.

        Returns:
            list[float]: normalized vector.
        """
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        """Hash tokens into a normalized sparse vector.

        Args:
            text: text to embed.

        Returns:
            list[float]: vector with the configured dimensionality.
        """
        vector = [0.0] * self.dimensions
        for token in _tokens(text):
            index_digest = hashlib.blake2b(f"index:{token}".encode("utf-8"), digest_size=8).digest()
            sign_digest = hashlib.blake2b(f"sign:{token}".encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(index_digest, "big") % self.dimensions
            sign = 1.0 if int.from_bytes(sign_digest, "big") & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector


def _tokens(text: str) -> list[str]:
    """Normalize text into stable tokens for the hashed baseline provider."""
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.replace("'", " ").replace("’", " ")
    return _TOKEN_RE.findall(normalized)


def get_embedding_provider(name: str = "hash") -> EmbeddingProvider:
    """Return a configured local embedding provider.

    Args:
        name: provider name. Only ``hash`` is available in the first slice.

    Returns:
        EmbeddingProvider: configured provider.

    Raises:
        EmbeddingError: if the provider name is unknown.
    """
    normalized = name.strip().casefold()
    if normalized in {"hash", "hash-local", "local-hash"}:
        return HashEmbeddingProvider()
    raise EmbeddingError(f"Unknown embedding provider: {name}")
