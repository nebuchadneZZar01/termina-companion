from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.llm import get_chat_model


def test_no_credentials_returns_none(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert get_chat_model() is None
    monkeypatch.setenv("LLM_PROVIDER", "rule-based")
    assert get_chat_model() is None


def test_openai_needs_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert get_chat_model() is None


def test_openrouter_needs_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert get_chat_model() is None


def test_anthropic_needs_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert get_chat_model() is None


def test_google_needs_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "google")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert get_chat_model() is None


def test_ollama_works_without_real_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    model = get_chat_model()
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "llama3.2"
    assert "11434" in model.openai_api_base


def test_lmstudio_defaults(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "lmstudio")
    monkeypatch.setenv("LLM_API_KEY", "x")
    model = get_chat_model()
    assert isinstance(model, ChatOpenAI)
    assert "1234" in model.openai_api_base


def test_openai_compatible_base_url_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:9999/v1")
    assert "9999" in get_chat_model().openai_api_base


def test_anthropic_builds_chat_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    assert isinstance(get_chat_model(), ChatAnthropic)


def test_google_builds_chat_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "google")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    assert isinstance(get_chat_model(), ChatGoogleGenerativeAI)


def test_unknown_provider_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    assert get_chat_model() is None
