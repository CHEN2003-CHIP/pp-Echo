from __future__ import annotations

from pydantic import BaseModel


class ToolMetadata(BaseModel):
    name: str
    category: str
    requires_confirmation: bool = False
