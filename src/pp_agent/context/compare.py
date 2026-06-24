from __future__ import annotations

import hashlib
from typing import Any

from pp_agent.context.pack import ContextPack
from pp_agent.domain import ChatMessage, TextPart


SECRET_MARKERS = ("api_key", "token", "secret", "password")
CRITICAL_WARNING_MARKERS = ("critical", "budget_error", "unsupported")


def compare_legacy_and_pipeline_messages(
    *,
    legacy_messages: list[ChatMessage],
    pack: ContextPack,
) -> dict[str, object]:
    """Return a secret-safe comparison between legacy hook messages and pipeline rendering."""

    pipeline_messages = list(pack.final_messages or [])
    legacy_sections = _message_section_counts(legacy_messages)
    pipeline_sections = _message_section_counts(pipeline_messages)
    return {
        "legacy_message_count": len(legacy_messages),
        "pipeline_message_count": len(pipeline_messages),
        "message_count_diff": len(pipeline_messages) - len(legacy_messages),
        "system_message_diff": _system_summary(pipeline_messages) != _system_summary(legacy_messages),
        "current_user_message_consistent": _latest_user_text(legacy_messages) == _latest_user_text(pipeline_messages),
        "markdown_memory_consistent": _count_section(pack, "markdown_memory") == pipeline_sections.get("markdown_memory", 0),
        "attachments_consistent": legacy_sections.get("attachments", 0) <= pipeline_sections.get("attachments", 0),
        "capabilities_consistent": _count_section(pack, "capabilities") == pipeline_sections.get("capabilities", 0),
        "mcp_consistent": _count_section(pack, "mcp") == pipeline_sections.get("mcp", 0),
        "skills_consistent": _count_section(pack, "skills") == pipeline_sections.get("skills", 0),
        "legacy_total_chars": _message_chars(legacy_messages),
        "pipeline_total_chars": _message_chars(pipeline_messages),
        "total_chars_diff": _message_chars(pipeline_messages) - _message_chars(legacy_messages),
        "dropped_item_summary": _dropped_summary(pack),
        "source_refs_summary": _source_refs_summary(pack),
        "sections": {
            "legacy": legacy_sections,
            "pipeline": pipeline_sections,
            "pack": _pack_section_counts(pack),
        },
        "message_hashes": {
            "legacy": _message_hashes(legacy_messages),
            "pipeline": _message_hashes(pipeline_messages),
        },
    }


def fallback_reason_for_auto(
    *,
    legacy_messages: list[ChatMessage],
    pack: ContextPack | None,
    diff_summary: dict[str, object] | None,
    render_error: Exception | None = None,
) -> str | None:
    """Explain why auto mode should keep legacy messages instead of pipeline output."""

    if render_error is not None:
        return "context_render_exception"
    if pack is None or not pack.final_messages:
        return "context_render_exception"
    if not _has_system_instruction(pack.final_messages):
        return "system_instruction_missing"
    if _latest_user_text(legacy_messages) and not _latest_user_text(pack.final_messages):
        return "protected_current_user_message_missing"
    if any(_is_critical_warning(warning) for warning in pack.warnings):
        return "critical_budget_warning"
    if any(message.metadata.get("connector_context_unsupported") for message in legacy_messages):
        return "unsupported_connector_context"
    if diff_summary:
        if diff_summary.get("attachments_consistent") is False:
            return "attachment_render_mismatch"
        visibility_keys = ("capabilities_consistent", "mcp_consistent", "skills_consistent")
        if any(diff_summary.get(key) is False for key in visibility_keys):
            return "tool_capability_visibility_mismatch"
    return None


def trace_context_pack_payload(pack: ContextPack, diff_summary: dict[str, object] | None = None) -> dict[str, object]:
    """Return the stable TraceInspect-ready fields for ContextPack v3 display."""

    return {
        "context_pack_v3": {
            "sections": _pack_section_counts(pack),
            "per_section_usage": pack.budget_report.model_dump(mode="json").get("per_section", {}),
            "included_items": [item.model_dump(mode="json") for item in pack.budget_report.included_items],
            "dropped_items": [item.model_dump(mode="json") for item in pack.budget_report.dropped_items],
            "source_refs": [ref.summary() for ref in pack.source_refs],
            "markdown_memory": {
                "paths": [item.source_ref.path for item in pack.markdown_memory if item.source_ref.path],
                "content_hash": [
                    item.source_ref.metadata.get("content_hash")
                    for item in pack.markdown_memory
                    if item.source_ref.metadata.get("content_hash")
                ],
            },
            "core_governance": {"prompt_injection_disabled": True, "included_count": len(pack.core_governance)},
            "mcp": _compact_card_summary(pack.mcp),
            "skills": _compact_card_summary(pack.skills),
            "diff_summary": diff_summary or {},
        }
    }


def _message_text(message: ChatMessage) -> str:
    return "\n".join(part.text for part in message.content if isinstance(part, TextPart))


def _latest_user_text(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return _message_text(message).strip()
    return ""


def _message_chars(messages: list[ChatMessage]) -> int:
    return sum(len(_message_text(message)) for message in messages)


def _message_hashes(messages: list[ChatMessage]) -> list[dict[str, object]]:
    return [
        {
            "role": message.role,
            "context_section": message.metadata.get("context_section") if message.metadata else None,
            "sha256": hashlib.sha256(_message_text(message).encode("utf-8")).hexdigest()[:16],
            "chars": len(_message_text(message)),
        }
        for message in messages
    ]


def _system_summary(messages: list[ChatMessage]) -> list[str]:
    return [hashlib.sha256(_message_text(message).encode("utf-8")).hexdigest()[:16] for message in messages if message.role == "system"]


def _message_section_counts(messages: list[ChatMessage]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for message in messages:
        section = str((message.metadata or {}).get("context_section") or message.role)
        counts[section] = counts.get(section, 0) + 1
    return counts


def _pack_section_counts(pack: ContextPack) -> dict[str, int]:
    return {
        "system": len(pack.system),
        "markdown_memory": len(pack.markdown_memory),
        "core_governance": len(pack.core_governance),
        "project_context": len(pack.project_context),
        "episodic_recall": len(pack.episodic_recall),
        "file_memory_preview": len(pack.file_memory_preview),
        "attachments": len(pack.attachments),
        "capabilities": len(pack.capabilities),
        "mcp": len(pack.mcp),
        "skills": len(pack.skills),
        "conversation": len(pack.conversation),
        "runtime_notes": len(pack.runtime_notes),
    }


def _count_section(pack: ContextPack, section: str) -> int:
    return int(_pack_section_counts(pack).get(section, 0))


def _dropped_summary(pack: ContextPack) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in pack.budget_report.dropped_items:
        reason = item.reason or "dropped"
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _source_refs_summary(pack: ContextPack) -> dict[str, object]:
    by_type: dict[str, int] = {}
    for ref in pack.source_refs:
        by_type[ref.source_type] = by_type.get(ref.source_type, 0) + 1
    return {"count": len(pack.source_refs), "by_type": by_type}


def _compact_card_summary(items: list[Any]) -> list[dict[str, object]]:
    return [{"id": item.id, "title": item.title, "source_ref": item.source_ref.summary()} for item in items[:20]]


def _has_system_instruction(messages: list[ChatMessage]) -> bool:
    return bool(messages and messages[0].role == "system" and _message_text(messages[0]).strip())


def _is_critical_warning(warning: object) -> bool:
    lowered = str(warning).lower()
    return any(marker in lowered for marker in CRITICAL_WARNING_MARKERS)
