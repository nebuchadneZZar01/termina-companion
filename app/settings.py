"""Application configuration read from environment variables.

Every environment variable the app understands is declared here as a Pydantic
setting, so a malformed value (``RAG_TOP_K=abc``, an unknown ``LOG_LEVEL``, an
out-of-range threshold) fails at startup instead of halfway through a run.
``.env`` is loaded into the process environment on import, once, so the fields
below remain the single source of truth for configuration.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

DEFAULT_QDRANT_PATH = Path(".cache/termina-companion/qdrant")
DEFAULT_PHOENIX_UI_URL = "http://localhost:6006"
PHOENIX_UI_PORT = 6006
#: Local multilingual FastEmbed model (384 dimensions). Lives here so the
#: settings module stays importable without pulling the fastembed stack.
DEFAULT_FASTEMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class RAGSettings(BaseSettings):
    """Runtime settings for persistent adaptive RAG.

    Field names map to the documented environment variables through the
    ``RAG_`` prefix (``top_k`` -> ``RAG_TOP_K``).
    """

    model_config = SettingsConfigDict(env_prefix="RAG_", extra="ignore")

    qdrant_path: Path = DEFAULT_QDRANT_PATH
    embedding_model: str = DEFAULT_FASTEMBED_MODEL
    # Provisional 2026-10-10: 0.60 best on 14 live scenarios
    # (0.60: 7/14, 0.72: 3/14, 0.80: 1/14, top_k=4); see
    # app/rag/scenarios.py (CALIBRATED_*) and scripts/calibrate_rag.py.
    # Override via RAG_SIMILARITY_THRESHOLD.
    similarity_threshold: float = Field(default=0.60, ge=-1.0, le=1.0)
    top_k: int = Field(default=4, gt=0, le=50)
    max_pages_per_miss: int = Field(default=3, gt=0, le=20)
    max_chunks_per_source: int = Field(default=2, gt=0, le=50)
    request_timeout_seconds: float = Field(default=20.0, gt=0, le=300)
    wiki_budget_seconds: float = Field(default=60.0, ge=0.0, le=3600)
    wiki_failure_threshold: int = Field(default=3, ge=0, le=100)
    wiki_cooldown_seconds: float = Field(default=60.0, ge=0.0, le=3600)
    cache_ttl_seconds: float = Field(default=604800.0, ge=0.0)
    min_term_coverage: float = Field(default=0.15, ge=0.0, le=1.0)
    chunk_max_chars: int = Field(default=1200, gt=0)
    chunk_overlap: int = Field(default=120, ge=0)
    #: ``RAG_ENABLED``; the evaluation harness flips it for A/B sweeps.
    enabled: bool = True

    @model_validator(mode="after")
    def validate_chunking(self) -> "RAGSettings":
        if self.chunk_overlap >= self.chunk_max_chars:
            raise ValueError("chunk overlap must be smaller than chunk size")
        return self

    @property
    def collection_name(self) -> str:
        """Return a stable, model-specific Qdrant collection name."""
        digest = hashlib.sha256(self.embedding_model.encode("utf-8")).hexdigest()[:12]
        slug = re.sub(r"[^a-z0-9]+", "_", self.embedding_model.casefold()).strip("_")
        return f"termina_wiki_{slug[:32]}_{digest}"


class Settings(BaseSettings):
    """Top-level application settings.

    Field names map to the environment variables without a prefix
    (``llm_provider`` -> ``LLM_PROVIDER``). Optional strings treat an empty
    value as unset, because ``.env.example`` ships them as blank lines.
    """

    model_config = SettingsConfigDict(extra="ignore")

    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    #: Planner engine. ``llm`` is the product path; ``deterministic`` is the
    #: evaluation baseline (the objective chain, no LLM call). A run can also
    #: override it explicitly, so a sweep never mutates the environment.
    planner: Literal["llm", "deterministic"] = "llm"
    otel_exporter_otlp_endpoint: str | None = None
    phoenix_base_url: str | None = None
    rag: RAGSettings = Field(default_factory=RAGSettings)

    @field_validator(
        "llm_provider",
        "llm_model",
        "llm_base_url",
        "llm_api_key",
        "otel_exporter_otlp_endpoint",
        "phoenix_base_url",
        mode="before",
    )
    @classmethod
    def _optional_text(cls, value: object) -> object:
        """Strip optional values and drop the blank ones (incl. the secret)."""
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        """Accept lower-case log levels, as the old ``getenv`` reader did."""
        if not isinstance(value, str):
            return value
        return value.strip().upper() or "INFO"

    @property
    def tracing_enabled(self) -> bool:
        """Whether OTLP spans are exported somewhere."""
        return bool(self.otel_exporter_otlp_endpoint)

    @property
    def phoenix_annotation_url(self) -> str | None:
        """Where span annotations are posted, or None to stay silent.

        ``PHOENIX_BASE_URL`` wins over the tracing endpoint, so annotations
        land where the traces do by default without extra configuration.
        """
        for raw in (self.phoenix_base_url, self.otel_exporter_otlp_endpoint):
            if raw:
                return raw.rstrip("/")
        return None

    @property
    def phoenix_ui_url(self) -> str:
        """Phoenix web UI base URL derived from the OTLP endpoint.

        Phoenix serves the UI and the OTLP/HTTP receiver on the same port, so
        the UI origin is scheme + host of the configured endpoint with the
        port forced to :data:`PHOENIX_UI_PORT`.
        """
        parsed = urlsplit(self.otel_exporter_otlp_endpoint or "")
        if not parsed.scheme or not parsed.hostname:
            return DEFAULT_PHOENIX_UI_URL
        return f"{parsed.scheme}://{parsed.hostname}:{PHOENIX_UI_PORT}"


def get_settings() -> Settings:
    """Build the application settings from the current environment.

    Deliberately not cached: construction is cheap and callers such as the
    evaluation harness or the tests change environment variables at runtime.

    returns:
        Settings: the validated configuration for this call.
    """
    return Settings()
