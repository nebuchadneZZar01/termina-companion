"""LLM provider factory.

Reads provider configuration from environment variables. A usable LLM is
required by the Planning Agent; invalid or incomplete configuration raises
:class:`LLMConfigurationError` instead of selecting an alternate planner.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

load_dotenv()

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


class LLMConfigurationError(RuntimeError):
    """Raised when no usable LLM provider is configured."""


def get_chat_model(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> BaseChatModel:
    """Return a configured chat model.

    All parameters override the corresponding ``LLM_*`` env vars when
    provided (non-empty string).

    raises:
        LLMConfigurationError: if the provider is missing, unsupported or lacks
            required credentials.
    """
    provider = (provider or os.getenv("LLM_PROVIDER", "")).strip().lower()
    if not provider:
        raise LLMConfigurationError(
            "No LLM provider configured. Set LLM_PROVIDER to a supported provider."
        )
    if provider == "rule-based":
        raise LLMConfigurationError(
            "The rule-based provider is no longer supported; configure an LLM provider."
        )
    model = (model or os.getenv("LLM_MODEL", "")).strip() or None
    api_key = (api_key or os.getenv("LLM_API_KEY", "")).strip() or None

    if provider in _OPENAI_COMPATIBLE:
        default_url, default_model = _OPENAI_COMPATIBLE[provider]
        if api_key is None and provider in {"openai", "openrouter"}:
            raise LLMConfigurationError(f"Provider {provider!r} requires LLM_API_KEY")
        chat = ChatOpenAI(
            model=model or default_model,
            api_key=api_key or "not-needed",
            base_url=(base_url or os.getenv("LLM_BASE_URL", "")).strip() or default_url,
        )
        logger.info(
            "LLM provider=%s model=%s base_url=%s", provider, chat.model_name, chat.openai_api_base
        )
        return chat
    if provider == "anthropic":
        if api_key is None:
            raise LLMConfigurationError("Provider 'anthropic' requires LLM_API_KEY")
        return ChatAnthropic(model=model or _ANTHROPIC_DEFAULT_MODEL, api_key=api_key)
    if provider == "google":
        if api_key is None:
            raise LLMConfigurationError("Provider 'google' requires LLM_API_KEY")
        return ChatGoogleGenerativeAI(model=model or _GOOGLE_DEFAULT_MODEL, api_key=api_key)
    raise LLMConfigurationError(f"Unknown LLM_PROVIDER {provider!r}")
