from __future__ import annotations

from pydantic import BaseModel


class UsageSnapshot(BaseModel):
    """LLM使用情况快照"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
