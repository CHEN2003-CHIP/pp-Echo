from __future__ import annotations

import time
from collections.abc import Iterable

from pp_agent.domain import TextPart
from pp_agent.runtime import AgentEvent
from pp_agent.tui.state import (
    ActiveAssistantMessage,
    ApprovalState,
    ComposerState,
    QueueSummary,
    RuntimePhase,
    TuiMessage,
    TuiPlanStep,
    TuiState,
    append_log,
)


def hydrate_state_from_runtime(state: TuiState, runtime, *, session_epoch: int = 0, pending_plan_details: dict | None = None) -> TuiState:
    state.session_epoch = session_epoch
    state.messages = _messages_from_runtime(runtime)
    state.active_assistant_message = ActiveAssistantMessage()
    state.plan_steps = []
    state.plan_summary = []
    state.plan_files = []
    state.plan_shell_commands = []
    state.plan_high_risk_tools = []
    state.plan_token_preview = ""
    state.awaiting_assistant = False
    state.runtime_phase = RuntimePhase(
        session_id=runtime.session_id,
        turn_id=runtime.state.turn.turn_id,
        phase=runtime.state.turn.phase,
        reason=runtime.state.turn.reason,
        pending_tool_count=len(runtime.state.pending_tool_calls),
        queue_count=len(runtime.state.queued_messages),
        busy=bool(getattr(runtime.state, "is_streaming", False)),
    )
    state.runtime_phase.status_line = _make_status_line(state.runtime_phase)
    state.queue_summary = _queue_summary_from_runtime(runtime)
    state.approval_state = _approval_from_runtime(runtime)
    state.plan_token_preview = state.approval_state.token_preview
    if pending_plan_details:
        _update_plan_preview(state, pending_plan_details)
    state.composer = _composer_state(state)
    state.ephemeral_logs = []
    return state


def reduce_event(state: TuiState, event: AgentEvent) -> TuiState:
    _apply_runtime_snapshot(state, event)

    if event.type == "local_waiting":
        state.awaiting_assistant = True
        _append_status_message(state, "assistant-waiting", event.message or "assistant is thinking ...")
    elif event.type == "message_delta" and event.delta:
        if not state.active_assistant_message.streaming:
            state.active_assistant_message.started_at = time.time()
            _remove_status_message(state, "assistant-waiting")
            _append_status_message(state, "assistant-stream", "assistant started responding")
        state.awaiting_assistant = False
        state.active_assistant_message.streaming = True
        state.active_assistant_message.has_content = True
        state.active_assistant_message.text += event.delta
    elif event.type == "planner_start":
        state.awaiting_assistant = False
        _remove_status_message(state, "assistant-waiting")
        state.plan_steps = []
        _update_plan_preview(state, event.details)
        _append_status_message(state, "planner-start", "planning next actions")
    elif event.type == "planner_step" and event.plan_step is not None:
        _upsert_plan_step(state, event.plan_step.title, event.plan_step.tool_name, event.plan_step.status)
    elif event.type == "planner_end" and not event.details.get("requires_approval"):
        append_log(state, "Plan ready for execution.", level="info")
        _append_status_message(state, "planner-end", "plan ready for execution")
    elif event.type == "planner_gate_pending":
        token = event.details.get("token")
        state.awaiting_assistant = False
        _remove_status_message(state, "assistant-waiting")
        _update_plan_preview(state, event.details)
        state.approval_state = _approval_from_token(token, awaiting=True)
        append_log(state, state.approval_state.prompt, level="warning", important=True)
        _append_status_message(state, "approval-pending", "waiting for approval")
    elif event.type == "planner_gate_approved":
        append_log(state, event.message or "Approval accepted.", level="success", important=True)
        state.approval_state = ApprovalState(status_label="approved")
        _append_status_message(state, "approval-approved", event.message or "approval accepted")
    elif event.type == "planner_gate_rejected":
        append_log(state, event.message or "Approval rejected.", level="warning", important=True)
        state.approval_state = ApprovalState(status_label="rejected")
        state.plan_steps = []
        state.plan_summary = []
        state.plan_files = []
        state.plan_shell_commands = []
        state.plan_high_risk_tools = []
        state.plan_token_preview = ""
        _append_status_message(state, "approval-rejected", event.message or "approval rejected")
    elif event.type == "queue_update":
        state.queue_summary.latest_action = _queue_action_text(event)
        append_log(state, state.queue_summary.latest_action, level="info")
    elif event.type == "tool_start":
        append_log(state, f"Start {event.tool_name}", level="info")
    elif event.type == "tool_end":
        level = "error" if event.is_error else "success"
        label = "ERROR" if event.is_error else "DONE"
        append_log(state, f"{label} {event.tool_name}: {event.message or ''}".strip(), level=level)
    elif event.type == "error":
        state.awaiting_assistant = False
        _remove_status_message(state, "assistant-waiting")
        message = f"Error: {event.message or ''}".strip()
        append_log(state, message, level="error", important=True)
        _append_status_message(state, f"error-{len(state.messages)}", message)
    elif event.type == "local_info":
        append_log(state, event.message or "", level="info")
        _append_status_message(state, f"local-info-{len(state.messages)}", event.message or "")
    elif event.type == "local_warning":
        append_log(state, event.message or "", level="warning", important=True)
        _append_status_message(state, f"local-warning-{len(state.messages)}", event.message or "")

    if event.type in {"turn_end", "agent_end", "planner_gate_pending", "error"}:
        state.awaiting_assistant = False
        _remove_status_message(state, "assistant-waiting")
        _commit_active_assistant_message(state)
        if state.runtime_phase.phase == "idle" and not state.approval_state.awaiting_approval:
            state.plan_steps = []
            state.plan_summary = []
            state.plan_files = []
            state.plan_shell_commands = []
            state.plan_high_risk_tools = []
            state.plan_token_preview = ""
    state.composer = _composer_state(state)
    return state


