from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pp_agent.context.runtime_bridge import build_runtime_context_pack
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.llm import ModelConfig
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.runtime.state import AgentState
from pp_agent.storage.sessions import SessionStore
from pp_agent.storage.settings import Settings
from pp_agent.tools.registry import ToolRegistry


class RecordingLLMClient:
    def __init__(self, *, tool_first: bool = False) -> None:
        self.model = ModelConfig()
        self.tool_first = tool_first
        self.calls = 0
        self.seen_messages: list[list[ChatMessage]] = []

    def stream_chat(self, messages, tools=None) -> Iterator[dict]:
        self.calls += 1
        self.seen_messages.append(list(messages))
        if self.tool_first and self.calls == 1:
            yield {
                "text": "",
                "tool_calls": [{"id": "call-list", "name": "list_files", "arguments_chunk": '{"path":"."}'}],
                "finish_reason": "tool_calls",
                "raw": {},
            }
            return
        yield {"text": "ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def _runtime(tmp_path: Path, *, mode: str, llm: RecordingLLMClient | None = None) -> tuple[AgentRuntime, RecordingLLMClient]:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    client = llm or RecordingLLMClient()
    runtime = AgentRuntime(
        llm_client=client,
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        require_plan_approval=False,
    )
    runtime.restore_session_record(record)
    runtime.config_snapshot.settings.context_pipeline.context_pipeline_mode = mode
    runtime.context_pipeline_mode = mode
    return runtime, client


def _text(message: ChatMessage) -> str:
    return "\n".join(part.text for part in message.content if isinstance(part, TextPart))


def _texts(messages: list[ChatMessage], *, role: str | None = None, section: str | None = None) -> list[str]:
    return [
        _text(message)
        for message in messages
        if (role is None or message.role == role) and (section is None or message.metadata.get("context_section") == section)
    ]


def _section_order(messages: list[ChatMessage]) -> list[str]:
    order: list[str] = []
    for message in messages:
        section = str(message.metadata.get("context_section") or message.role)
        if section not in order:
            order.append(section)
    return order


def _context_hook(_state: AgentState, messages: list[ChatMessage]) -> list[ChatMessage]:
    injected = [
        ChatMessage(
            role="system",
            content=[TextPart(text="Approved memory: stable provider fact.")],
            metadata={"context_section": "episodic_recall", "source_type": "episodic_memory", "source_id": "approved-memory"},
            timestamp=0.0,
        ),
        ChatMessage(
            role="system",
            content=[TextPart(text="Current session attachments:\n- docs/spec.md: attachment preview must stay")],
            metadata={"context_section": "attachments", "source_type": "attachment", "source_id": "att-spec", "path": "docs/spec.md"},
            timestamp=0.0,
        ),
        ChatMessage(
            role="system",
            content=[TextPart(text="Tool card: list_files is available for workspace reads.")],
            metadata={"context_section": "capabilities", "source_type": "capability", "source_id": "list_files"},
            timestamp=0.0,
        ),
        ChatMessage(
            role="system",
            content=[TextPart(text="Runtime notes:\n- developer steering is stable.")],
            metadata={"context_section": "runtime_notes", "source_type": "runtime", "source_id": "developer-note"},
            timestamp=0.0,
        ),
    ]
    return [messages[0], *injected, *messages[1:]]


def test_provider_final_messages_by_rollout_mode(tmp_path: Path) -> None:
    (tmp_path / "MEMORY.md").write_text("# Project Memory\n\nMarkdown memory visible only through pipeline.\n", encoding="utf-8")

    observed: dict[str, tuple[list[ChatMessage], dict[str, object]]] = {}
    for mode in ("off", "shadow", "auto", "on"):
        runtime, client = _runtime(tmp_path / mode, mode=mode)
        (tmp_path / mode / "MEMORY.md").write_text("# Project Memory\n\nMarkdown memory visible only through pipeline.\n", encoding="utf-8")
        runtime.runtime_hooks.add_transform_context_hook("golden-context", "memory", _context_hook)

        events = runtime.prompt(f"hello {mode}")
        details = [event.details for event in events if event.type == "context_built"][-1]
        observed[mode] = (client.seen_messages[-1], details)

    off_messages, off_details = observed["off"]
    shadow_messages, shadow_details = observed["shadow"]
    auto_messages, auto_details = observed["auto"]
    on_messages, on_details = observed["on"]

    assert off_details["pipeline_used"] is False
    assert shadow_details["pipeline_used"] is False
    assert auto_details["pipeline_used"] is True
    assert on_details["pipeline_used"] is True

    assert not _texts(off_messages, section="markdown_memory")
    assert not _texts(shadow_messages, section="markdown_memory")
    assert _texts(auto_messages, section="markdown_memory")
    assert _texts(on_messages, section="markdown_memory")

    assert _texts(on_messages, role="user")[-1] == "hello on"
    assert _section_order(on_messages).index("system") < _section_order(on_messages).index("markdown_memory")
    assert _section_order(on_messages).index("episodic_recall") < _section_order(on_messages).index("attachments")
    assert _section_order(on_messages).index("attachments") < _section_order(on_messages).index("capabilities")
    assert _section_order(on_messages).index("runtime_notes") < _section_order(on_messages).index("conversation")
    assert shadow_details["diff_summary"]["pipeline_message_count"] > 0


def test_on_mode_provider_messages_include_current_capability_cards(tmp_path: Path) -> None:
    runtime, client = _runtime(tmp_path, mode="on")

    events = runtime.prompt("please list files")
    details = [event.details for event in events if event.type == "context_built"][-1]
    system_text = "\n".join(_texts(client.seen_messages[0], role="system"))

    assert details["pipeline_used"] is True
    assert "builtin:list_files" in system_text
    assert "List files" in system_text


def test_tool_observation_enters_next_provider_context_in_on_mode(tmp_path: Path) -> None:
    runtime, client = _runtime(tmp_path, mode="on", llm=RecordingLLMClient(tool_first=True))

    runtime.prompt("list files before answering")

    assert len(client.seen_messages) == 2
    second_call = client.seen_messages[1]
    assert any(message.role == "tool" and message.tool_name == "list_files" for message in second_call)
    assert any("test_context_pipeline_provider_golden.py" not in _text(message) for message in second_call if message.role == "tool")


def test_runtime_pack_budget_drops_are_deterministic_and_explained(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    settings.context_pipeline.total_budget = 60
    settings.context_pipeline.section_budgets = {"attachments": 1000, "capabilities": 1000, "conversation": 1000}
    messages = [
        ChatMessage(role="system", content=[TextPart(text="system")], timestamp=0.0),
        ChatMessage(
            role="system",
            content=[TextPart(text="A" * 45)],
            metadata={"context_section": "attachments", "source_type": "attachment", "source_id": "att-high"},
            timestamp=0.0,
        ),
        ChatMessage(
            role="system",
            content=[TextPart(text="B" * 45)],
            metadata={"context_section": "capabilities", "source_type": "capability", "source_id": "cap-low"},
            timestamp=0.0,
        ),
        ChatMessage(role="user", content=[TextPart(text="hello")], timestamp=0.0),
    ]

    first = build_runtime_context_pack(state=AgentState(system_prompt="system"), messages=messages, settings=settings, session_id="s1")
    second = build_runtime_context_pack(state=AgentState(system_prompt="system"), messages=messages, settings=settings, session_id="s1")

    assert [item.id for item in first.budget_report.dropped_items] == [item.id for item in second.budget_report.dropped_items]
    assert all(item.reason for item in first.budget_report.dropped_items)
    assert any(item.reason == "total_budget_exceeded" for item in first.budget_report.dropped_items)
    assert first.attachments
    assert not first.capabilities


def test_pending_core_memory_candidate_is_not_injected_into_final_messages(tmp_path: Path) -> None:
    runtime, client = _runtime(tmp_path, mode="on")
    runtime.state.memory_context["explicit_core_memory_by_turn"] = {
        "turn-1": {"memory_id": "pending-1", "status": "pending", "content": "PENDING MEMORY MUST NOT LEAK"}
    }

    runtime.prompt("hello memory governance")
    provider_text = "\n".join(_text(message) for message in client.seen_messages[-1])

    assert "PENDING MEMORY MUST NOT LEAK" not in provider_text
