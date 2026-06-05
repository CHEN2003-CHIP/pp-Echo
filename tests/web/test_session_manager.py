from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel

from pp_agent.app import bootstrap
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.state import AgentEvent
from pp_agent.storage.models import StoredModelConfig
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

    def record_external_approval_result(self, result: dict) -> None:
        self.state.messages.append(
            ChatMessage(
                role="tool",
                content=[TextPart(text=str(result.get("result", "")))],
                tool_call_id=str(result.get("tool_call_id") or ""),
                tool_name=str(result.get("source_tool_name") or result.get("action_type") or ""),
                metadata={"tool_details": {**dict(result.get("details") or {}), "external_approval_result": True, "lifecycle": result.get("lifecycle")}},
                timestamp=1.0,
            )
        )

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
    assert handle.snapshot()["runtime_control"]["status"] == "executing"


def test_web_session_manager_approval_flow(tmp_path: Path) -> None:
    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    handle = manager.get_handle("session-1")
    handle.agent.state.pending_plan_token = "token-1"

    result = handle.approve()
    handle._worker.join(timeout=2)
    events = handle.drain_events()

    assert result["token"] == "token-1"
    assert events[0]["type"] == "planner_gate_approved"


def test_web_session_manager_records_external_approval_result(tmp_path: Path) -> None:
    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    handle = manager.get_handle("session-1")

    handle.record_external_approval_result(
        {
            "session_id": "session-1",
            "token": "token-1",
            "action_type": "write_file",
            "source_tool_name": "write_file",
            "tool_call_id": "call-1",
            "result": "Write applied successfully.",
            "success": True,
            "lifecycle": {"state": "grant_consumed"},
            "details": {"path": "test_637.py"},
        }
    )

    message = handle.agent.state.messages[-1]
    assert message.role == "tool"
    assert message.tool_name == "write_file"
    assert message.tool_call_id == "call-1"
    assert message.metadata["tool_details"]["external_approval_result"] is True
    assert message.metadata["tool_details"]["lifecycle"]["state"] == "grant_consumed"


def test_web_session_manager_cancel_marks_running_handle(tmp_path: Path) -> None:
    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    handle = manager.get_handle("session-1")
    handle._worker = SimpleNamespace(is_alive=lambda: True)

    result = handle.cancel()
    events = handle.drain_events()

    assert result["cancel_requested"] is True
    assert handle.snapshot()["cancel_requested"] is True
    assert events[0]["type"] == "cancel_requested"


def test_web_session_snapshot_includes_pending_patch_artifact_summary(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = WebSessionManager(workspace, runtime_factory=_factory)
    handle = manager.get_handle("session-1")
    store = bootstrap.pending_action_store_for(workspace)
    payload = store.stage(
        action_type="apply_patch_artifact",
        target_path=workspace / ".pp-agent" / "artifacts" / "demo.patch",
        details={
            "session_id": "session-1",
            "workflow": "code_change",
            "artifact_id": "artifact-1",
            "changed_paths": ["docs/worktree-smoke-web.md"],
        },
    )

    snapshot = handle.snapshot()

    assert snapshot["runtime_control"]["status"] == "awaiting_artifact_approval"
    assert snapshot["runtime_control"]["pending_artifact_count"] == 1
    assert snapshot["pending_artifacts"][0]["token"] == payload["token"]


def test_web_session_snapshot_filters_tool_messages_and_truncates_large_text(tmp_path: Path) -> None:
    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    handle = manager.get_handle("session-1")
    handle.agent.state.messages = [
        ChatMessage(role="user", content=[TextPart(text="hello")], timestamp=1.0),
        ChatMessage(role="tool", content=[TextPart(text="x" * 500_000)], tool_name="read_file", timestamp=2.0),
        ChatMessage(role="assistant", content=[TextPart(text="y" * 130_000)], timestamp=3.0),
    ]

    snapshot = handle.snapshot()

    assert [message["role"] for message in snapshot["messages"]] == ["user", "assistant"]
    assert snapshot["messages"][0]["content"][0]["text"] == "hello"
    assistant_text = snapshot["messages"][1]["content"][0]["text"]
    assert len(assistant_text) < 121_000
    assert "Web preview truncated" in assistant_text


def test_web_session_snapshot_omits_oversized_inline_media(tmp_path: Path) -> None:
    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    handle = manager.get_handle("session-1")
    handle.agent.state.messages = [
        ChatMessage(
            role="assistant",
            content=[TextPart(text="see attached")],
            metadata={"attachments": ["data:image/png;base64," + ("a" * 500_000)]},
            timestamp=1.0,
        ),
    ]

    snapshot = handle.snapshot()

    assert snapshot["messages"][0]["content"][0]["text"] == "see attached"
    assert snapshot["messages"][0]["metadata"]["attachments"] == [{}]


def test_web_session_events_are_lightweight_for_browser(tmp_path: Path) -> None:
    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    handle = manager.get_handle("session-1")
    for subscriber in handle.agent._subscribers:
        subscriber(
            AgentEvent(
                type="tool_end",
                session_id="session-1",
                message="m" * 50_000,
                details={"payload": "d" * 50_000, "items": list(range(100))},
            )
        )

    event = handle.drain_events()[0]

    assert len(event["message"]) < 13_000
    assert "Web preview truncated" in event["message"]
    assert len(event["details"]["payload"]) < 13_000
    assert len(event["details"]["items"]) == 24


def test_web_session_snapshot_uses_stored_snapshot_without_restoring_runtime(tmp_path: Path) -> None:
    store = bootstrap.session_store_for(tmp_path)
    record = store.create("system prompt", StoredModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="hello")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="world")], timestamp=2.0),
    ]
    store.save(record)

    def fail_runtime(*_args, **_kwargs):
        raise AssertionError("runtime restore should not run for stored snapshots")

    manager = WebSessionManager(tmp_path, runtime_factory=fail_runtime)
    snapshot = manager.snapshot(record.id)

    assert snapshot["session_id"] == record.id
    assert snapshot["history"]["source"] == "stored"
    assert snapshot["messages"][0]["role"] == "user"
    assert snapshot["messages"][1]["role"] == "assistant"


def test_web_session_list_uses_lightweight_event_summary(tmp_path: Path) -> None:
    store = bootstrap.session_store_for(tmp_path)
    record = store.create("system prompt", StoredModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="hello from history")], timestamp=1.0),
        ChatMessage(role="tool", content=[TextPart(text="x" * 500_000)], tool_name="read_file", timestamp=1.5),
        ChatMessage(role="assistant", content=[TextPart(text="short answer")], timestamp=2.0),
    ]
    path = store.save(record)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type":"session_snapshot","data":{"messages":"' + ("y" * 500_000) + '"}}\n')

    manager = WebSessionManager(tmp_path, runtime_factory=lambda *_args, **_kwargs: None)
    sessions = manager.list_sessions()

    assert sessions[0]["id"] == record.id
    assert sessions[0]["message_count"] == 3
