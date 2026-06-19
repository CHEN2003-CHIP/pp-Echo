from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from pp_agent.domain import ChatMessage, CompactionState, PlanStep, QueuedMessage, TurnPhase, ToolCall
from pp_agent.llm.models import ModelConfig


class TurnSnapshot(BaseModel):
    turn_id: int = 0
    phase: TurnPhase = "idle"
    reason: str = ""


class AgentState(BaseModel):
    """
    AgentState.system_prompt/model = 当前程序配置
    AgentState.messages = 当前对话上下文
    AgentState.pending_tool_calls/pending_plan_token = 待审批/待执行计划
    AgentState.queued_messages = 排队消息
    AgentState.compaction = 历史压缩状态
    AgentState.turn = 当前轮次与阶段
    AgentState.is_streaming/error_message = 当前运行标志与错误状态。z
    """
    system_prompt: str
    model: ModelConfig = Field(default_factory=ModelConfig)
    messages: list[ChatMessage] = Field(default_factory=list)
    pending_tool_calls: list[ToolCall] = Field(default_factory=list)
    pending_plan_token: Optional[str] = None
    queued_messages: list[QueuedMessage] = Field(default_factory=list)
    compaction: CompactionState = Field(default_factory=CompactionState)
    turn: TurnSnapshot = Field(default_factory=TurnSnapshot)
    memory_context: dict[str, Any] = Field(default_factory=dict)
    is_streaming: bool = False
    error_message: Optional[str] = None


class AgentEvent(BaseModel):
    """运行时事件模型，包含各种事件类型和相关数据"""
    type: str
    session_id: str = ""
    turn_id: Optional[int] = None
    phase: Optional[str] = None
    timestamp: float = 0.0
    event_id: Optional[str] = None
    run_id: Optional[str] = None
    activity_id: Optional[str] = None
    parent_activity_id: Optional[str] = None
    status: Optional[str] = None
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    duration_ms: Optional[int] = None
    message: Optional[str] = None
    delta: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[dict[str, Any]] = None
    plan_step: Optional[PlanStep] = None
    details: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False
