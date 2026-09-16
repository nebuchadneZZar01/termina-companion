"""LLM provider factory.

Reads provider configuration from environment variables. Returns ``None``
without credentials so every agent falls back to its deterministic rule-based
brain and the demo stays runnable with no API keys.
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


def get_chat_model() -> BaseChatModel | None:
    """Return a configured chat model, or None when nothing is configured."""
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not provider or provider == "rule-based":
        logger.info("No LLM configured (provider=%r) — rule-based brains active", provider)
        return None
    model = os.getenv("LLM_MODEL", "").strip() or None
    api_key = os.getenv("LLM_API_KEY", "").strip() or None

    if provider in _OPENAI_COMPATIBLE:
        default_url, default_model = _OPENAI_COMPATIBLE[provider]
        if api_key is None and provider in {"openai", "openrouter"}:
            logger.warning("Provider %r requires LLM_API_KEY — rule-based brains active", provider)
            return None
        chat = ChatOpenAI(
            model=model or default_model,
            api_key=api_key or "not-needed",
            base_url=os.getenv("LLM_BASE_URL", "").strip() or default_url,
        )
        logger.info(
            "LLM provider=%s model=%s base_url=%s", provider, chat.model_name, chat.openai_api_base
        )
        return chat
    if provider == "anthropic":
        if api_key is None:
            logger.warning("Provider %r requires LLM_API_KEY — rule-based brains active", provider)
            return None
        return ChatAnthropic(model=model or _ANTHROPIC_DEFAULT_MODEL, api_key=api_key)
    if provider == "google":
        if api_key is None:
            logger.warning("Provider %r requires LLM_API_KEY — rule-based brains active", provider)
            return None
        return ChatGoogleGenerativeAI(model=model or _GOOGLE_DEFAULT_MODEL, api_key=api_key)
    logger.warning("Unknown LLM_PROVIDER %r — rule-based brains active", provider)
    return None
