from pathlib import Path

from agent_core.types import ChatMessage, ModelConfig, TextPart
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
