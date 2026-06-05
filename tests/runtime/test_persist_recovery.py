from collections.abc import Iterator
from pathlib import Path

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.llm import ModelConfig
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.sessions import SessionStore
from pp_agent.tools.registry import ToolRegistry


class _NoopLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        if False:  # pragma: no cover
            yield {"text": "", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def test_runtime_persist_recovers_when_base_head_is_stale(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
        ChatMessage(role="user", content=[TextPart(text="u2")], timestamp=3.0),
        ChatMessage(role="assistant", content=[TextPart(text="a2")], timestamp=4.0),
    ]
    store.save(record)
    loaded = store.load(record.id)

    first_head = loaded.turn_nodes[0].id
    latest_head = loaded.active_head_id
    assert latest_head is not None

    agent = AgentRuntime(
        llm_client=_NoopLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=loaded.id,
        system_prompt=loaded.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
    )
    agent.restore_session_record(loaded)

    # Simulate the in-memory message branch being moved (e.g. external navigation/rewind)
    # while the runtime still thinks it should append to a newer base head.
    agent._base_head_id = latest_head
    agent.state.messages = store.branch_messages(loaded, first_head)
    agent.state.messages.append(ChatMessage(role="user", content=[TextPart(text="follow-up")], timestamp=5.0))

    agent._persist()

    saved = store.load(loaded.id)
    saved_branch = store.branch_messages(saved, saved.active_head_id)
    assert [message.role for message in saved_branch] == ["user", "assistant", "user"]
    assert saved_branch[-1].content[0].text == "follow-up"
