from __future__ import annotations

from typing import Optional

import httpx

from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.llm.provider.openai_compatible import LLMClient


class BailianLLMClient(LLMClient):
    def __init__(
        self,
        provider: Optional[ProviderConfig] = None,
        model: Optional[ModelConfig] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        provider = provider or ProviderConfig(
            name="alibaba-bailian",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key_env="PP_AGENT_API_KEY",
        )
        model = model or ModelConfig(provider="alibaba-bailian")
        super().__init__(provider=provider, model=model, client=client)
