from __future__ import annotations

from typing import Any, Iterable, List, Optional

from pp_agent.context.budget import ContextItemSummary
from pp_agent.context.item import ContextItem
from pp_agent.context.pack import ContextPack
from pp_agent.context.pipeline import ContextPipeline, ContextPipelineConfig
from pp_agent.context.source_ref import SourceRef
from pp_agent.domain import ChatMessage, TextPart, ToolCallPart


CORE_MEMORY_METADATA_KEY = "core_memory_snapshot"
RECALL_METADATA_KEY = "memory_recall"
CONTEXT_TRACE_PAYLOAD_VERSION = 2


SECTION_FIELDS = {
    "system_instructions": "system_instructions",
    "model_profile_summary": "model_profile_summary",
    "runtime_profile_summary": "runtime_profile_summary",
    "core_memory_snapshot": "core_memory_snapshot",
    "episodic_memory_items": "episodic_memory_items",
    "attachment_previews": "attachment_previews",
    "selected_capabilities": "selected_capabilities",
    "project_context": "project_context",
    "recent_turns": "recent_turns",
    "runtime_notes": "runtime_notes",
}


def build_context_pack_from_messages(
    *,
    state: Any,
    messages: list[ChatMessage],
    model_profile: Any = None,
    runtime_profile: Any = None,
    hook_metadata: Optional[dict[str, object]] = None,
    config: Optional[ContextPipelineConfig] = None,
    strict_core_memory: bool = False,
) -> ContextPack:
    """Build a ContextPack from the final Runtime message list without changing provider input."""

    categorized = _items_from_messages(messages, state=state, hook_metadata=hook_metadata or {})
    pipeline = ContextPipeline(config)
    pack = pipeline.build(
        user_message=_latest_user_text(messages),
        session_state=None,
        model_profile=model_profile,
        runtime_profile=runtime_profile,
        memory_providers={
            "core_memory_snapshot": categorized["core_memory_snapshot"],
            "episodic_memory_items": categorized["episodic_memory_items"],
        },
        attachment_providers=categorized["attachment_previews"],
        capability_selection=categorized["selected_capabilities"],
        project_context_providers=categorized["project_context"],
        system_instructions=categorized["system_instructions"],
        runtime_notes=categorized["runtime_notes"],
        strict_core_memory=strict_core_memory,
    )
    recent_pack = pipeline.build(
        user_message=_latest_user_text(messages),
        project_context_providers=[],
        system_instructions=[],
        runtime_notes=[],
        strict_core_memory=False,
    )
    pack.recent_turns = categorized["recent_turns"] or recent_pack.recent_turns
    pack.source_refs = _unique_source_refs([item.source_ref for section in _pack_sections(pack) for item in section])
    return pack


def context_pack_to_trace_details(pack: ContextPack) -> dict[str, object]:
    """Return trace-safe ContextPack details for Runtime events and spans."""

    report = pack.budget_report.model_dump(mode="json")
    sections = {
        section: {
            "count": len(items),
            "estimated_chars": sum(item.budget_chars for item in items),
            "item_ids": [item.id for item in items],
        }
        for section, items in _pack_section_map(pack).items()
    }
    return {
        "context_payload_version": CONTEXT_TRACE_PAYLOAD_VERSION,
        "context": {
            "budget_report": report,
            "included_sources": [item.model_dump(mode="json") for item in pack.budget_report.included_items],
            "dropped_sources": [item.model_dump(mode="json") for item in pack.budget_report.dropped_items],
            "sections": sections,
            "pack_summary": {
                "source_refs": [ref.summary() for ref in pack.source_refs],
                "included_count": len(pack.budget_report.included_items),
                "dropped_count": len(pack.budget_report.dropped_items),
                "used": pack.budget_report.used,
                "total_budget": pack.budget_report.total_budget,
            },
            "core_memory_budget_error": any(
                item.reason == "core_memory_budget_exceeded_not_truncated" for item in pack.budget_report.dropped_items
            ),
            **_memory_recall_trace(pack),
        },
    }


