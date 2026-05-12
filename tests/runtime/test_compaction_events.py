from pathlib import Path

from agent_core.types import ChatMessage, ModelConfig, TextPart, ToolCallPart
from pp_agent.runtime.lifecycle import SESSION_BEFORE_COMPACT, SESSION_COMPACTED
from pp_agent.storage.sessions import SessionStore
from pp_agent.tools.registry import ToolRegistry


class NoopLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None):
        yield {"text": "ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def _agent(tmp_path: Path):
    from pp_agent.runtime.runtime import AgentRuntime

    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentRuntime(
        llm_client=NoopLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        compact_after_messages=4,
        require_plan_approval=False,
    )
    agent.restore_session_record(record)
    return agent


def test_compact_now_emits_before_and_completed(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    agent.state.messages = [
        ChatMessage(role="user", content=[TextPart(text=f"user {index}")], timestamp=float(index))
        for index in range(6)
    ]

    events = agent.compact_now()
    types = [event.type for event in events]

    assert SESSION_BEFORE_COMPACT in types
    assert SESSION_COMPACTED in types


def test_compact_now_noop_emits_no_completed_event(tmp_path: Path) -> None:
    agent = _agent(tmp_path)

    events = agent.compact_now()

    assert events == []


def test_compaction_uses_short_spawn_subagent_summary(tmp_path: Path) -> None:
    from pp_agent.runtime.compaction import ConversationCompactor

    message = ChatMessage(
        role="tool",
        tool_name="spawn_subagent",
        tool_call_id="call-1",
        content=[TextPart(text="very long raw text that should not be used directly")],
        metadata={
            "is_error": True,
            "tool_details": {
                "failure_kind": "invalid_summary",
                "summary": "No reliable summary was produced.",
                "confidence": "low",
                "inspected_paths": ["README.md", "docs/guide.md"],
            },
        },
        timestamp=1.0,
    )

    line = ConversationCompactor._message_to_line(message)

    assert "spawn_subagent:failed/invalid_summary" in line
    assert "No reliable summary was produced." in line
    assert "inspected=2" in line


def test_compaction_keeps_tool_call_pair_together() -> None:
    from pp_agent.runtime.compaction import ConversationCompactor
    from pp_agent.domain import CompactionState

    messages = [
        ChatMessage(role="user", content=[TextPart(text="older request")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="older answer")], timestamp=2.0),
        ChatMessage(
            role="assistant",
            content=[ToolCallPart(id="call-1", name="grep_code", arguments={"query": "AgentRuntime"})],
            timestamp=3.0,
        ),
        ChatMessage(role="tool", tool_call_id="call-1", tool_name="grep_code", content=[TextPart(text="src/pp_agent/runtime/runtime.py")], timestamp=4.0),
        ChatMessage(role="user", content=[TextPart(text="continue with the runtime change")], timestamp=5.0),
    ]

    state = ConversationCompactor(keep_recent_messages=2).compact(messages, CompactionState())

    assert state.summarized_message_count == 2
    assert "Tools mentioned:" in state.summary
    assert "grep_code" in state.summary


def test_compaction_summary_has_stable_sections() -> None:
    from pp_agent.runtime.compaction import ConversationCompactor
    from pp_agent.domain import CompactionState

    messages = [
        ChatMessage(role="user", content=[TextPart(text="todo: update tests/test_memory_retrieval.py next")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="Edited src/pp_agent/memory/retrieval.py")], timestamp=2.0),
        ChatMessage(role="user", content=[TextPart(text="current work is memory recall")], timestamp=3.0),
    ]

    state = ConversationCompactor(keep_recent_messages=1, max_summary_chars=800).compact(messages, CompactionState(summary="Old summary line"))

    assert "Previously compacted context:" in state.summary
    assert "Newly compacted context:" in state.summary
    assert "Current work:" in state.summary
    assert "Pending work:" in state.summary
    assert "Key files referenced:" in state.summary
    assert "Tools mentioned:" in state.summary
