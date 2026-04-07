from __future__ import annotations

from pp_agent.domain import PlanStep
from pp_agent.runtime import AgentEvent
from pp_agent.tui.reducer import reduce_event
from pp_agent.tui.state import TuiState


def test_reduce_event_tracks_waiting_then_streaming_and_commits_message_once() -> None:
    state = TuiState()

    state = reduce_event(
        state,
        AgentEvent(type="local_waiting", session_id="s1", message="assistant is thinking ...", details={}),
    )
    assert state.awaiting_assistant is True
    assert state.composer.mode_label == "WAITING"
    assert state.messages[-1].kind == "status"
    assert "assistant is thinking" in state.messages[-1].text

    state = reduce_event(
        state,
        AgentEvent(type="message_delta", session_id="s1", delta="hello", details={"runtime": {"turn_id": 1, "phase": "executing"}}),
    )
    state = reduce_event(
        state,
        AgentEvent(type="message_delta", session_id="s1", delta=" world", details={"runtime": {"turn_id": 1, "phase": "executing"}}),
    )
    assert state.awaiting_assistant is False
    assert state.active_assistant_message.text == "hello world"
    assert state.active_assistant_message.has_content is True
    assert all(message.id != "assistant-waiting" for message in state.messages)

    state = reduce_event(
        state,
        AgentEvent(type="turn_end", session_id="s1", details={"runtime": {"turn_id": 1, "phase": "idle"}}),
    )
    assert state.active_assistant_message.text == ""
    assert state.messages[-1].role == "assistant"
    assert state.messages[-1].text == "hello world"


def test_reduce_event_tracks_approval_transitions() -> None:
    state = TuiState()

    state = reduce_event(
        state,
        AgentEvent(
            type="planner_gate_pending",
            session_id="s1",
            details={
                "token": "tok-1",
                "runtime": {
                    "turn_id": 2,
                    "phase": "awaiting_approval",
                    "queue_count": 1,
                    "pending_tool_count": 2,
                    "pending_plan": True,
                },
            },
        ),
    )
    assert state.approval_state.awaiting_approval is True
    assert state.approval_state.actionable is True
    assert state.approval_state.status_label == "awaiting"
    assert state.runtime_phase.phase == "awaiting_approval"
    assert state.composer.mode_label == "APPROVAL"

    state = reduce_event(
        state,
        AgentEvent(
            type="planner_gate_approved",
            session_id="s1",
            message="Approved planner gate tok-1",
            details={"runtime": {"turn_id": 2, "phase": "planning", "pending_plan": False}},
        ),
    )
    assert state.approval_state.awaiting_approval is False
    assert state.approval_state.status_label == "approved"


def test_reduce_event_queue_summary_and_plan_reset() -> None:
    state = TuiState()

    state = reduce_event(state, AgentEvent(type="planner_start", session_id="s1", details={}))
    state = reduce_event(
        state,
        AgentEvent(
            type="planner_step",
            session_id="s1",
            plan_step=PlanStep(title="Use tool", tool_name="run_shell", status="in_progress"),
            details={},
        ),
    )
    assert len(state.plan_steps) == 1

    state = reduce_event(
        state,
        AgentEvent(
            type="queue_update",
            session_id="s1",
            details={
                "action": "enqueued",
                "delivery": "follow_up",
                "text": "later",
                "runtime": {
                    "turn_id": 2,
                    "phase": "awaiting_approval",
                    "queue_count": 2,
                    "queue_action": "enqueued",
                    "queue_delivery": "follow_up",
                },
            },
        ),
    )
    assert state.queue_summary.queue_count == 2
    assert state.queue_summary.follow_up_count == 1

    state = reduce_event(
        state,
        AgentEvent(type="turn_end", session_id="s1", details={"runtime": {"turn_id": 2, "phase": "idle", "pending_plan": False}}),
    )
    assert state.plan_steps == []
