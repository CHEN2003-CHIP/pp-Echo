from __future__ import annotations

from typing import Optional

import httpx

from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.llm.provider.bailian import BailianLLMClient
from pp_agent.llm.provider.openai_compatible import LLMClient


def create_llm_client(
    *,
    provider: Optional[ProviderConfig] = None,
    model: Optional[ModelConfig] = None,
    client: Optional[httpx.Client] = None,
) -> LLMClient:
    effective_provider = provider or ProviderConfig()
    if effective_provider.name == "alibaba-bailian":
        return BailianLLMClient(provider=effective_provider, model=model, client=client)
    return LLMClient(provider=effective_provider, model=model, client=client)
