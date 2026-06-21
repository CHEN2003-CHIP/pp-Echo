from __future__ import annotations

from typing import Dict, List, Literal

from pydantic import BaseModel, Field


ProviderProtocol = Literal["openai-compatible", "anthropic"]


class ProviderPreset(BaseModel):
    """Describes one selectable model provider without storing any secret value."""

    id: str
    label: str
    protocol: ProviderProtocol
    default_base_url: str
    default_api_key_env: str
    recommended_models: List[str] = Field(default_factory=list)
    supports_thinking: bool = False
    supports_streaming: bool = True
    supports_tools: bool = False
    notes: str = ""


_PRESETS: Dict[str, ProviderPreset] = {
    "openai": ProviderPreset(
        id="openai",
        label="OpenAI / ChatGPT",
        protocol="openai-compatible",
        default_base_url="https://api.openai.com/v1",
        default_api_key_env="OPENAI_API_KEY",
        recommended_models=["gpt-4.1", "gpt-4o", "gpt-4o-mini"],
        supports_tools=True,
    ),
    "deepseek": ProviderPreset(
        id="deepseek",
        label="DeepSeek",
        protocol="openai-compatible",
        default_base_url="https://api.deepseek.com",
        default_api_key_env="DEEPSEEK_API_KEY",
        recommended_models=["deepseek-chat", "deepseek-reasoner", "deepseek-v4"],
        supports_thinking=True,
        supports_tools=True,
    ),
    "qwen-dashscope": ProviderPreset(
        id="qwen-dashscope",
        label="Qwen / DashScope",
        protocol="openai-compatible",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_api_key_env="DASHSCOPE_API_KEY",
        recommended_models=["qwen-plus", "qwen-max", "qwen3-max-2026-01-23"],
        supports_thinking=True,
        supports_tools=True,
    ),
    "xiaomi": ProviderPreset(
        id="xiaomi",
        label="Xiaomi Model",
        protocol="openai-compatible",
        default_base_url="https://api.xiaomi.com/v1",
        default_api_key_env="XIAOMI_API_KEY",
        recommended_models=["xiaoai-large", "mi-large"],
        supports_tools=False,
        notes="Override the base URL if your Xiaomi model endpoint uses a tenant-specific address.",
    ),
    "alibaba-bailian": ProviderPreset(
        id="alibaba-bailian",
        label="Alibaba Bailian",
        protocol="openai-compatible",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_api_key_env="PP_AGENT_API_KEY",
        recommended_models=["qwen3-max-2026-01-23", "qwen-plus", "qwen-max"],
        supports_thinking=True,
        supports_tools=True,
    ),
    "anthropic": ProviderPreset(
        id="anthropic",
        label="Anthropic Claude",
        protocol="anthropic",
        default_base_url="https://api.anthropic.com/v1",
        default_api_key_env="ANTHROPIC_API_KEY",
        recommended_models=["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"],
        supports_tools=False,
    ),
    "custom-openai-compatible": ProviderPreset(
        id="custom-openai-compatible",
        label="Custom OpenAI-compatible",
        protocol="openai-compatible",
        default_base_url="",
        default_api_key_env="PP_AGENT_API_KEY",
        recommended_models=[],
        supports_tools=True,
        notes="Use this for proxies or providers that expose /chat/completions.",
    ),
}


def list_provider_presets() -> List[ProviderPreset]:
    """Return stable provider presets in UI display order."""

    return list(_PRESETS.values())


def provider_preset(provider_id: str) -> ProviderPreset:
    """Resolve a provider preset, falling back to custom OpenAI-compatible behavior."""

    return _PRESETS.get(provider_id) or _PRESETS["custom-openai-compatible"]


def provider_protocol(provider_id: str) -> ProviderProtocol:
    return provider_preset(provider_id).protocol
