from __future__ import annotations

import httpx

from pp_agent.llm.connectivity import ModelConnectivityService
from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.llm.provider.anthropic import AnthropicLLMClient
from pp_agent.llm.provider.bailian import BailianLLMClient
from pp_agent.llm.provider.openai_compatible import LLMClient
from pp_agent.llm.providers import list_provider_presets, provider_preset
from pp_agent.llm.registry import create_llm_client


def test_provider_presets_include_required_providers() -> None:
    ids = {preset.id for preset in list_provider_presets()}

    assert {"openai", "deepseek", "qwen-dashscope", "xiaomi", "alibaba-bailian", "anthropic", "custom-openai-compatible"} <= ids
    assert provider_preset("anthropic").protocol == "anthropic"
    assert provider_preset("deepseek").protocol == "openai-compatible"
    assert provider_preset("xiaomi").default_api_key_env == "MIMO_API_KEY"
    assert provider_preset("xiaomi").default_base_url == "https://api.xiaomimimo.com/v1"
    assert "mimo-v2.5-pro" in provider_preset("xiaomi").recommended_models


def test_client_factory_dispatches_by_provider_protocol() -> None:
    assert isinstance(create_llm_client(provider=ProviderConfig(name="anthropic", base_url="https://example.test", api_key_env="ANTHROPIC_API_KEY")), AnthropicLLMClient)
    assert isinstance(create_llm_client(provider=ProviderConfig(name="alibaba-bailian", base_url="https://example.test", api_key_env="PP_AGENT_API_KEY")), BailianLLMClient)
    assert isinstance(create_llm_client(provider=ProviderConfig(name="deepseek", base_url="https://example.test", api_key_env="DEEPSEEK_API_KEY")), LLMClient)


def test_model_connectivity_warns_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_MODEL_KEY", raising=False)

    result = ModelConnectivityService().test(
        ProviderConfig(name="openai", base_url="https://example.test/v1", api_key_env="MISSING_MODEL_KEY"),
        ModelConfig(provider="openai", model="gpt-test"),
    )

    assert result.status == "warning"
    assert result.api_key_env == "MISSING_MODEL_KEY"


def test_model_connectivity_openai_compatible_success(monkeypatch) -> None:
    monkeypatch.setenv("TEST_MODEL_KEY", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, json={"id": "req-1", "choices": [{"message": {"content": "OK"}}]})

    service = ModelConnectivityService(httpx.Client(transport=httpx.MockTransport(handler)))
    result = service.test(
        ProviderConfig(name="openai", base_url="https://example.test/v1", api_key_env="TEST_MODEL_KEY"),
        ModelConfig(provider="openai", model="gpt-test"),
    )

    assert result.status == "ok"
    assert "req-1" in result.safe_detail


def test_model_connectivity_anthropic_http_error(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_TEST_KEY", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "secret"
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    service = ModelConnectivityService(httpx.Client(transport=httpx.MockTransport(handler)))
    result = service.test(
        ProviderConfig(name="anthropic", base_url="https://example.test/v1", api_key_env="ANTHROPIC_TEST_KEY"),
        ModelConfig(provider="anthropic", model="claude-test"),
    )

    assert result.status == "error"
    assert result.retryable is False
    assert "invalid key" in result.safe_detail
