from __future__ import annotations

from typing import Optional

import httpx

from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.llm.provider.base import BaseLLMClient
from pp_agent.llm.provider.anthropic import AnthropicLLMClient
from pp_agent.llm.provider.bailian import BailianLLMClient
from pp_agent.llm.provider.openai_compatible import LLMClient
from pp_agent.llm.providers import provider_protocol


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