def _messages_from_runtime(runtime) -> list[TuiMessage]:
    messages: list[TuiMessage] = []
    for index, message in enumerate(runtime.state.messages):
        text = _text_from_parts(message.content)
        if text:
            messages.append(TuiMessage(id=f"runtime-{index}", role=message.role, text=text))
    return messages


def _queue_summary_from_runtime(runtime) -> QueueSummary:
    items = list(runtime.state.queued_messages)
    steering_count = sum(1 for item in items if item.delivery == "steering")
    follow_up_count = sum(1 for item in items if item.delivery == "follow_up")
    return QueueSummary(
        queue_count=len(items),
        steering_count=steering_count,
        follow_up_count=follow_up_count,
        latest_action="",
    )


def _approval_from_runtime(runtime) -> ApprovalState:
    token = runtime.state.pending_plan_token
    return _approval_from_token(token, awaiting=bool(token)) if token else ApprovalState(status_label="clear")


def _approval_from_token(token: str | None, *, awaiting: bool) -> ApprovalState:
    preview = token[:8] if token else ""
    return ApprovalState(
        pending_plan_token=token,
        awaiting_approval=awaiting,
        prompt=_approval_prompt(token),
        actionable=awaiting,
        status_label="awaiting" if awaiting else "clear",
        token_preview=preview,
    )


def _composer_state(state: TuiState) -> ComposerState:
    if state.approval_state.awaiting_approval:
        return ComposerState(
            prompt_prefix="approve>",
            mode_label="APPROVAL",
            helper_text="Approval pending. Ctrl+S submits input; Ctrl+V pastes text; Ctrl+C copies selection.",
            command_hint="Type 'approve' or 'reject' | Ctrl+S submit | /new | /resume <session_id>",
            focus_label="ACTION",
            placeholder="Approve, reject, or wait for the gate to clear",
            accent_variant="approval",
            show_pending_badge=True,
        )
    if state.runtime_phase.busy:
        return ComposerState(
            prompt_prefix="queue>",
            mode_label="BUSY",
            helper_text="Agent is working. Enter adds a new line; Ctrl+S submits; Ctrl+V pastes text.",
            command_hint="Type follow-up guidance | Ctrl+S submit | /new | /resume <session_id>",
            focus_label="QUEUE",
            placeholder="Add a follow-up while the agent is working",
            accent_variant="busy",
            show_pending_badge=False,
        )
    if state.awaiting_assistant:
        return ComposerState(
            prompt_prefix=">",
            mode_label="WAITING",
            helper_text="Question sent. Enter adds a new line; Ctrl+S submits when you're ready.",
            command_hint="Stay here or prepare your next turn | Ctrl+V paste",
            focus_label="WAIT",
            placeholder="The agent is preparing a response",
            accent_variant="waiting",
            show_pending_badge=False,
        )
    return ComposerState(
        prompt_prefix=">",
        mode_label="READY",
        helper_text="Enter adds a new line; Ctrl+S submits; Ctrl+V pastes; Ctrl+C copies selection.",
        command_hint="Commands: /approve /reject /new /resume <session_id> | Ctrl+S submit",
        focus_label="INPUT",
        placeholder="Ask pp-Echo what to do next",
        accent_variant="ready",
        show_pending_badge=False,
    )


def _append_status_message(state: TuiState, message_id: str, text: str) -> None:
    if not text:
        return
    for existing in state.messages:
        if existing.id == message_id:
            existing.text = text
            return
    state.messages.append(
        TuiMessage(
            id=message_id,
            role="system",
            text=text,
            muted=True,
            kind="status",
        )
    )


