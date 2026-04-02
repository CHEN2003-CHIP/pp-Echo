from collections.abc import Iterator
from pathlib import Path

from agent_core.types import ModelConfig
from pp_agent.app.bootstrap import build_agent
from pp_agent.runtime.lifecycle import (
    AGENT_END,
    AGENT_START,
    BEFORE_PROVIDER_REQUEST,
    CONTEXT_BUILT,
    PROVIDER_RESPONSE,
    TOOL_CALL,
    TOOL_END,
    TOOL_ERROR,
    TOOL_RESULT,
    TOOL_START,
    TURN_END,
    TURN_START,
)


class HelloLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {"text": "hello", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class ToolLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {
            "text": "",
            "tool_calls": [{"id": "call-1", "name": "write_file", "arguments_chunk": '{"path":"a.txt","content":"hi","apply":true}'}],
            "finish_reason": "tool_calls",
            "raw": {},
        }
        yield {"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}


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


def _agent(tmp_path: Path, llm_client, subscribers=None):
    from pp_agent.runtime.runtime import AgentRuntime
    from pp_agent.storage.sessions import SessionStore
    from pp_agent.tools.registry import ToolRegistry

    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentRuntime(
        llm_client=llm_client,
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
    )
    for subscriber in subscribers or []:
        agent.subscribe(subscriber)
    agent._queue_lifecycle_event(agent._event("session_start", details={"new_session": True}))
    agent.restore_session_record(record)
    return agent


def test_prompt_emits_minimum_lifecycle_sequence(tmp_path: Path) -> None:
    agent = _agent(tmp_path, HelloLLMClient())

    events = agent.prompt("hello")
    types = [event.type for event in events]

    assert "session_start" in types
    assert "session_restore" in types
    assert AGENT_START in types
    assert TURN_START in types
    assert CONTEXT_BUILT in types
    assert BEFORE_PROVIDER_REQUEST in types
    assert PROVIDER_RESPONSE in types
    assert TURN_END in types
    assert AGENT_END in types


def test_tool_lifecycle_success_order(tmp_path: Path) -> None:
    agent = _agent(tmp_path, ToolLLMClient())

    events = agent.prompt("create file")
    types = [event.type for event in events]

    assert types.index(TOOL_CALL) < types.index(TOOL_START) < types.index(TOOL_RESULT) < types.index(TOOL_END)


def test_tool_lifecycle_error_order(tmp_path: Path) -> None:
    agent = _agent(tmp_path, FailingToolLLMClient())

    events = agent.prompt("edit missing")
    types = [event.type for event in events]

    assert types.index(TOOL_CALL) < types.index(TOOL_START) < types.index(TOOL_ERROR) < types.index(TOOL_END)
