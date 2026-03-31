from collections.abc import Iterator
from pathlib import Path

from agent_core.runtime.session import AgentSession
from agent_core.types import ChatMessage, ModelConfig, TextPart
from storage.sessions import SessionStore
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


def test_agent_session_executes_tool_loop(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentSession(
        llm_client=FakeLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
    )

    events = agent.prompt("create a file")

    assert any(event.type == "tool_start" for event in events)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hi"
    assert agent.state.messages[-1].role == "assistant"


def test_agent_session_persists_and_resumes(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentSession(
        llm_client=FakeLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
    )
    agent.prompt("create a file")

    restored = store.load(record.id)

    assert restored.messages
    assert restored.messages[0].role == "user"


def test_agent_session_emits_error_for_bad_tool_arguments(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentSession(
        llm_client=BrokenLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
    )

    events = agent.prompt("create a file")

    assert any(event.type == "error" for event in events)


def test_agent_session_compacts_old_messages(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentSession(
        llm_client=NoopLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        compact_after_messages=4,
    )
    agent.state.messages = [
        ChatMessage(role="user", content=[TextPart(text=f"user {index}")], timestamp=float(index))
        for index in range(6)
    ]

    events = agent.prompt("trigger compaction")

    assert any(event.type == "compaction" for event in events)
    assert agent.state.compaction.summary
    assert agent.state.compaction.summarized_message_count > 0