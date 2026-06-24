from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from pp_agent.cli.commands.context import context_compare_messages_main, context_replay_trace_main
from pp_agent.context.compare import compare_legacy_and_pipeline_messages
from pp_agent.context.runtime_bridge import build_runtime_context_pack
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.llm import ModelConfig
from pp_agent.observability.recorder import TraceRecorder
from pp_agent.observability.store import TraceStore
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.runtime.state import AgentState
from pp_agent.storage.sessions import SessionStore
from pp_agent.storage.settings import Settings
from pp_agent.tools.registry import ToolRegistry


class NoopLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()
        self.seen_messages: list[list[ChatMessage]] = []

    def stream_chat(self, messages, tools=None) -> Iterator[dict]:
        self.seen_messages.append(list(messages))
        yield {"text": "ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def _runtime(tmp_path: Path, *, mode: str) -> tuple[AgentRuntime, NoopLLMClient]:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    client = NoopLLMClient()
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


def test_context_compare_messages_json(tmp_path: Path) -> None:
    (tmp_path / "MEMORY.md").write_text("# Project Memory\n\nGrey memory.\n", encoding="utf-8")

    payload = context_compare_messages_main(tmp_path, prompt="hello", json_mode=False)

    assert payload["diff_summary"]["pipeline_message_count"] > 0  # type: ignore[index]
    assert payload["diff_summary"]["source_refs_summary"]["count"] > 0  # type: ignore[index]


def test_context_pipeline_shadow_records_diff(tmp_path: Path) -> None:
    runtime, client = _runtime(tmp_path, mode="shadow")

    events = runtime.prompt("hello shadow")
    details = [event.details for event in events if event.type == "context_built"][-1]

    assert details["pipeline_mode"] == "shadow"
    assert details["pipeline_used"] is False
    assert details["diff_summary"]["pipeline_message_count"] > 0
    assert client.seen_messages[-1] == client.seen_messages[-1]


def test_context_pipeline_auto_fallback_records_reason(tmp_path: Path) -> None:
    runtime, _client = _runtime(tmp_path, mode="auto")
    runtime.runtime_hooks.add_transform_context_hook(
        "unsupported_connector",
        "test",
        lambda _state, messages: [
            message.model_copy(update={"metadata": {"connector_context_unsupported": True}}) if index == 0 else message
            for index, message in enumerate(messages)
        ],
    )

    events = runtime.prompt("hello auto fallback")
    details = [event.details for event in events if event.type == "context_built"][-1]

    assert details["pipeline_mode"] == "auto"
    assert details["pipeline_used"] is False
    assert details["fallback_reason"] == "unsupported_connector_context"


def test_context_pipeline_on_uses_pipeline_messages(tmp_path: Path) -> None:
    (tmp_path / "MEMORY.md").write_text("# Project Memory\n\nPipeline on memory.\n", encoding="utf-8")
    runtime, client = _runtime(tmp_path, mode="on")

    events = runtime.prompt("hello on")
    details = [event.details for event in events if event.type == "context_built"][-1]
    system_text = "\n".join(part.text for message in client.seen_messages[-1] if message.role == "system" for part in message.content)

    assert details["pipeline_mode"] == "on"
    assert details["pipeline_used"] is True
    assert "Pipeline on memory." in system_text


def test_context_pipeline_replay_trace_smoke(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    trace_store = TraceStore(tmp_path)
    runtime = AgentRuntime(
        llm_client=NoopLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        require_plan_approval=False,
        observability=TraceRecorder(trace_store, workspace=tmp_path),
    )
    runtime.restore_session_record(record)
    runtime.prompt("hello trace")

    payload = context_replay_trace_main(tmp_path, session_id=record.id, json_mode=False)

    assert payload["context_payload_version"] == 3
    assert "diff_summary" in payload


def test_context_pack_v3_trace_payload_shape(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[
            ChatMessage(role="system", content=[TextPart(text="system")], timestamp=0),
            ChatMessage(role="user", content=[TextPart(text="hello")], timestamp=0),
        ],
        settings=settings,
        session_id="s1",
    )
    diff = compare_legacy_and_pipeline_messages(legacy_messages=pack.final_messages, pack=pack)

    assert "dropped_item_summary" in diff
    assert "source_refs_summary" in diff
    assert isinstance(pack.budget_report.model_dump(mode="json")["per_section"], dict)


def test_context_pipeline_no_secret_in_diff_summary(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    settings.context_pipeline.section_budgets = {}
    messages = [
        ChatMessage(role="system", content=[TextPart(text="system")], timestamp=0),
        ChatMessage(role="system", content=[TextPart(text="secret context")], metadata={"api_key": "SHOULD_NOT_LEAK"}, timestamp=0),
        ChatMessage(role="user", content=[TextPart(text="hello")], timestamp=0),
    ]
    pack = build_runtime_context_pack(state=AgentState(system_prompt="system"), messages=messages, settings=settings, session_id="s1")
    payload = json.dumps(compare_legacy_and_pipeline_messages(legacy_messages=messages, pack=pack), ensure_ascii=False)

    assert "SHOULD_NOT_LEAK" not in payload
    assert "api_key" not in payload
