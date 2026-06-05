from __future__ import annotations

import subprocess
from pathlib import Path

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.llm import ModelConfig

from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.runtime.session_host import SessionHost
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.checkpoints import CheckpointStore
from pp_agent.storage.sessions import SessionStore
from pp_agent.tools.registry import ToolRegistry


class FakeLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None):
        yield {"text": "ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def _init_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "note.txt").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "note.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)


def _host(tmp_path: Path) -> SessionHost:
    def runtime_factory(workspace: Path, record, lifecycle_subscribers=None):
        agent = AgentRuntime(
            llm_client=FakeLLMClient(),
            tool_registry=ToolRegistry(workspace),
            session_store=SessionStore(workspace / "sessions"),
            session_id=record.id,
            system_prompt=record.system_prompt,
            confirm_callback=lambda _name, _args: True,
            require_plan_approval=False,
        )
        for subscriber in lifecycle_subscribers or []:
            agent.subscribe(subscriber)
        return agent

    return SessionHost(
        runtime_factory=runtime_factory,
        session_store_factory=lambda workspace: SessionStore(workspace / "sessions"),
        pending_action_store_factory=lambda workspace: PendingActionStore(workspace / "pending"),
        session_defaults_factory=lambda workspace: {"system_prompt": "system", "model": ModelConfig()},
        checkpoint_store_factory=lambda workspace: CheckpointStore(workspace / "checkpoints"),
    )


def test_safe_rewind_workspace_only_restores_workspace(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    host = _host(tmp_path)
    runtime = host.create_session(tmp_path)
    store = SessionStore(tmp_path / "sessions")
    record = store.load(runtime.session_id)
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
    ]
    store.save(record)
    checkpoint = host.create_checkpoint(tmp_path, session_id=runtime.session_id, reason="before-change")
    (tmp_path / "note.txt").write_text("v2\n", encoding="utf-8")

    result = host.rewind_safe(tmp_path, runtime.session_id, checkpoint_id=checkpoint.checkpoint_id, mode="workspace_only")

    assert result.restored_workspace is True
    assert result.restored_conversation is False
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "v1\n"


def test_safe_rewind_conversation_only_keeps_workspace_and_branches_session(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    host = _host(tmp_path)
    runtime = host.create_session(tmp_path)
    store = SessionStore(tmp_path / "sessions")
    record = store.load(runtime.session_id)
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
    ]
    store.save(record)
    checkpoint = host.create_checkpoint(tmp_path, session_id=runtime.session_id, reason="before-change")
    (tmp_path / "note.txt").write_text("dirty\n", encoding="utf-8")

    result = host.rewind_safe(tmp_path, runtime.session_id, checkpoint_id=checkpoint.checkpoint_id, mode="conversation_only", message_count=0)

    assert result.restored_workspace is False
    assert result.restored_conversation is True
    assert result.session_id != runtime.session_id
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "dirty\n"


def test_safe_rewind_emits_restore_and_safe_rewind_events(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    host = _host(tmp_path)
    runtime = host.create_session(tmp_path)
    store = SessionStore(tmp_path / "sessions")
    record = store.load(runtime.session_id)
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
    ]
    store.save(record)
    checkpoint = host.create_checkpoint(tmp_path, session_id=runtime.session_id, reason="before-change")
    (tmp_path / "note.txt").write_text("v2\n", encoding="utf-8")
    captured = []

    host.rewind_safe(tmp_path, runtime.session_id, checkpoint_id=checkpoint.checkpoint_id, mode="conversation_and_workspace", message_count=0, lifecycle_subscribers=[captured.append])

    types = [event.type for event in captured]
    assert "session_safe_rewind_started" in types
    assert "checkpoint_restored" in types
    assert "session_safe_rewind_completed" in types
