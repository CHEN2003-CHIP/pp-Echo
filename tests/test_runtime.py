from collections.abc import Iterator
from pathlib import Path

from agent_core.runtime.session import AgentSession
from agent_core.types import ChatMessage, ModelConfig, TextPart
from storage.sessions import SessionStore
from tools.pending_actions import PendingActionStore
from tools.registry import ToolRegistry


class FakeLLMClient:
    def __init__(self) -> None:
        self.calls = 0
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        self.calls += 1
        if self.calls == 1:
            yield {
                "text": "",
                "tool_calls": [{"id": "call-1", "name": "write_file", "arguments_chunk": '{"path":"a.txt","content":"hi","apply":true}'}],
                "finish_reason": "tool_calls",
                "raw": {},
            }
        else:
            yield {"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class BrokenLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {"text": "", "tool_calls": [{"id": "call-1", "name": "write_file", "arguments_chunk": '{broken'}], "finish_reason": "tool_calls", "raw": {}}


class NoopLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {"text": "ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class FailingToolLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {
            "text": "",
            "tool_calls": [{"id": "call-1", "name": "edit_file", "arguments_chunk": '{"path":"missing.txt","diff":"<<<<<<< SEARCH\\nold\\n=======\\nnew\\n>>>>>>> REPLACE","apply":true}'}],
            "finish_reason": "tool_calls",
            "raw": {},
        }


def build_agent(tmp_path: Path, llm_client, compact_after_messages: int = 8, require_plan_approval: bool = True) -> AgentSession:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    return AgentSession(
        llm_client=llm_client,
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        compact_after_messages=compact_after_messages,
        require_plan_approval=require_plan_approval,
    )


def test_agent_session_pauses_high_risk_plan_until_approved(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, FakeLLMClient(), require_plan_approval=True)

    events = agent.prompt("create a file")
    planner_pause = [event for event in events if event.type == "planner_end" and event.details.get("requires_approval")]

    assert planner_pause
    assert agent.state.pending_plan_token is not None
    assert len(agent.state.pending_tool_calls) == 1
    assert (tmp_path / "a.txt").exists() is False

    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert pending and pending[0]["action_type"] == "planner_approval"


def test_agent_session_executes_pending_plan_after_approval(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, FakeLLMClient(), require_plan_approval=True)
    agent.prompt("create a file")

    token = agent.state.pending_plan_token
    assert token is not None

    events = agent.approve_pending_plan(token)

    assert any(event.type == "tool_start" for event in events)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hi"
    assert agent.state.pending_plan_token is None
    assert agent.state.pending_tool_calls == []


def test_agent_session_emits_planner_events_before_tool_execution(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, FakeLLMClient(), require_plan_approval=False)

    events = agent.prompt("create a file")
    event_types = [event.type for event in events]
    planner_start_index = event_types.index("planner_start")
    first_tool_start_index = event_types.index("tool_start")
    plan_updates = [event for event in events if event.type == "planner_step" and event.plan_step is not None]
    statuses = [event.plan_step.status for event in plan_updates]

    assert planner_start_index < first_tool_start_index
    assert statuses[:3] == ["pending", "in_progress", "completed"]


def test_agent_session_persists_and_resumes_pending_plan(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentSession(
        llm_client=FakeLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=True,
    )
    agent.prompt("create a file")

    restored = store.load(record.id)

    assert restored.pending_plan_token is not None
    assert len(restored.pending_tool_calls) == 1
    assert restored.messages
    assert restored.messages[0].role == "user"


def test_agent_session_emits_error_for_bad_tool_arguments(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, BrokenLLMClient(), require_plan_approval=False)

    events = agent.prompt("create a file")

    assert any(event.type == "error" for event in events)


def test_agent_session_marks_plan_step_failed_when_tool_fails(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, FailingToolLLMClient(), require_plan_approval=False)

    events = agent.prompt("edit a missing file")
    failed_steps = [event.plan_step for event in events if event.type == "planner_step" and event.plan_step is not None and event.plan_step.status == "failed"]

    assert failed_steps
    assert any(event.type == "tool_end" and event.is_error for event in events)


def test_agent_session_compacts_old_messages(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, NoopLLMClient(), compact_after_messages=4, require_plan_approval=False)
    agent.state.messages = [
        ChatMessage(role="user", content=[TextPart(text=f"user {index}")], timestamp=float(index))
        for index in range(6)
    ]

    events = agent.prompt("trigger compaction")

    assert any(event.type == "compaction" for event in events)
    assert agent.state.compaction.summary
    assert agent.state.compaction.summarized_message_count > 0
