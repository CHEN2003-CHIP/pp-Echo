from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """Specification for a tool that can be called by the agent."""
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False
    permission_domain: str = "read"
    sensitive: bool = False
    model_callable: bool = True


class ToolCall(BaseModel):
    """A call to a tool with its arguments."""
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Result of executing a tool call."""
    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
