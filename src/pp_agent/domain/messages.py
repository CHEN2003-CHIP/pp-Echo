from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class TextPart(BaseModel):
    """ A simple text content part of a chat message."""
    type: Literal["text"] = "text"
    text: str


class ToolCallPart(BaseModel):
    """" A part of a chat message that represents a call to a tool, which can be rendered as a button or similar UI element."""
    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


ContentPart = Union[TextPart, ToolCallPart]


class ChatMessage(BaseModel):
    """ A chat message that can contain text and/or tool calls. """
    role: Literal["system", "user", "assistant", "tool"]
    content: list[ContentPart] = Field(default_factory=list)
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    timestamp: float
