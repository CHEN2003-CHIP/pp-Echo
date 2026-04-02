from __future__ import annotations

import subprocess
from pathlib import Path

from agent_core.types import ModelConfig

from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.checkpoints import CheckpointStore
from pp_agent.storage.sessions import SessionStore
from pp_agent.tools.registry import ToolRegistry


class WriteTwiceLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()
        self.calls = 0

    def stream_chat(self, _messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            yield {
                "text": "",
                "tool_calls": [
                    {"id": "call-1", "name": "write_file", "arguments_chunk": '{"path":"a.txt","content":"one","apply":true,"overwrite":true}'},
                    {"id": "call-2", "name": "write_file", "arguments_chunk": '{"path":"b.txt","content":"two","apply":true}'},
                ],
                "finish_reason": "tool_calls",
                "raw": {},
            }
            return
        yield {"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def _init_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "a.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)


def test_create_head_snapshot_writes_ledger(tmp_path: Path) -> None:
    from pp_agent.runtime.git_checkpoint import GitCheckpointManager

    _init_git_repo(tmp_path)
    session_store = SessionStore(tmp_path / "sessions")
    record = session_store.create("system", ModelConfig())
    session_store.save(record)
    checkpoint_store = CheckpointStore(tmp_path / "checkpoints")
    manager = GitCheckpointManager(tmp_path, checkpoint_store, session_store)

    entry = manager.create_head_snapshot(session_id=record.id, head_id=None, turn_id=None, reason="test")

    loaded = checkpoint_store.load(entry.checkpoint_id)
    assert loaded.snapshot_type == "head_snapshot"
    assert loaded.session_id == record.id
    assert loaded.head_commit
    assert loaded.branch_name


def test_auto_checkpoint_creates_one_head_snapshot_per_turn(tmp_path: Path) -> None:
    from pp_agent.app.bootstrap import _install_auto_checkpoint_hook
    from pp_agent.runtime.git_checkpoint import GitCheckpointManager

    _init_git_repo(tmp_path)
    session_store = SessionStore(tmp_path / "sessions")
    checkpoint_store = CheckpointStore(tmp_path / "checkpoints")
    record = session_store.create("system", ModelConfig())
    session_store.save(record)
    agent = AgentRuntime(
        llm_client=WriteTwiceLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=session_store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
    )
    agent.restore_session_record(record)
    _install_auto_checkpoint_hook(agent=agent, workspace=tmp_path, manager=GitCheckpointManager(tmp_path, checkpoint_store, session_store))

    agent.prompt("write files")

    entries = checkpoint_store.list(workspace=tmp_path, session_id=record.id)
    assert len(entries) == 1
    assert entries[0].snapshot_type == "head_snapshot"
