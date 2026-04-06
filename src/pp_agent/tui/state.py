from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass
class TuiMessage:
    role: MessageRole
    text: str


@dataclass
class ActiveAssistantMessage:
    text: str = ""
    streaming: bool = False


@dataclass
class TuiPlanStep:
    title: str
    tool_name: Optional[str] = None
    status: str = "pending"


@dataclass
class QueueSummary:
    queue_count: int = 0
    steering_count: int = 0
    follow_up_count: int = 0
    latest_action: str = ""


@dataclass
class ApprovalState:
    pending_plan_token: Optional[str] = None
    awaiting_approval: bool = False
    prompt: str = ""


@dataclass
class RuntimePhase:
    session_id: str = ""
    turn_id: int = 0
    phase: str = "idle"
    reason: str = ""
    pending_tool_count: int = 0
    queue_count: int = 0
    busy: bool = False


@dataclass
class TuiState:
    messages: list[TuiMessage] = field(default_factory=list)
    active_assistant_message: ActiveAssistantMessage = field(default_factory=ActiveAssistantMessage)
    plan_steps: list[TuiPlanStep] = field(default_factory=list)
    queue_summary: QueueSummary = field(default_factory=QueueSummary)
    approval_state: ApprovalState = field(default_factory=ApprovalState)
    runtime_phase: RuntimePhase = field(default_factory=RuntimePhase)
    ephemeral_logs: list[str] = field(default_factory=list)


def append_log(state: TuiState, message: str, *, limit: int = 100) -> None:
    if not message:
        return
    state.ephemeral_logs.append(message)
    if len(state.ephemeral_logs) > limit:
        del state.ephemeral_logs[:-limit]
