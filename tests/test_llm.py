from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.llm import get_chat_model


def test_no_credentials_returns_none(monkeypatch):
    """Without env vars the provider factory returns None."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert get_chat_model() is None
    monkeypatch.setenv("LLM_PROVIDER", "rule-based")
    assert get_chat_model() is None


def test_openai_needs_key(monkeypatch):
    """OpenAI requires an API key."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert get_chat_model() is None


def test_openrouter_needs_key(monkeypatch):
    """OpenRouter requires an API key."""
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert get_chat_model() is None


def test_anthropic_needs_key(monkeypatch):
    """Anthropic requires an API key."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert get_chat_model() is None


def test_google_needs_key(monkeypatch):
    """Google requires an API key."""
    monkeypatch.setenv("LLM_PROVIDER", "google")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert get_chat_model() is None


def test_ollama_works_without_real_key(monkeypatch):
    """Ollama builds a local ChatOpenAI without an API key."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    model = get_chat_model()
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "llama3.2"
    assert "11434" in model.openai_api_base


def test_lmstudio_defaults(monkeypatch):
    """LM Studio builds a ChatOpenAI pointed at its default port."""
    monkeypatch.setenv("LLM_PROVIDER", "lmstudio")
    monkeypatch.setenv("LLM_API_KEY", "x")
    model = get_chat_model()
    assert isinstance(model, ChatOpenAI)
    assert "1234" in model.openai_api_base


def test_openai_compatible_base_url_override(monkeypatch):
    """LLM_BASE_URL overrides the base_url of a ChatOpenAI model."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:9999/v1")
    assert "9999" in get_chat_model().openai_api_base


def test_anthropic_builds_chat_model(monkeypatch):
    """Anthropic provider builds a ChatAnthropic model."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    assert isinstance(get_chat_model(), ChatAnthropic)


def test_google_builds_chat_model(monkeypatch):
    """Google provider builds a ChatGoogleGenerativeAI model."""
    monkeypatch.setenv("LLM_PROVIDER", "google")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    assert isinstance(get_chat_model(), ChatGoogleGenerativeAI)


def test_unknown_provider_falls_back(monkeypatch):
    """Unknown providers fall back to None."""
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    assert get_chat_model() is None


def test_provider_parameter_overrides_env(monkeypatch):
    """A provider passed directly overrides LLM_PROVIDER."""
    monkeypatch.setenv("LLM_PROVIDER", "rule-based")
    assert get_chat_model() is None
    assert isinstance(get_chat_model(provider="ollama"), ChatOpenAI)


def test_model_parameter_overrides_default(monkeypatch):
    """A model passed directly overrides the provider default."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    model = get_chat_model(model="custom-model")
    assert model.model_name == "custom-model"


def test_api_key_parameter_enables_openai(monkeypatch):
    """An API key passed directly enables an otherwise keyless OpenAI setup."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert get_chat_model() is None
    assert isinstance(get_chat_model(api_key="secret"), ChatOpenAI)
