from __future__ import annotations

from pathlib import Path

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.llm import ModelConfig

from pp_agent.runtime.lifecycle import (
    SESSION_BEFORE_FORK,
    SESSION_BEFORE_SWITCH,
    SESSION_BEFORE_TREE,
    SESSION_FORKED,
    SESSION_REWOUND,
    SESSION_SWITCHED,
    SESSION_TREE_NAVIGATED,
    SESSION_TREE_VIEWED,
)
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


def _host(tmp_path: Path) -> SessionHost:
    from pp_agent.runtime.runtime import AgentRuntime

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


def test_session_host_events(tmp_path: Path) -> None:
    host = _host(tmp_path)
    captured = []
    created = host.create_session(tmp_path)
    store = SessionStore(tmp_path / "sessions")
    record = store.load(created.session_id)
    store.save(record)

    forked = host.fork_session(tmp_path, created.session_id, lifecycle_subscribers=[captured.append])
    rewound = host.rewind_session(tmp_path, created.session_id, message_count=0, lifecycle_subscribers=[captured.append])
    host.get_tree(tmp_path, created.session_id, lifecycle_subscribers=[captured.append])
    host.switch_session(tmp_path, created.session_id, forked.session_id, lifecycle_subscribers=[captured.append])

    assert forked.session_id
    assert rewound.session_id
    types = [event.type for event in captured]
    assert SESSION_BEFORE_FORK in types
    assert SESSION_FORKED in types
    assert SESSION_REWOUND in types
    assert SESSION_BEFORE_TREE in types
    assert SESSION_TREE_VIEWED in types
    assert SESSION_BEFORE_SWITCH in types
    assert SESSION_SWITCHED in types


def test_session_host_create_and_restore_session(tmp_path: Path) -> None:
    host = _host(tmp_path)

    created = host.create_session(tmp_path)
    restored = host.restore_session(tmp_path, created.session_id)

    assert created.session_id == restored.session_id


def test_session_host_navigate_tree_emits_navigation(tmp_path: Path) -> None:
    host = _host(tmp_path)
    created = host.create_session(tmp_path)
    store = SessionStore(tmp_path / "sessions")
    record = store.load(created.session_id)
    record.messages = [ChatMessage(role="user", content=[TextPart(text="hello")], timestamp=1.0)]
    store.save(record)
    head_id = store.load(created.session_id).active_head_id
    captured = []

    if head_id is not None:
        host.navigate_tree(tmp_path, created.session_id, head_id, lifecycle_subscribers=[captured.append])

    types = [event.type for event in captured]
    assert SESSION_BEFORE_TREE in types
    assert SESSION_TREE_NAVIGATED in types