class SkillContextAdapter:
    """Adapts Skill progressive disclosure providers into ContextPipeline inputs."""

    def __init__(self, provider: Any) -> None:
        self.provider = provider
        self.dropped_items: list[ContextItemSummary] = []

    def level0_items(self) -> list[ContextItem]:
        """Return metadata-only skill cards for selected capabilities or project context."""

        return self.provider.list_level0()

    def level1_items(self, skill_names: Iterable[str]) -> list[ContextItem]:
        """Return explicitly selected level 1 skill bodies."""

        return [self.provider.load_level1(name) for name in skill_names]

    def level2_items(self, artifacts: Iterable[tuple[str, str]]) -> list[ContextItem]:
        """Return explicitly selected level 2 artifacts and record denied paths as drops."""

        items: list[ContextItem] = []
        for skill_name, relative_path in artifacts:
            try:
                items.append(self.provider.load_level2(skill_name, relative_path))
            except ValueError:
                item_id = f"skill:{skill_name}:level2:{relative_path}"
                self.dropped_items.append(
                    ContextItemSummary(
                        id=item_id,
                        type="project_context",
                        title=f"Skill {skill_name} artifact {relative_path}",
                        section="project_context",
                        priority=75,
                        estimated_chars=0,
                        source_ref={
                            "source_type": "project_map",
                            "source_id": f"skill:{skill_name}",
                            "relative_path": relative_path,
                        },
                        reason="skill_artifact_path_denied",
                    )
                )
        return items


class MCPContextAdapter:
    """Adapts MCP descriptor cards and policy drops into ContextPipeline inputs."""

    def __init__(self, provider: Any) -> None:
        self.provider = provider
        self._dropped_items: list[ContextItemSummary] = []

    @property
    def dropped_items(self) -> list[ContextItemSummary]:
        """Return BudgetReport-compatible drops from the underlying MCP provider."""

        return list(self._dropped_items)

    def tool_items(self, server_name: str) -> list[ContextItem]:
        """Return model-facing MCP tool cards that passed overlay and metadata scan."""

        items = self.provider.tool_cards(server_name)
        self._dropped_items.extend(getattr(self.provider, "dropped_items", []))
        return items

    def resource_items(self, server_name: str) -> list[ContextItem]:
        """Return model-facing MCP resource cards that passed metadata scan."""

        items = self.provider.resource_cards(server_name)
        self._dropped_items.extend(getattr(self.provider, "dropped_items", []))
        return items

    def prompt_items(self, server_name: str) -> list[ContextItem]:
        """Return model-facing MCP prompt cards that passed metadata scan."""

        items = self.provider.prompt_cards(server_name)
        self._dropped_items.extend(getattr(self.provider, "dropped_items", []))
        return items


def _items_from_messages(messages: list[ChatMessage], *, state: Any, hook_metadata: dict[str, object]) -> dict[str, list[ContextItem]]:
    """Classify final model messages into ContextPack sections."""

    categorized = {section: [] for section in SECTION_FIELDS}
    for index, message in enumerate(messages):
        text = _message_text(message)
        if not text:
            continue
        section, item_type, source_ref, priority = _classify_message(message, text=text, index=index)
        categorized[section].append(
            ContextItem(
                id=f"message:{index}:{section}",
                type=item_type,
                title=_title_for(section, message, index),
                content=text,
                source_ref=source_ref,
                priority=priority,
                metadata={
                    "role": message.role,
                    "message_index": index,
                    "classification": "metadata" if message.metadata else "fallback",
                    "hook_metadata_keys": sorted(hook_metadata.keys()),
                    "preview": _safe_preview(text),
                },
            )
        )
    return categorized


