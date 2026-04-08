from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


MessageRole = Literal["system", "user", "assistant", "tool"]
LogLevel = Literal["info", "warning", "error", "success"]


@dataclass
class TuiMessage:
    id: str
    role: MessageRole
    text: str
    highlight: bool = False
    muted: bool = False
    kind: Literal["message", "status"] = "message"


@dataclass
class ActiveAssistantMessage:
    text: str = ""
    streaming: bool = False
    started_at: float = 0.0
    has_content: bool = False


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
    actionable: bool = False
    status_label: str = "clear"
    token_preview: str = ""


@dataclass
class RuntimePhase:
    session_id: str = ""
    turn_id: int = 0
    phase: str = "idle"
    reason: str = ""
    pending_tool_count: int = 0
    queue_count: int = 0
    busy: bool = False
    status_line: str = ""


@dataclass
class EphemeralLogEntry:
    message: str
    level: LogLevel = "info"
    important: bool = False


@dataclass
class ComposerState:
    prompt_prefix: str = ">"
    mode_label: str = "READY"
    helper_text: str = "Agent is ready."
    command_hint: str = "Commands: /approve /reject /new /resume <session_id>"
    focus_label: str = "INPUT"
    placeholder: str = "Ask pp-Echo what to do next"
    accent_variant: Literal["ready", "waiting", "busy", "approval"] = "ready"
    show_pending_badge: bool = False


@dataclass
class TuiState:
    session_epoch: int = 0
    messages: list[TuiMessage] = field(default_factory=list)
    active_assistant_message: ActiveAssistantMessage = field(default_factory=ActiveAssistantMessage)
    plan_steps: list[TuiPlanStep] = field(default_factory=list)
    plan_summary: list[str] = field(default_factory=list)
    plan_files: list[str] = field(default_factory=list)
    plan_shell_commands: list[str] = field(default_factory=list)
    plan_high_risk_tools: list[str] = field(default_factory=list)
    plan_token_preview: str = ""
    queue_summary: QueueSummary = field(default_factory=QueueSummary)
    approval_state: ApprovalState = field(default_factory=ApprovalState)
    runtime_phase: RuntimePhase = field(default_factory=RuntimePhase)
    composer: ComposerState = field(default_factory=ComposerState)
    ephemeral_logs: list[EphemeralLogEntry] = field(default_factory=list)
    awaiting_assistant: bool = False


def append_log(
    state: TuiState,
    message: str,
    *,
    level: LogLevel = "info",
    important: bool = False,
    limit: int = 100,
) -> None:
    if not message:
        return
    state.ephemeral_logs.append(EphemeralLogEntry(message=message, level=level, important=important))
    if len(state.ephemeral_logs) > limit:
        del state.ephemeral_logs[:-limit]
