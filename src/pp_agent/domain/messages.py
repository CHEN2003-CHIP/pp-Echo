from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolCallPart(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


ContentPart = Union[TextPart, ToolCallPart]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: list[ContentPart] = Field(default_factory=list)
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    timestamp: float
