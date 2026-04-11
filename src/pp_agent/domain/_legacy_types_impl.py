from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    name: str = "alibaba-bailian"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key_env: str = "PP_AGENT_API_KEY"


class ModelConfig(BaseModel):
    provider: str = "alibaba-bailian"
    model: str = "qwen3.5-plus"
    temperature: float = 0.2
    max_tokens: Optional[int] = None
    enable_thinking: bool = False


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
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: float


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class CompactionState(BaseModel):
    summary: str = ""
    summarized_message_count: int = 0