def _classify_message(message: ChatMessage, *, text: str, index: int) -> tuple[str, str, SourceRef, int]:
    """Map an injected or conversation message to a ContextPack section."""

    metadata = message.metadata or {}
    if CORE_MEMORY_METADATA_KEY in metadata:
        core = metadata.get(CORE_MEMORY_METADATA_KEY) if isinstance(metadata.get(CORE_MEMORY_METADATA_KEY), dict) else {}
        return (
            "core_memory_snapshot",
            "core_memory",
            SourceRef(source_type="core_memory", source_id=str(core.get("snapshot_hash") or core.get("workspace_id") or "core_memory")),
            95,
        )
    if RECALL_METADATA_KEY in metadata:
        recall = metadata.get(RECALL_METADATA_KEY) if isinstance(metadata.get(RECALL_METADATA_KEY), dict) else {}
        return (
            "episodic_memory_items",
            "episodic_memory",
            SourceRef(source_type="episodic_memory", source_id=str(recall.get("retrieval_version") or "memory_recall"), metadata=_trace_safe_metadata(recall)),
            70,
        )
    if text.startswith("Runtime notes:"):
        return ("runtime_notes", "runtime_note", SourceRef(source_type="conversation", source_id="runtime_notes"), 85)
    if text.startswith("Current session attachments:"):
        return ("attachment_previews", "attachment_preview", SourceRef(source_type="attachment", source_id="session_attachments"), 75)
    if text.startswith("Active skills loaded for this turn:"):
        return ("selected_capabilities", "capability", SourceRef(source_type="capability", source_id="skill_runtime"), 65)
    if message.role == "system" and index == 0:
        return ("system_instructions", "system_instruction", SourceRef(source_type="conversation", source_id="system_prompt"), 100)
    if message.role == "system":
        source_type = "project_map" if "project" in text.lower() else "conversation"
        return ("project_context", "project_context", SourceRef(source_type=source_type, source_id=f"system_context:{index}"), 45)
    return ("recent_turns", "conversation", SourceRef(source_type="conversation", source_id=f"message:{index}"), 20)


def _message_text(message: ChatMessage) -> str:
    """Extract bounded text from a ChatMessage while avoiding full tool payloads."""

    parts: list[str] = []
    for part in message.content:
        if isinstance(part, TextPart):
            parts.append(part.text)
        elif isinstance(part, ToolCallPart):
            parts.append(f"Tool call requested: {part.name} ({part.id})")
    text = "\n".join(item.strip() for item in parts if item and item.strip()).strip()
    if message.role == "tool" and len(text) > 1200:
        return text[:1200] + "\n[tool output preview truncated for context trace]"
    return text


def _latest_user_text(messages: list[ChatMessage]) -> str:
    """Return the latest user text for provider-like callbacks."""

    for message in reversed(messages):
        if message.role == "user":
            return _message_text(message)
    return ""


def _title_for(section: str, message: ChatMessage, index: int) -> str:
    """Create a stable human-readable item title."""

    if section == "recent_turns":
        return f"{message.role} message {index}"
    return section.replace("_", " ").title()


def _safe_preview(text: str, limit: int = 240) -> str:
    """Build a short trace preview without changing item content."""

    collapsed = " ".join(text.split())
    return collapsed[:limit]


def _trace_safe_metadata(metadata: object) -> dict[str, object]:
    """Keep only small scalar metadata values for source references."""

    if not isinstance(metadata, dict):
        return {}
    safe: dict[str, object] = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
        elif isinstance(value, list):
            safe[str(key)] = [str(item)[:120] for item in value[:10]]
    return safe


def _pack_section_map(pack: ContextPack) -> dict[str, list[ContextItem]]:
    """Return all ContextPack item sections by public section name."""

    return {section: list(getattr(pack, field)) for section, field in SECTION_FIELDS.items()}


def _pack_sections(pack: ContextPack) -> Iterable[list[ContextItem]]:
    """Iterate item sections in ContextPack order."""

    return _pack_section_map(pack).values()


def _memory_recall_trace(pack: ContextPack) -> dict[str, object]:
    """Expose episodic memory recall only through the canonical context payload."""

    for item in pack.episodic_memory_items:
        metadata = item.source_ref.metadata or {}
        if metadata:
            return {"memory_recall": metadata}
    return {}


def _unique_source_refs(refs: Iterable[SourceRef]) -> List[SourceRef]:
    """Deduplicate source refs while preserving order."""

    seen: set[tuple[object, ...]] = set()
    unique: list[SourceRef] = []
    for ref in refs:
        key = (ref.source_type, ref.source_id, ref.path, ref.line_start, ref.line_end, ref.page, ref.heading)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique
