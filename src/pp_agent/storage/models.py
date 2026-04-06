from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict
from rootenv_loader import env
# 大模型【提供商】配置（对接阿里云百炼）
class StoredProviderConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = "alibaba-bailian"
    base_url: str = env("base_url")
    api_key_env: str = "PP_AGENT_API_KEY"

# 大模型【具体参数】配置
class StoredModelConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str = "alibaba-bailian"
    model: str = env("model_name")
    temperature: float = 0.2
    max_tokens: Optional[int] = None
    enable_thinking: bool = False
