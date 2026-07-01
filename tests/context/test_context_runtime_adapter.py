from __future__ import annotations

import json
from pathlib import Path

from pp_agent.capabilities.descriptor import CapabilityDescriptor
from pp_agent.capabilities.router import BlockedCapability, CapabilitySelection
from pp_agent.context.adapters import build_context_pack_from_messages, context_pack_to_trace_details
from pp_agent.context.runtime_bridge import build_runtime_context_pack
from pp_agent.coding.repository import repository_analysis_to_context_item
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.state import AgentState
from pp_agent.storage.settings import Settings


CORE_MEMORY_METADATA_KEY = "core_memory_snapshot"
RECALL_METADATA_KEY = "memory_recall"


def _message(role: str, text: str, *, metadata: dict | None = None) -> ChatMessage:
    return ChatMessage(role=role, content=[TextPart(text=text)], metadata=metadata or {}, timestamp=0.0)  # type: ignore[arg-type]


def test_adapter_classifies_runtime_context_messages() -> None:
    messages = [
        _message("system", "You are pp-Echo."),
        _message("system", "Runtime notes:\n- Active session id: s1."),
        _message("system", "Core memory snapshot", metadata={CORE_MEMORY_METADATA_KEY: {"workspace_id": "w1", "snapshot_hash": "h1"}}),
        _message("system", "Relevant long-term memory snippets", metadata={RECALL_METADATA_KEY: {"retrieval_version": "v2"}}),
        _message("system", "Current session attachments:\n- att1 preview_only=short"),
        _message("system", "Active skills loaded for this turn:\n- python"),
        _message("user", "hello"),
    ]

    pack = build_context_pack_from_messages(state=None, messages=messages)

    assert pack.system_instructions[0].id == "message:0:system"
    assert pack.runtime_notes[0].id == "message:1:runtime_notes"
    assert pack.core_memory_snapshot[0].source_ref.source_type == "core_governance"
    assert pack.episodic_memory_items[0].source_ref.source_type == "episodic_memory"
    assert pack.attachment_previews[0].source_ref.source_type == "attachment"
    assert pack.skills[0].source_ref.source_type == "skill"
    assert pack.recent_turns[0].source_ref.source_type == "conversation"


def test_context_trace_details_do_not_include_attachment_full_content() -> None:
    messages = [
        _message("system", "You are pp-Echo."),
        _message("system", "Current session attachments:\n- att1 preview_only=short SECRET_FULL_TEXT_SHOULD_NOT_TRACE"),
    ]

    details = context_pack_to_trace_details(build_context_pack_from_messages(state=None, messages=messages))

    assert "SECRET_FULL_TEXT_SHOULD_NOT_TRACE" not in json.dumps(details, ensure_ascii=False)
    assert details["context_payload_version"] == 3
    assert details["context"]["sections"]["attachment_previews"]["count"] == 1  # type: ignore[index]
    assert "context_budget_report" not in details


def test_core_memory_budget_error_is_trace_visible_without_mutating_messages() -> None:
    messages = [
        _message("system", "You are pp-Echo."),
        _message("system", "x" * 4000, metadata={CORE_MEMORY_METADATA_KEY: {"workspace_id": "w1"}}),
        _message("user", "hello"),
    ]
    before = [message.model_dump(mode="json") for message in messages]

    pack = build_context_pack_from_messages(state=None, messages=messages)
    details = context_pack_to_trace_details(pack)

    assert [message.model_dump(mode="json") for message in messages] == before
    assert details["context"]["core_memory_budget_error"] is True
    assert details["context"]["dropped_sources"][0]["reason"] == "core_memory_budget_exceeded_not_truncated"  # type: ignore[index]


def test_runtime_bridge_adds_capability_selection_and_blocks_dropped(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    selection = CapabilitySelection(
        selected=[
            CapabilityDescriptor(
                kind="builtin_tool",
                name="list_files",
                description="List files",
                source="builtin:list_files",
                risk_level="read",
            )
        ],
        blocked=[BlockedCapability(capability_id="run_shell", reason="trust_denied", policy="deny")],
    )

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        capability_selection=selection,
    )
    rendered_text = "\n".join(part.text for message in pack.final_messages for part in message.content if isinstance(part, TextPart))

    assert pack.capabilities[0].id == "capability:list_files"
    assert pack.budget_report.drop_reasons["capability:run_shell"] == "capability_blocked"
    assert "run_shell" not in rendered_text


def test_runtime_bridge_includes_repository_analysis_in_project_context(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
    )

    assert any(item.title == "Repository analysis" for item in pack.project_context)
    assert any(item.metadata.get("repository_analysis") for item in pack.project_context)
    assert repository_analysis_to_context_item.__doc__
