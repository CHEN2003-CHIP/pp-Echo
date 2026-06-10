from __future__ import annotations

import os
from typing import Optional

from pydantic import BaseModel
from rootenv_loader import env

class ProviderConfig(BaseModel):
    """LLM提供者配置"""
    name: str = env("provider_name") or"alibaba-bailian"
    base_url: str = env("base_url") 
    api_key_env: str = "PP_AGENT_API_KEY"


class ModelConfig(BaseModel):
    """LLM模型配置"""
    provider: str = env("provider_name") or"alibaba-bailian"
    model: str = env("model_name") or "qwen3-max-2026-01-23"
    temperature: float = 0.2
    max_tokens: Optional[int] = None
    enable_thinking: bool = False
