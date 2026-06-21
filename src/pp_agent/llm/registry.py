from __future__ import annotations

from typing import Optional

import httpx

from pp_agent.llm.model_profile import (
    ModelCapabilities,
    ModelCapabilityProfile,
    ModelLimits,
    ModelQualityHints,
    ModelRuntimeHints,
)
from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.llm.provider.base import BaseLLMClient
from pp_agent.llm.provider.anthropic import AnthropicLLMClient
from pp_agent.llm.provider.bailian import BailianLLMClient
from pp_agent.llm.provider.openai_compatible import LLMClient
from pp_agent.llm.providers import list_provider_presets, provider_preset, provider_protocol


def create_llm_client(
    *,
    provider: Optional[ProviderConfig] = None,
    model: Optional[ModelConfig] = None,
    client: Optional[httpx.Client] = None,
) -> BaseLLMClient:
    """Create the concrete LLM client for the configured provider protocol."""
    effective_provider = provider or ProviderConfig()
    if provider_protocol(effective_provider.name) == "anthropic":
        return AnthropicLLMClient(provider=effective_provider, model=model, client=client)
    if effective_provider.name == "alibaba-bailian":
        return BailianLLMClient(provider=effective_provider, model=model, client=client)
    return LLMClient(provider=effective_provider, model=model, client=client)


def list_model_profiles() -> list[ModelCapabilityProfile]:
    """
    Return configured model profiles derived from provider presets.

    These profiles are intentionally conservative: they describe only broad provider
    defaults and recommended model ids, while precise model capability curation can be
    added later without changing the public provider factory.
    """
    profiles: list[ModelCapabilityProfile] = []
    for preset in list_provider_presets():
        for model_id in preset.recommended_models:
            profiles.append(_profile_from_preset(preset.id, model_id, source="configured"))
    return profiles


def get_model_profile(provider_id: str, model_id: str) -> ModelCapabilityProfile | None:
    """Return a configured profile only when the provider preset recommends model_id."""
    preset = provider_preset(provider_id)
    if provider_id != preset.id:
        return None
    if model_id not in preset.recommended_models:
        return None
    return _profile_from_preset(provider_id, model_id, source="configured")


def infer_model_profile(provider_id: str, model_id: str) -> ModelCapabilityProfile:
    """
    Resolve a model profile without raising for unknown providers or models.

    Unknown values use a conservative inferred profile. Known providers may contribute
    broad defaults such as tool or streaming support, but uncertain per-model features
    remain false or None until explicitly configured.
    """
    configured = get_model_profile(provider_id, model_id)
    if configured is not None:
        return configured
    preset = provider_preset(provider_id)
    if provider_id == preset.id:
        return _profile_from_preset(provider_id, model_id, source="inferred")
    return ModelCapabilityProfile(
        provider_id=provider_id or "unknown",
        model_id=model_id or "unknown",
        display_name=model_id or None,
        capabilities=ModelCapabilities(),
        runtime_hints=ModelRuntimeHints(preferred_runtime="pp_echo_native"),
        metadata={"source": "inferred", "known_provider": False},
    )


def _profile_from_preset(provider_id: str, model_id: str, *, source: str) -> ModelCapabilityProfile:
    preset = provider_preset(provider_id)
    family = _model_family(model_id)
    return ModelCapabilityProfile(
        provider_id=provider_id,
        model_id=model_id or "unknown",
        display_name=model_id or None,
        family=family,
        capabilities=ModelCapabilities(
            tool_calling=bool(preset.supports_tools),
            json_mode=bool(preset.supports_tools),
            streaming=bool(preset.supports_streaming),
            vision=_looks_like_vision_model(model_id),
            long_context=_looks_like_long_context_model(model_id),
            reasoning_mode=bool(preset.supports_thinking or _looks_like_reasoning_model(model_id)),
            structured_output=bool(preset.supports_tools),
        ),
        limits=ModelLimits(
            context_window=_conservative_context_window(model_id),
            max_output_tokens=None,
        ),
        quality_hints=ModelQualityHints(
            good_for=_good_for(provider_id, model_id),
            avoid_for=[],
        ),
        runtime_hints=ModelRuntimeHints(
            preferred_runtime="pp_echo_native",
            compatible_runtimes=["pp_echo_native"],
        ),
        metadata={
            "source": source,
            "known_provider": True,
            "provider_label": preset.label,
            "capability_basis": "provider_preset",
        },
    )


def _model_family(model_id: str) -> str | None:
    lowered = (model_id or "").lower()
    for prefix in ("gpt", "qwen", "deepseek", "claude", "xiaoai", "mi"):
        if lowered.startswith(prefix):
            return prefix
    return None


def _looks_like_vision_model(model_id: str) -> bool:
    lowered = (model_id or "").lower()
    return any(marker in lowered for marker in ("vision", "vl", "gpt-4o"))


def _looks_like_long_context_model(model_id: str) -> bool:
    lowered = (model_id or "").lower()
    return any(marker in lowered for marker in ("128k", "200k", "1m", "long"))


def _looks_like_reasoning_model(model_id: str) -> bool:
    lowered = (model_id or "").lower()
    return any(marker in lowered for marker in ("reasoner", "thinking", "r1", "o1", "o3", "o4"))


def _conservative_context_window(model_id: str) -> int | None:
    lowered = (model_id or "").lower()
    if "128k" in lowered:
        return 128_000
    if "200k" in lowered:
        return 200_000
    if "32k" in lowered:
        return 32_000
    return None


def _good_for(provider_id: str, model_id: str) -> list[str]:
    lowered = f"{provider_id} {model_id}".lower()
    hints: list[str] = []
    if "reason" in lowered or "thinking" in lowered:
        hints.append("reasoning")
    if "qwen" in lowered or "deepseek" in lowered:
        hints.append("coding")
    if "gpt" in lowered or "claude" in lowered:
        hints.append("general_agent_tasks")
    return hints
