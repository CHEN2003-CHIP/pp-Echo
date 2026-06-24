from __future__ import annotations

CANONICAL_SECTIONS: tuple[str, ...] = (
    "system",
    "markdown_memory",
    "core_governance",
    "project_context",
    "episodic_recall",
    "file_memory_preview",
    "attachments",
    "capabilities",
    "mcp",
    "skills",
    "conversation",
    "runtime_notes",
)

TRACE_ONLY_SECTIONS: tuple[str, ...] = (
    "model_profile_summary",
    "runtime_profile_summary",
)

SECTION_ALIASES: dict[str, str] = {
    "system_instructions": "system",
    "core_memory_snapshot": "core_governance",
    "episodic_memory_items": "episodic_recall",
    "attachment_previews": "attachments",
    "selected_capabilities": "capabilities",
    "recent_turns": "conversation",
}

SECTION_FIELDS: dict[str, str] = {
    **{section: section for section in CANONICAL_SECTIONS},
    **{section: section for section in TRACE_ONLY_SECTIONS},
    "system_instructions": "system_instructions",
    "core_memory_snapshot": "core_memory_snapshot",
    "episodic_memory_items": "episodic_memory_items",
    "attachment_previews": "attachment_previews",
    "selected_capabilities": "selected_capabilities",
    "recent_turns": "recent_turns",
}

SECTION_ITEM_TYPES: dict[str, str] = {
    "system": "system_instruction",
    "markdown_memory": "markdown_memory",
    "core_governance": "core_governance",
    "project_context": "project_context",
    "episodic_recall": "episodic_memory",
    "file_memory_preview": "file_memory_preview",
    "attachments": "attachment_preview",
    "capabilities": "capability",
    "mcp": "mcp",
    "skills": "skill",
    "conversation": "conversation",
    "runtime_notes": "runtime_note",
}

SECTION_SOURCE_TYPES: dict[str, str] = {
    "system": "system",
    "markdown_memory": "markdown_memory",
    "core_governance": "core_governance",
    "project_context": "project_context",
    "episodic_recall": "episodic_memory",
    "file_memory_preview": "file_memory",
    "attachments": "attachment",
    "capabilities": "capability",
    "mcp": "mcp",
    "skills": "skill",
    "conversation": "conversation",
    "runtime_notes": "runtime",
}

SECTION_PRIORITIES: dict[str, int] = {
    "system": 100,
    "markdown_memory": 88,
    "core_governance": 10,
    "project_context": 60,
    "episodic_recall": 70,
    "file_memory_preview": 55,
    "attachments": 65,
    "capabilities": 60,
    "mcp": 50,
    "skills": 50,
    "runtime_notes": 85,
    "conversation": 20,
}


def canonical_section(section: str) -> str:
    """Normalize legacy section names into the ContextPipeline section vocabulary."""

    candidate = SECTION_ALIASES.get(section, section)
    return candidate if candidate in CANONICAL_SECTIONS else ""
