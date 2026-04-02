from __future__ import annotations

from pydantic import BaseModel


class UsageSnapshot(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
