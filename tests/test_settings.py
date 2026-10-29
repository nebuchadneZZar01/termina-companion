"""Environment-driven configuration: parsing, validation, derived URLs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import RAGSettings, Settings, get_settings


def test_defaults_when_nothing_is_configured():
    settings = get_settings()

    assert settings.llm_provider is None
    assert settings.llm_api_key is None
    assert settings.log_level == "INFO"
    assert settings.planner == "llm"
    assert settings.rag.enabled is True
    assert settings.rag.top_k == 4
    assert settings.phoenix_annotation_url is None
    assert settings.phoenix_ui_url == "http://localhost:6006"


def test_blank_optional_values_are_unset(monkeypatch):
    """`.env.example` ships empty LLM lines; those must not become ""."""
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setenv("LLM_MODEL", "  ")
    monkeypatch.setenv("LLM_BASE_URL", "")

    settings = get_settings()

    assert settings.llm_provider is None
    assert settings.llm_model is None
    assert settings.llm_base_url is None


def test_api_key_is_a_secret(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-secret")

    settings = get_settings()

    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "sk-secret"
    assert "sk-secret" not in repr(settings)


def test_planner_engine_reads_the_environment(monkeypatch):
    """The ablation engine is opt-in and validated at startup."""
    assert get_settings().planner == "llm"

    monkeypatch.setenv("PLANNER", "deterministic")
    assert get_settings().planner == "deterministic"

    monkeypatch.setenv("PLANNER", "magic")
    with pytest.raises(ValidationError):
        get_settings()


def test_rag_settings_read_the_prefixed_environment(monkeypatch):
    monkeypatch.setenv("RAG_TOP_K", "9")
    monkeypatch.setenv("RAG_SIMILARITY_THRESHOLD", "0.72")
    monkeypatch.setenv("RAG_QDRANT_PATH", "/tmp/qdrant")

    settings = get_settings()

    assert settings.rag.top_k == 9
    assert settings.rag.similarity_threshold == 0.72
    assert str(settings.rag.qdrant_path) == "/tmp/qdrant"


def test_invalid_value_fails_at_startup(monkeypatch):
    monkeypatch.setenv("RAG_TOP_K", "not-a-number")

    with pytest.raises(ValidationError):
        get_settings()


def test_out_of_range_threshold_fails_at_startup(monkeypatch):
    monkeypatch.setenv("RAG_SIMILARITY_THRESHOLD", "2.0")

    with pytest.raises(ValidationError):
        get_settings()


def test_log_level_is_normalized_and_validated(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert get_settings().log_level == "DEBUG"

    monkeypatch.setenv("LOG_LEVEL", "verbose")
    with pytest.raises(ValidationError):
        get_settings()


@pytest.mark.parametrize("raw", ["0", "false", "off", "no"])
def test_rag_enabled_accepts_the_documented_false_values(monkeypatch, raw):
    monkeypatch.setenv("RAG_ENABLED", raw)
    assert get_settings().rag.enabled is False


def test_rag_disabled_settings_still_validate_chunking(monkeypatch):
    monkeypatch.setenv("RAG_CHUNK_OVERLAP", "200")
    monkeypatch.setenv("RAG_CHUNK_MAX_CHARS", "100")

    with pytest.raises(ValidationError):
        get_settings()


def test_collection_name_is_model_specific():
    first = RAGSettings(embedding_model="model-a").collection_name
    second = RAGSettings(embedding_model="model-b").collection_name

    assert first != second
    assert first.startswith("termina_wiki_model_a_")


def test_annotation_url_prefers_phoenix_base_url(monkeypatch):
    monkeypatch.setenv("PHOENIX_BASE_URL", "http://phoenix.local:6006/")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel:6006")

    assert get_settings().phoenix_annotation_url == "http://phoenix.local:6006"

    monkeypatch.delenv("PHOENIX_BASE_URL")
    assert get_settings().phoenix_annotation_url == "http://otel:6006"

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    assert get_settings().phoenix_annotation_url is None


def test_phoenix_ui_url_is_derived_from_the_otlp_endpoint(monkeypatch):
    """The UI link is scheme + host of the endpoint, port forced to 6006."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:6006")
    assert get_settings().phoenix_ui_url == "http://localhost:6006"

    # Another host, trailing slash: port is still forced to the UI port.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://phoenix:6006/")
    assert get_settings().phoenix_ui_url == "http://phoenix:6006"

    # Any other port (e.g. a hypothetical gRPC base) still maps to the UI port.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://phoenix:4317")
    assert get_settings().phoenix_ui_url == "http://phoenix:6006"

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    assert get_settings().phoenix_ui_url == "http://localhost:6006"


def test_tracing_flag_follows_the_otlp_endpoint(monkeypatch):
    assert get_settings().tracing_enabled is False

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:6006")

    assert get_settings().tracing_enabled is True


def test_settings_class_reads_the_same_values_as_get_settings(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")

    assert Settings().llm_base_url == "http://localhost:11434"
