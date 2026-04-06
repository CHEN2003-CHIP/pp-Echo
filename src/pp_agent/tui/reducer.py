from __future__ import annotations

from collections.abc import Iterable

from pp_agent.domain import TextPart
from pp_agent.runtime import AgentEvent
from pp_agent.tui.state import (
    ApprovalState,
    QueueSummary,
    RuntimePhase,
    TuiMessage,
    TuiPlanStep,
    TuiState,
    append_log,
)


def hydrate_state_from_runtime(state: TuiState, runtime) -> TuiState:
    state.messages = _messages_from_runtime(runtime)
    state.runtime_phase.session_id = runtime.session_id
    state.runtime_phase.turn_id = runtime.state.turn.turn_id
    state.runtime_phase.phase = runtime.state.turn.phase
    state.runtime_phase.reason = runtime.state.turn.reason
    state.runtime_phase.pending_tool_count = len(runtime.state.pending_tool_calls)
    state.runtime_phase.queue_count = len(runtime.state.queued_messages)
    state.runtime_phase.busy = bool(getattr(runtime.state, "is_streaming", False))
    state.queue_summary = _queue_summary_from_runtime(runtime)
    state.approval_state = ApprovalState(
        pending_plan_token=runtime.state.pending_plan_token,
        awaiting_approval=bool(runtime.state.pending_plan_token),
        prompt=_approval_prompt(runtime.state.pending_plan_token),
    )
    return state


def reduce_event(state: TuiState, event: AgentEvent) -> TuiState:
    _apply_runtime_snapshot(state, event)

    if event.type == "message_delta" and event.delta:
        state.active_assistant_message.streaming = True
        state.active_assistant_message.text += event.delta
    elif event.type == "planner_start":
        state.plan_steps = []
    elif event.type == "planner_step" and event.plan_step is not None:
        _upsert_plan_step(state, event.plan_step.title, event.plan_step.tool_name, event.plan_step.status)
    elif event.type == "planner_end":
        if event.details.get("requires_approval"):
            token = event.details.get("token")
            state.approval_state = ApprovalState(
                pending_plan_token=token,
                awaiting_approval=True,
                prompt=_approval_prompt(token),
            )
    elif event.type == "planner_gate_pending":
        token = event.details.get("token")
        state.approval_state = ApprovalState(
            pending_plan_token=token,
            awaiting_approval=True,
            prompt=_approval_prompt(token),
        )
        append_log(state, state.approval_state.prompt)
    elif event.type in {"planner_gate_approved", "planner_gate_rejected"}:
        append_log(state, event.message or event.type.replace("_", " "))
        state.approval_state = ApprovalState()
    elif event.type == "queue_update":
        state.queue_summary.latest_action = _queue_action_text(event)
        append_log(state, state.queue_summary.latest_action)
    elif event.type == "tool_start":
        append_log(state, f"Start {event.tool_name}")
    elif event.type == "tool_end":
        label = "ERROR" if event.is_error else "DONE"
        append_log(state, f"{label} {event.tool_name}: {event.message or ''}".strip())
    elif event.type == "error":
        append_log(state, f"Error: {event.message or ''}".strip())

    if event.type in {"turn_end", "agent_end", "planner_gate_pending", "error"}:
        _commit_active_assistant_message(state)
    return state


def _messages_from_runtime(runtime) -> list[TuiMessage]:
    messages: list[TuiMessage] = []
    for message in runtime.state.messages:
        text = _text_from_parts(message.content)
        if text:
            messages.append(TuiMessage(role=message.role, text=text))
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
    state.queue_summary.queue_count = state.runtime_phase.queue_count
    if runtime.get("queue_delivery") == "steering":
        state.queue_summary.steering_count = max(0, state.queue_summary.steering_count + _queue_count_delta(runtime))
    elif runtime.get("queue_delivery") == "follow_up":
        state.queue_summary.follow_up_count = max(0, state.queue_summary.follow_up_count + _queue_count_delta(runtime))
    pending_plan = bool(runtime.get("pending_plan", False))
    if pending_plan and not state.approval_state.pending_plan_token:
        state.approval_state.pending_plan_token = event.details.get("token")
    state.approval_state.awaiting_approval = pending_plan or state.approval_state.awaiting_approval
    if pending_plan and state.approval_state.pending_plan_token:
        state.approval_state.prompt = _approval_prompt(state.approval_state.pending_plan_token)


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


def _approval_prompt(token: str | None) -> str:
    if not token:
        return ""
    return f"Pending approval {token}. Use /approve or /reject."


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
    state.messages.append(TuiMessage(role="assistant", text=state.active_assistant_message.text))
    state.active_assistant_message.text = ""
    state.active_assistant_message.streaming = False
