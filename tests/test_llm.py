import pytest
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.llm import (
    MAX_OUTPUT_TOKENS,
    LLMConfigurationError,
    get_chat_model,
    llm_error_hint,
    normalize_base_url,
)


def test_no_provider_raises(monkeypatch):
    """Without a provider the factory reports a configuration error."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    with pytest.raises(LLMConfigurationError, match="No LLM provider"):
        get_chat_model()


def test_rule_based_provider_is_unknown(monkeypatch):
    """The removed rule-based provider is no longer supported."""
    monkeypatch.setenv("LLM_PROVIDER", "rule-based")
    with pytest.raises(LLMConfigurationError, match="Unknown LLM_PROVIDER"):
        get_chat_model()


def test_openai_needs_key(monkeypatch):
    """OpenAI requires an API key."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError, match="requires LLM_API_KEY"):
        get_chat_model()


def test_openrouter_needs_key(monkeypatch):
    """OpenRouter requires an API key."""
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError, match="requires LLM_API_KEY"):
        get_chat_model()


def test_anthropic_needs_key(monkeypatch):
    """Anthropic requires an API key."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError, match="requires LLM_API_KEY"):
        get_chat_model()


def test_google_needs_key(monkeypatch):
    """Google requires an API key."""
    monkeypatch.setenv("LLM_PROVIDER", "google")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError, match="requires LLM_API_KEY"):
        get_chat_model()


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


def test_unknown_provider_raises(monkeypatch):
    """Unknown providers are configuration errors."""
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    with pytest.raises(LLMConfigurationError, match="Unknown LLM_PROVIDER"):
        get_chat_model()


def test_provider_parameter_overrides_env(monkeypatch):
    """A provider passed directly overrides LLM_PROVIDER."""
    monkeypatch.setenv("LLM_PROVIDER", "rule-based")
    with pytest.raises(LLMConfigurationError):
        get_chat_model()
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
    with pytest.raises(LLMConfigurationError):
        get_chat_model()
    assert isinstance(get_chat_model(api_key="secret"), ChatOpenAI)


def test_local_base_url_gets_the_openai_path():
    """A bare host for a local server becomes its /v1 endpoint."""
    assert normalize_base_url("ollama", "http://localhost:11434") == "http://localhost:11434/v1"
    assert normalize_base_url("lmstudio", "http://localhost:1234/") == "http://localhost:1234/v1"


def test_local_base_url_with_a_path_is_kept():
    """An explicit path is never rewritten."""
    assert normalize_base_url("ollama", "http://localhost:11434/v1") == "http://localhost:11434/v1"
    assert normalize_base_url("ollama", "http://host/custom") == "http://host/custom"


def test_cloud_base_url_is_never_rewritten():
    """Cloud providers keep the URL the user configured."""
    assert normalize_base_url("openai", "https://api.openai.com") == "https://api.openai.com"
    assert normalize_base_url("openrouter", "https://openrouter.ai/api/v1") == (
        "https://openrouter.ai/api/v1"
    )


def test_ollama_base_url_override_is_normalized(monkeypatch):
    """The factory applies the /v1 path to a bare LLM_BASE_URL."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
    model = get_chat_model()
    assert model.openai_api_base.rstrip("/").endswith("/v1")


def test_error_hint_points_at_the_base_url():
    """A 404 tells the user which setting to check."""
    assert "LLM_BASE_URL" in llm_error_hint(Exception("404 page not found"))


def test_error_hint_points_at_the_api_key():
    """An authentication failure tells the user which setting to check."""
    assert "LLM_API_KEY" in llm_error_hint(Exception("Error code: 401 - invalid api key"))


def test_error_hint_points_at_the_server():
    """A connection failure tells the user the server may be down."""
    assert "server" in llm_error_hint(Exception("Connection refused"))


def test_error_hint_is_empty_for_unknown_failures():
    """An unknown failure gets no guess."""
    assert llm_error_hint(Exception("boom")) == ""


def test_error_hint_points_at_the_output_cap():
    """A cut-off answer points at the token cap."""
    assert "MAX_OUTPUT_TOKENS" in llm_error_hint(Exception("Expecting value: line 1 column 1"))


def test_generated_output_is_capped(monkeypatch):
    """Every provider caps the tokens one call may generate."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    model = get_chat_model()
    assert model.max_tokens == MAX_OUTPUT_TOKENS
