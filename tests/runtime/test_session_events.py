from collections.abc import Iterator
from pathlib import Path

from agent_core.types import ModelConfig
from pp_agent.app.bootstrap import fork_session, rewind_session_with_events, switch_session_head, view_session_tree
from pp_agent.runtime.lifecycle import (
    PLANNER_GATE_APPROVED,
    PLANNER_GATE_PENDING,
    PLANNER_GATE_REJECTED,
    SESSION_BEFORE_FORK,
    SESSION_BEFORE_SWITCH,
    SESSION_BEFORE_TREE,
    SESSION_FORKED,
    SESSION_REWOUND,
    SESSION_TREE_NAVIGATED,
    SESSION_TREE_VIEWED,
)
from pp_agent.storage.sessions import SessionStore
from pp_agent.tools.registry import ToolRegistry
from pp_agent.app.bootstrap import session_store_for


class GatedToolLLMClient:
    def __init__(self) -> None:
        self.calls = 0
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        self.calls += 1
        if self.calls == 1:
            yield {
                "text": "",
                "tool_calls": [{"id": "call-1", "name": "write_file", "arguments_chunk": '{"path":"a.txt","content":"hi"}'}],
                "finish_reason": "tool_calls",
                "raw": {},
            }
        else:
            yield {"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def _runtime(tmp_path: Path):
    from pp_agent.runtime.runtime import AgentRuntime

    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentRuntime(
        llm_client=GatedToolLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=True,
    )
    agent.restore_session_record(record)
    return agent


def test_planner_gate_events_are_emitted(tmp_path: Path) -> None:
    agent = _runtime(tmp_path)

    pending_events = agent.prompt("create file")
    token = agent.state.pending_plan_token
    assert token is not None
    approved_events = agent.approve_pending_plan(token)

    agent = _runtime(tmp_path / "reject")
    pending_reject_events = agent.prompt("create file")
    reject_token = agent.state.pending_plan_token
    assert reject_token is not None
    agent.reject_pending_plan(reject_token)

    assert any(event.type == PLANNER_GATE_PENDING for event in pending_events)
    assert any(event.type == PLANNER_GATE_APPROVED for event in approved_events)
    assert any(event.type == PLANNER_GATE_PENDING for event in pending_reject_events)


def test_session_tree_facade_emits_distinct_view_and_navigation_events(tmp_path: Path) -> None:
    store = session_store_for(tmp_path)
    record = store.create("system", ModelConfig())
    record.messages = []
    store.save(record)
    subscribers = []
    captured = []
    subscribers.append(captured.append)

    view_session_tree(tmp_path, session_id=record.id, subscribers=subscribers)
    forked_id = fork_session(tmp_path, record.id, subscribers=subscribers)
    rewound_id = rewind_session_with_events(tmp_path, record.id, message_count=0, subscribers=subscribers)
    switch_session_head(tmp_path, record.id, None, subscribers=subscribers)

    types = [event.type for event in captured]

    assert SESSION_BEFORE_TREE in types
    assert SESSION_TREE_VIEWED in types
    assert SESSION_TREE_NAVIGATED not in [event.type for event in captured[:2]]
    assert SESSION_BEFORE_FORK in types
    assert SESSION_FORKED in types
    assert SESSION_REWOUND in types
    assert forked_id
    assert rewound_id


def test_session_switch_emits_navigation_only_on_real_change(tmp_path: Path) -> None:
    store = session_store_for(tmp_path)
    record = store.create("system", ModelConfig())
    record.messages = []
    store.save(record)
    saved = store.load(record.id)
    subscribers = []
    captured = []
    subscribers.append(captured.append)

    switch_session_head(tmp_path, saved.id, saved.active_head_id, subscribers=subscribers)

    assert any(event.type == SESSION_BEFORE_SWITCH for event in captured)
    assert not any(event.type == SESSION_TREE_NAVIGATED for event in captured)
