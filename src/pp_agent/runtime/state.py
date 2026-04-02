from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from pp_agent.domain import ChatMessage, CompactionState, PlanStep, QueuedMessage, TurnPhase, ToolCall
from pp_agent.llm.models import ModelConfig


class TurnSnapshot(BaseModel):
    turn_id: int = 0
    phase: TurnPhase = "idle"
    reason: str = ""


class AgentState(BaseModel):
    system_prompt: str
    model: ModelConfig = Field(default_factory=ModelConfig)
    messages: list[ChatMessage] = Field(default_factory=list)
    pending_tool_calls: list[ToolCall] = Field(default_factory=list)
    pending_plan_token: Optional[str] = None
    queued_messages: list[QueuedMessage] = Field(default_factory=list)
    compaction: CompactionState = Field(default_factory=CompactionState)
    turn: TurnSnapshot = Field(default_factory=TurnSnapshot)
    is_streaming: bool = False
    error_message: Optional[str] = None


class AgentEvent(BaseModel):
    type: Literal[
        "agent_start",
        "turn_start",
        "planner_start",
        "planner_step",
        "planner_end",
        "message_delta",
        "tool_start",
        "tool_end",
        "turn_end",
        "agent_end",
        "error",
        "compaction",
        "queue_update",
        "turn_state",
    ]
    message: Optional[str] = None
    delta: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[dict[str, Any]] = None
    plan_step: Optional[PlanStep] = None
    details: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False
