"""Tests for the FastEmbed adapter without downloading a model."""

from __future__ import annotations

import pytest

from app.rag import embeddings


class FakeTextEmbedding:
    instances: list["FakeTextEmbedding"] = []

    def __init__(self, *, model_name, cache_dir, lazy_load):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.lazy_load = lazy_load
        self.__class__.instances.append(self)

    @staticmethod
    def list_supported_models():
        return [{"model": "test-model", "dim": 3}]

    def embed(self, texts):
        for text in texts:
            yield [float(len(text)), 1.0, -1.0]

    def query_embed(self, text):
        yield [float(len(text)), 1.0, -1.0]


def test_fastembed_adapter_uses_model_metadata_and_query_api(monkeypatch):
    FakeTextEmbedding.instances.clear()
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    provider = embeddings.FastEmbedProvider("test-model", cache_dir="/tmp/model-cache")

    assert provider.dimensions == 3
    assert provider.embed_documents(["a", "abcd"]) == [[1.0, 1.0, -1.0], [4.0, 1.0, -1.0]]
    assert provider.embed_query("abc") == [3.0, 1.0, -1.0]
    assert FakeTextEmbedding.instances[0].lazy_load is True
    assert FakeTextEmbedding.instances[0].cache_dir == "/tmp/model-cache"


def test_default_fastembed_metadata_is_available_offline(monkeypatch):
    def offline_registry():
        raise OSError("model registry offline")

    monkeypatch.setattr(embeddings.TextEmbedding, "list_supported_models", offline_registry)
    provider = embeddings.FastEmbedProvider(embeddings.DEFAULT_FASTEMBED_MODEL)

    assert provider.dimensions == 384


def test_fastembed_rejects_unknown_model(monkeypatch):
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    with pytest.raises(embeddings.EmbeddingError, match="Unsupported"):
        embeddings.FastEmbedProvider("missing-model")