def _remove_status_message(state: TuiState, message_id: str) -> None:
    state.messages = [message for message in state.messages if message.id != message_id]


def _text_from_parts(parts: Iterable[object]) -> str:
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, TextPart) and part.text.strip():
            chunks.append(part.text.strip())
        else:
            text = getattr(part, "text", "")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
    return "\n".join(chunks)


def _apply_runtime_snapshot(state: TuiState, event: AgentEvent) -> None:
    runtime = event.details.get("runtime") or {}
    if not runtime:
        return
    state.runtime_phase = RuntimePhase(
        session_id=event.session_id or state.runtime_phase.session_id,
        turn_id=int(runtime.get("turn_id", state.runtime_phase.turn_id)),
        phase=str(runtime.get("phase", state.runtime_phase.phase)),
        reason=str(runtime.get("reason", state.runtime_phase.reason)),
        pending_tool_count=int(runtime.get("pending_tool_count", state.runtime_phase.pending_tool_count)),
        queue_count=int(runtime.get("queue_count", state.runtime_phase.queue_count)),
        busy=str(runtime.get("phase", state.runtime_phase.phase)) != "idle",
    )
    state.runtime_phase.status_line = _make_status_line(state.runtime_phase)
    state.queue_summary.queue_count = state.runtime_phase.queue_count
    if runtime.get("queue_delivery") == "steering":
        state.queue_summary.steering_count = max(0, state.queue_summary.steering_count + _queue_count_delta(runtime))
    elif runtime.get("queue_delivery") == "follow_up":
        state.queue_summary.follow_up_count = max(0, state.queue_summary.follow_up_count + _queue_count_delta(runtime))
    pending_plan = bool(runtime.get("pending_plan", False))
    if pending_plan:
        token = state.approval_state.pending_plan_token or event.details.get("token")
        state.approval_state = _approval_from_token(token, awaiting=True)
    elif state.approval_state.awaiting_approval:
        state.approval_state.awaiting_approval = False
        state.approval_state.actionable = False
        if state.approval_state.status_label == "awaiting":
            state.approval_state.status_label = "clear"


def _make_status_line(phase: RuntimePhase) -> str:
    mode = "busy" if phase.busy else "idle"
    line = (
        f"session={phase.session_id or '-'} turn={phase.turn_id} phase={phase.phase} "
        f"queue={phase.queue_count} tools={phase.pending_tool_count} mode={mode}"
    )
    if phase.reason:
        line += f" reason={phase.reason}"
    return line


def _queue_count_delta(runtime: dict) -> int:
    action = runtime.get("queue_action")
    if action == "enqueued":
        return 1
    if action == "dequeued":
        return -1
    return 0


def _upsert_plan_step(state: TuiState, title: str, tool_name: str | None, status: str) -> None:
    for step in state.plan_steps:
        if step.title == title and step.tool_name == tool_name:
            step.status = status
            return
    state.plan_steps.append(TuiPlanStep(title=title, tool_name=tool_name, status=status))


def _update_plan_preview(state: TuiState, details: dict) -> None:
    if "summary" in details:
        summary = details.get("summary") or []
        state.plan_summary = [str(item) for item in summary if str(item).strip()]
    if "files_touched_guess" in details:
        state.plan_files = [str(item) for item in details.get("files_touched_guess", []) if str(item).strip()]
    if "shell_commands_guess" in details:
        state.plan_shell_commands = [str(item) for item in details.get("shell_commands_guess", []) if str(item).strip()]
    if "high_risk_tools" in details:
        state.plan_high_risk_tools = [str(item) for item in details.get("high_risk_tools", []) if str(item).strip()]
    token = details.get("token")
    if token:
        state.plan_token_preview = str(token)[:8]


def _approval_prompt(token: str | None) -> str:
    if not token:
        return ""
    return f"Pending approval {token}. Type approve or reject."


def _queue_action_text(event: AgentEvent) -> str:
    action = event.details.get("action", "updated")
    delivery = event.details.get("delivery", "")
    text = str(event.details.get("text", "")).replace("\n", " ").strip()
    preview = text[:77] + "..." if len(text) > 80 else text
    return f"Queue {action} {delivery}: {preview}".strip()


def _commit_active_assistant_message(state: TuiState) -> None:
    if not state.active_assistant_message.text:
        state.active_assistant_message.streaming = False
        return
    state.messages.append(
        TuiMessage(
            id=f"assistant-{len(state.messages)}",
            role="assistant",
            text=state.active_assistant_message.text,
            highlight=True,
        )
    )
    state.active_assistant_message = ActiveAssistantMessage()

