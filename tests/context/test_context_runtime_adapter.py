from __future__ import annotations

import json

from pp_agent.context.adapters import build_context_pack_from_messages, context_pack_to_trace_details
from pp_agent.domain import ChatMessage, TextPart


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

    assert pack.system_instructions[0].id == "message:0:system_instructions"
    assert pack.runtime_notes[0].id == "message:1:runtime_notes"
    assert pack.core_memory_snapshot[0].source_ref.source_type == "core_memory"
    assert pack.episodic_memory_items[0].source_ref.source_type == "episodic_memory"
    assert pack.attachment_previews[0].source_ref.source_type == "attachment"
    assert pack.selected_capabilities[0].source_ref.source_type == "capability"
    assert pack.recent_turns[0].source_ref.source_type == "conversation"


def test_context_trace_details_do_not_include_attachment_full_content() -> None:
    messages = [
        _message("system", "You are pp-Echo."),
        _message("system", "Current session attachments:\n- att1 preview_only=short SECRET_FULL_TEXT_SHOULD_NOT_TRACE"),
    ]

    details = context_pack_to_trace_details(build_context_pack_from_messages(state=None, messages=messages))

    assert "SECRET_FULL_TEXT_SHOULD_NOT_TRACE" not in json.dumps(details, ensure_ascii=False)
    assert details["context_payload_version"] == 2
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
