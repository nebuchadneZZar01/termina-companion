"""LLM provider factory.

Reads provider configuration from environment variables. A usable LLM is
required by the Planning Agent; invalid or incomplete configuration raises
:class:`LLMConfigurationError` instead of selecting an alternate planner.
"""

from __future__ import annotations

import logging
import warnings
from urllib.parse import urlsplit

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.settings import get_settings

logger = logging.getLogger(__name__)

# provider -> (default base URL, default model). The four OpenAI-compatible
# providers share the ChatOpenAI class and only differ in endpoint and model.
_OPENAI_COMPATIBLE: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
    "ollama": ("http://localhost:11434/v1", "llama3.2"),
    "lmstudio": ("http://localhost:1234/v1", "local-model"),
}

_ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-5"
_GOOGLE_DEFAULT_MODEL = "gemini-2.5-flash"

# Providers served by a local OpenAI-compatible server. Their endpoint lives
# under the "/v1" path, so a bare host in LLM_BASE_URL is normalized to it.
_LOCAL_OPENAI_COMPATIBLE = frozenset({"ollama", "lmstudio"})

# Cap on the tokens one LLM call may generate. A plan needs a few hundred
# tokens, so the cap is generous for a real answer but stops a runaway
# generation (a local model looping) from blocking the pipeline forever.
MAX_OUTPUT_TOKENS = 1536


def default_model_for(provider: str) -> str | None:
    """Return the model a provider uses when ``LLM_MODEL`` is unset.

    args:
        provider (str): the normalized provider name.

    returns:
        str | None: the built-in default model, or None for an unknown provider.
    """
    if provider in _OPENAI_COMPATIBLE:
        return _OPENAI_COMPATIBLE[provider][1]
    if provider == "anthropic":
        return _ANTHROPIC_DEFAULT_MODEL
    if provider == "google":
        return _GOOGLE_DEFAULT_MODEL
    return None


def normalize_base_url(provider: str, base_url: str) -> str:
    """Return the base URL to use for a provider.

    A local OpenAI-compatible server (Ollama, LM Studio) exposes its API
    under ``/v1``. When ``LLM_BASE_URL`` names only the host, the path is
    added: without it every request hits a missing route and the server
    answers "404 page not found".

    args:
        provider (str): the normalized provider name.
        base_url (str): the configured base URL.

    returns:
        str: the base URL to use, with a trailing slash removed.
    """
    cleaned = base_url.strip().rstrip("/")
    if not cleaned or provider not in _LOCAL_OPENAI_COMPATIBLE:
        return cleaned
    if urlsplit(cleaned).path in {"", "/"}:
        normalized = f"{cleaned}/v1"
        logger.warning(
            "LLM: base_url %s normalized to %s for provider %s", base_url, normalized, provider
        )
        return normalized
    return cleaned


def llm_error_hint(exc: Exception) -> str:
    """Return a short hint about why an LLM call failed.

    args:
        exc (Exception): the failure raised by the provider client.

    returns:
        str: a hint to append to the error message, empty when unknown.
    """
    text = str(exc).lower()
    if "404" in text:
        return (
            " — check LLM_BASE_URL: the OpenAI-compatible path is required "
            "(e.g. http://localhost:11434/v1)"
        )
    if "401" in text or "403" in text:
        return " — check LLM_API_KEY"
    if "connection" in text or "refused" in text or "timed out" in text:
        return " — check that the LLM server is running at LLM_BASE_URL"
    if "json" in text or "unterminated" in text or "expecting value" in text:
        return (
            " — the model output was not valid JSON; it may have been cut off "
            f"(MAX_OUTPUT_TOKENS={MAX_OUTPUT_TOKENS})"
        )
    return ""


class LLMConfigurationError(RuntimeError):
    """Raised when no usable LLM provider is configured."""


def get_chat_model(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> BaseChatModel:
    """Return a configured chat model.

    All parameters override the corresponding ``LLM_*`` settings when
    provided (non-empty string).

    raises:
        LLMConfigurationError: if the provider is missing, unsupported or lacks
            required credentials.
    """
    settings = get_settings()
    provider = (provider or settings.llm_provider or "").strip().lower()
    if not provider:
        raise LLMConfigurationError(
            "No LLM provider configured. Set LLM_PROVIDER to a supported provider."
        )
    model = (model or settings.llm_model or "").strip() or None
    stored_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    api_key = (api_key or stored_key).strip() or None
    base_url = (base_url or settings.llm_base_url or "").strip()

    if provider in _OPENAI_COMPATIBLE:
        default_url, default_model = _OPENAI_COMPATIBLE[provider]
        if api_key is None and provider in {"openai", "openrouter"}:
            raise LLMConfigurationError(f"Provider {provider!r} requires LLM_API_KEY")
        chat = ChatOpenAI(
            model=model or default_model,
            api_key=api_key or "not-needed",
            base_url=normalize_base_url(provider, base_url or default_url),
            max_tokens=MAX_OUTPUT_TOKENS,
        )
        logger.info(
            "LLM provider=%s model=%s base_url=%s", provider, chat.model_name, chat.openai_api_base
        )
        return chat
    if provider == "anthropic":
        if api_key is None:
            raise LLMConfigurationError("Provider 'anthropic' requires LLM_API_KEY")
        return ChatAnthropic(
            model=model or _ANTHROPIC_DEFAULT_MODEL,
            api_key=api_key,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
    if provider == "google":
        if api_key is None:
            raise LLMConfigurationError("Provider 'google' requires LLM_API_KEY")
        # google-genai still imports typing._UnionGenericAlias, which Python
        # 3.14 deprecates. Keep the warning out of normal runs and load the
        # provider only when it is actually selected.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="'_UnionGenericAlias' is deprecated.*",
                category=DeprecationWarning,
                module=r"google\.genai\.types",
            )
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=model or _GOOGLE_DEFAULT_MODEL,
                api_key=api_key,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )
    raise LLMConfigurationError(f"Unknown LLM_PROVIDER {provider!r}")
