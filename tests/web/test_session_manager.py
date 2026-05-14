from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.state import AgentEvent
from pp_agent.web.session_manager import WebSessionManager


class FakeTurn(BaseModel):
    phase: str = "idle"


class FakeState:
    def __init__(self) -> None:
        self.pending_plan_token = None
        self.pending_tool_calls = []
        self.queued_messages = []
        self.turn = FakeTurn()
        self.messages = []


class FakeAgent:
    def __init__(self, session_id: str, subscribers) -> None:
        self.session_id = session_id
        self.state = FakeState()
        self._subscribers = subscribers
        self._cancel_requested = False

    def prompt(self, text: str):
        self.state.messages.append(ChatMessage(role="user", content=[TextPart(text=text)], timestamp=1.0))
        event = AgentEvent(type="message_delta", session_id=self.session_id, delta="ok")
        for subscriber in self._subscribers:
            subscriber(event)
        return [event]

    def enqueue_message(self, text: str, delivery: str = "follow_up"):
        item = SimpleNamespace(id="queued-1", delivery=delivery, text=text)
        self.state.queued_messages.append(item)
        return item

    def continue_(self):
        return []

    def approve_pending_plan(self, token: str):
        self.state.pending_plan_token = None
        event = AgentEvent(type="planner_gate_approved", session_id=self.session_id, details={"token": token})
        for subscriber in self._subscribers:
            subscriber(event)
        return [event]

    def reject_pending_plan(self, token: str):
        self.state.pending_plan_token = None

    def request_cancel(self, reason: str = "cancel_requested") -> None:
        self._cancel_requested = True

    def cancellation_requested(self) -> bool:
        return self._cancel_requested


def _factory(_workspace: Path, session_id, subscribers):
    return FakeAgent(session_id or "session-1", subscribers)


def test_web_session_manager_creates_and_streams_events(tmp_path: Path) -> None:
    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    snapshot = manager.create_session()

    result = manager.get_handle(snapshot["session_id"]).prompt("hello")
    manager.get_handle(snapshot["session_id"])._worker.join(timeout=2)
    events = manager.get_handle(snapshot["session_id"]).drain_events()

    assert result["queued"] is False
    assert events[0]["type"] == "message_delta"
    assert events[0]["delta"] == "ok"


def test_web_session_manager_queues_while_busy(tmp_path: Path) -> None:
    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    handle = manager.get_handle("session-1")
    handle._worker = SimpleNamespace(is_alive=lambda: True)

    result = handle.prompt("later")

    assert result["queued"] is True
    assert handle.snapshot()["queued_message_count"] == 1


def test_web_session_manager_approval_flow(tmp_path: Path) -> None:
    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    handle = manager.get_handle("session-1")
    handle.agent.state.pending_plan_token = "token-1"

    result = handle.approve()
    handle._worker.join(timeout=2)
    events = handle.drain_events()

    assert result["token"] == "token-1"
    assert events[0]["type"] == "planner_gate_approved"


def test_web_session_manager_cancel_marks_running_handle(tmp_path: Path) -> None:
    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    handle = manager.get_handle("session-1")
    handle._worker = SimpleNamespace(is_alive=lambda: True)

    result = handle.cancel()
    events = handle.drain_events()

    assert result["cancel_requested"] is True
    assert handle.snapshot()["cancel_requested"] is True
    assert events[0]["type"] == "cancel_requested"
