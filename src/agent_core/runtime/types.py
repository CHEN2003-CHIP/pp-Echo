from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from agent_core.types import ChatMessage, CompactionState, ModelConfig, ToolCall


class AgentState(BaseModel):
    system_prompt: str
    model: ModelConfig = Field(default_factory=ModelConfig)
    messages: list[ChatMessage] = Field(default_factory=list)
    pending_tool_calls: list[ToolCall] = Field(default_factory=list)
    compaction: CompactionState = Field(default_factory=CompactionState)
    is_streaming: bool = False
    error_message: Optional[str] = None


class AgentEvent(BaseModel):
    type: Literal[
        "agent_start",
        "turn_start",
        "message_delta",
        "tool_start",
        "tool_end",
        "turn_end",
        "agent_end",
        "error",
        "compaction",
    ]
    message: Optional[str] = None
    delta: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[dict[str, Any]] = None
    details: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False