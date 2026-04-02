from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class StoredProviderConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = "alibaba-bailian"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key_env: str = "PP_AGENT_API_KEY"


class StoredModelConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str = "alibaba-bailian"
    model: str = "qwen3.5-plus"
    temperature: float = 0.2
    max_tokens: Optional[int] = None
    enable_thinking: bool = False
