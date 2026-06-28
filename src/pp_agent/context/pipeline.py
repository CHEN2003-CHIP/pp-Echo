from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Dict, List, Mapping, Optional, Union

from pydantic import BaseModel, Field

from pp_agent.context.budget import ContextBudgetSectionUsage, ContextBudgeter, ContextItemSummary
from pp_agent.context.item import ContextItem
from pp_agent.context.markdown_memory import markdown_memory_items
from pp_agent.context.pack import ContextPack
from pp_agent.context.sections import CANONICAL_SECTIONS, SECTION_ALIASES
from pp_agent.context.source_ref import SourceRef
from pp_agent.domain import ChatMessage, TextPart


ContextProvider = Callable[..., Optional[Union[Iterable[ContextItem], ContextItem]]]


DEFAULT_SECTION_BUDGETS: dict[str, int] = {
    "system": 4000,
    "markdown_memory": 4000,
    "core_governance": 800,
    "project_context": 3000,
    "episodic_recall": 3000,
    "file_memory_preview": 1200,
    "attachments": 3000,
    "capabilities": 2500,
    "mcp": 1500,
    "skills": 1500,
    "conversation": 5000,
    "runtime_notes": 1000,
    "model_profile_summary": 1200,
    "runtime_profile_summary": 1200,
    "system_instructions": 4000,
    "core_memory_snapshot": 800,
    "episodic_memory_items": 3000,
    "attachment_previews": 3000,
    "selected_capabilities": 2500,
    "recent_turns": 5000,
}


class ContextPipelineConfig(BaseModel):
    """Budget and rollout controls for the final context-engine path."""

    total_budget: int = 30900
    section_budgets: Dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_SECTION_BUDGETS))
    use_context_pipeline_messages: bool = False
    debug_include_core_governance: bool = False


class ContextPipeline:
    """Final context orchestrator: it budgets and renders context, but never retrieves or stores it."""

    def __init__(self, config: Optional[ContextPipelineConfig] = None) -> None:
        self.config = config or ContextPipelineConfig()
        self.config.section_budgets = _normalize_section_budgets(self.config.section_budgets)

    def build(
        self,
        *,
        user_message: str,
        session_state: Optional[Any] = None,
        model_profile: Optional[Any] = None,
        runtime_profile: Optional[Any] = None,
        memory_providers: Optional[Mapping[str, Union[Iterable[ContextItem], ContextProvider]]] = None,
        attachment_providers: Optional[Union[Iterable[ContextItem], ContextProvider]] = None,
        capability_selection: Optional[Union[Iterable[ContextItem], ContextProvider, Any]] = None,
        conversation_items: Optional[Union[Iterable[ContextItem], ContextProvider]] = None,
        project_context_providers: Optional[Union[Iterable[ContextItem], ContextProvider]] = None,
        system_instructions: Optional[Union[Iterable[ContextItem], ContextProvider, str]] = None,
        runtime_notes: Optional[Union[Iterable[ContextItem], ContextProvider]] = None,
        strict_core_memory: bool = True,
        workspace: Optional[Any] = None,
        global_root: Optional[Any] = None,
        settings: Optional[Any] = None,
        pre_dropped_items: Optional[Iterable[ContextItemSummary]] = None,
    ) -> ContextPack:
        """Assemble a ContextPack; legacy arguments are normalized into canonical sections."""

        sections, warnings = self.collect_items(
            user_message=user_message,
            session_state=session_state,
            model_profile=model_profile,
            runtime_profile=runtime_profile,
            memory_providers=memory_providers,
            attachment_providers=attachment_providers,
            capability_selection=capability_selection,
            conversation_items=conversation_items,
            project_context_providers=project_context_providers,
            system_instructions=system_instructions,
            runtime_notes=runtime_notes,
            workspace=workspace,
            global_root=global_root,
            settings=settings,
        )
        return self.build_pack(
            sections,
            strict_core_memory=strict_core_memory,
            pre_dropped_items=pre_dropped_items,
            warnings=warnings,
        )

    def collect_items(
        self,
        *,
        user_message: str,
        session_state: Optional[Any] = None,
        model_profile: Optional[Any] = None,
        runtime_profile: Optional[Any] = None,
        memory_providers: Optional[Mapping[str, Union[Iterable[ContextItem], ContextProvider]]] = None,
        attachment_providers: Optional[Union[Iterable[ContextItem], ContextProvider]] = None,
        capability_selection: Optional[Union[Iterable[ContextItem], ContextProvider, Any]] = None,
        conversation_items: Optional[Union[Iterable[ContextItem], ContextProvider]] = None,
        project_context_providers: Optional[Union[Iterable[ContextItem], ContextProvider]] = None,
        system_instructions: Optional[Union[Iterable[ContextItem], ContextProvider, str]] = None,
        runtime_notes: Optional[Union[Iterable[ContextItem], ContextProvider]] = None,
        workspace: Optional[Any] = None,
        global_root: Optional[Any] = None,
        settings: Optional[Any] = None,
    ) -> tuple[dict[str, list[ContextItem]], list[str]]:
        """Collect provider outputs into canonical ContextPipeline sections."""

        markdown_items, warnings = markdown_memory_items(workspace=workspace, global_root=global_root, settings=settings)
        sections: dict[str, list[ContextItem]] = {
            "system": self._coerce_system_instructions(system_instructions),
            "markdown_memory": markdown_items,
            "core_governance": [],
            "project_context": self._collect(project_context_providers, user_message=user_message, session_state=session_state),
            "episodic_recall": [],
            "file_memory_preview": [],
            "attachments": self._collect(attachment_providers, user_message=user_message, session_state=session_state),
            "capabilities": [],
            "mcp": [],
            "skills": [],
            "conversation": self._collect(conversation_items, user_message=user_message, session_state=session_state)
            or self._recent_turn_items(session_state),
            "runtime_notes": self._collect(runtime_notes, user_message=user_message, session_state=session_state),
            "model_profile_summary": self._profile_items("model_profile_summary", "model_profile", model_profile),
            "runtime_profile_summary": self._profile_items("runtime_profile_summary", "runtime_profile", runtime_profile),
        }
        if memory_providers:
            sections["core_governance"] = self._collect(
                memory_providers.get("core_governance")
                or memory_providers.get("core_memory_snapshot")
                or memory_providers.get("core_memory")
            )
            sections["episodic_recall"] = self._collect(
                memory_providers.get("episodic_recall")
                or memory_providers.get("episodic_memory_items")
                or memory_providers.get("episodic_memory")
            )
            sections["file_memory_preview"] = self._collect(memory_providers.get("file_memory_preview"))
            sections["markdown_memory"].extend(self._collect(memory_providers.get("markdown_memory")))

        for item in self._coerce_capabilities(capability_selection, user_message=user_message):
            section = _section_for_context_item(item)
            sections.setdefault(section, []).append(item)
        return sections, warnings

    def build_pack(
        self,
        sections: Mapping[str, Iterable[ContextItem]],
        *,
        strict_core_memory: bool = True,
        pre_dropped_items: Optional[Iterable[ContextItemSummary]] = None,
        warnings: Optional[Iterable[str]] = None,
    ) -> ContextPack:
        """Apply budget and policy ordering to collected ContextItems."""

        budgeter = ContextBudgeter(total_budget=self.config.total_budget, section_budgets=self.config.section_budgets)
        selected: dict[str, list[ContextItem]] = {}
        canonical_order = [
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
            "model_profile_summary",
            "runtime_profile_summary",
        ]
        for section in canonical_order:
            items = list(sections.get(section, []))
            items, duplicate_drops = _dedupe_items(section, items)
            for duplicate in duplicate_drops:
                budgeter.report.record_dropped(section, duplicate, "duplicate_context")
            if section == "system":
                selected[section] = items
                for item in items:
                    budgeter.report.record_included(section, item)
                continue
            if section == "core_governance" and not self.config.debug_include_core_governance:
                for item in items:
                    budgeter.report.record_dropped(section, item, "core_memory_prompt_injection_disabled")
                selected[section] = []
                continue
            selected[section] = budgeter.select(
                section,
                items,
                droppable=section != "core_governance" or not strict_core_memory,
                drop_reason="core_memory_budget_exceeded_not_truncated" if section == "core_governance" else None,
            )
        for summary in pre_dropped_items or []:
            normalized = _normalize_summary_section(summary)
            budgeter.report.dropped_items.append(normalized)
            budgeter.report.drop_reasons[normalized.id] = normalized.reason or "dropped"
            usage = budgeter.report.per_section.setdefault(normalized.section, ContextBudgetSectionUsage(budget=0))
            usage.dropped_count += 1

        source_refs = _unique_source_refs(item.source_ref for items in selected.values() for item in items)
        pack = ContextPack(
            system=selected["system"],
            markdown_memory=selected["markdown_memory"],
            core_governance=selected["core_governance"],
            project_context=selected["project_context"],
            episodic_recall=selected["episodic_recall"],
            file_memory_preview=selected["file_memory_preview"],
            attachments=selected["attachments"],
            capabilities=selected["capabilities"],
            mcp=selected["mcp"],
            skills=selected["skills"],
            conversation=selected["conversation"],
            runtime_notes=selected["runtime_notes"],
            model_profile_summary=selected["model_profile_summary"],
            runtime_profile_summary=selected["runtime_profile_summary"],
            source_refs=source_refs,
            budget_report=budgeter.report,
            warnings=list(warnings or []),
        )
        pack.final_messages = self.render_messages(pack)
        return pack

    def render_messages(self, pack: ContextPack) -> list[ChatMessage]:
        """Render the audited ContextPack into the only provider-facing message shape."""

        messages: list[ChatMessage] = []
        for section, items in _renderable_sections(pack, debug_core=self.config.debug_include_core_governance):
            for item in items:
                if section == "conversation" and item.metadata.get("message_json"):
                    messages.append(_message_from_conversation_item(item))
                    continue
                messages.append(
                    ChatMessage(
                        role="system",
                        content=[TextPart(text=_render_context_item(section, item))],
                        metadata={
                            "context_section": section,
                            "context_item_id": item.id,
                            "source_type": item.source_ref.source_type,
                            "source_ref": item.source_ref.summary(),
                            **item.metadata,
                        },
                        timestamp=0.0,
                    )
                )
        return messages

    def _collect(self, provider: Optional[Union[Iterable[ContextItem], ContextProvider]], **kwargs: Any) -> list[ContextItem]:
        """Resolve a provider or iterable into ContextItems."""

        if provider is None:
            return []
        value = provider(**kwargs) if callable(provider) else provider
        if value is None:
            return []
        if isinstance(value, ContextItem):
            return [value]
        return list(value)

    def _coerce_system_instructions(self, value: Optional[Union[Iterable[ContextItem], ContextProvider, str]]) -> list[ContextItem]:
        """Convert plain system text into a source-referenced ContextItem."""

        if isinstance(value, str):
            return [
                ContextItem(
                    id="system-instructions",
                    type="system_instruction",
                    title="System instructions",
                    content=value,
                    source_ref=SourceRef(source_type="system", source_id="system"),
                    priority=100,
                )
            ]
        return self._collect(value)

    def _profile_items(self, section: str, item_type: str, profile: Optional[Any]) -> list[ContextItem]:
        """Summarize model/runtime profile inputs without provider secrets."""

        if profile is None:
            return []
        profile_id = (
            _get_attr(profile, "id")
            or _get_attr(profile, "model_id")
            or _get_attr(profile, "runtime_id")
            or _get_attr(profile, "name")
            or section
        )
        return [
            ContextItem(
                id=f"{section}:{profile_id}",
                type=item_type,  # type: ignore[arg-type]
                title=str(profile_id),
                content=_profile_summary(profile),
                source_ref=SourceRef(source_type="runtime", source_id=str(profile_id)),
                priority=90,
            )
        ]

    def _coerce_capabilities(self, value: Optional[Union[Iterable[ContextItem], ContextProvider, Any]], **kwargs: Any) -> list[ContextItem]:
        """Convert capability selections or descriptors into ContextItems."""

        if value is None:
            return []
        if callable(value) or isinstance(value, (list, tuple)):
            return self._collect(value, **kwargs)
        selected = _get_attr(value, "selected") or _get_attr(value, "enabled") or []
        items: list[ContextItem] = []
        for index, capability in enumerate(selected):
            name = str(_get_attr(capability, "name") or _get_attr(capability, "id") or capability)
            items.append(
                ContextItem(
                    id=f"capability:{name}",
                    type="capability",
                    title=name,
                    content=_profile_summary(capability),
                    source_ref=SourceRef(source_type="capability", source_id=name),
                    priority=50 - index,
                )
            )
        return items

    def _recent_turn_items(self, session_state: Optional[Any]) -> list[ContextItem]:
        """Extract recent turns from a session-like object when available."""

        turns = _get_attr(session_state, "recent_turns") if session_state is not None else None
        if not turns:
            return []
        items: list[ContextItem] = []
        for index, turn in enumerate(turns):
            content = str(_get_attr(turn, "content") or _get_attr(turn, "message") or turn)
            items.append(
                ContextItem(
                    id=f"recent-turn:{index}",
                    type="conversation",
                    title=f"Recent turn {index + 1}",
                    content=content,
                    source_ref=SourceRef(source_type="conversation", source_id=str(index)),
                    priority=20 - index,
                )
            )
        return items


def build_context_built_event(pack: ContextPack, *, model_id: Optional[str] = None, runtime_id: Optional[str] = None) -> dict[str, object]:
    """Build a trace event payload for a completed ContextPack."""

    summary = pack.trace_summary()
    return {
        "name": "context_built",
        "attributes": {
            "model_id": model_id,
            "runtime_id": runtime_id,
            "included_count": len(pack.budget_report.included_items),
            "dropped_count": len(pack.budget_report.dropped_items),
        },
        "payload": {
            **summary,
            "model_id": model_id,
            "runtime_id": runtime_id,
        },
    }


def _get_attr(value: Any, name: str) -> Any:
    """Read an attribute or mapping key without depending on concrete profile classes."""

    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _profile_summary(profile: Any) -> str:
    """Create a bounded, secret-avoiding summary for profile-like values."""

    if isinstance(profile, str):
        return profile
    if isinstance(profile, Mapping):
        public = {
            key: val
            for key, val in profile.items()
            if "secret" not in str(key).lower() and "token" not in str(key).lower()
        }
        return ", ".join(f"{key}={val}" for key, val in sorted(public.items()))
    model_dump = getattr(profile, "model_dump", None)
    if callable(model_dump):
        return _profile_summary(model_dump(mode="json"))
    return str(profile)


def _unique_source_refs(refs: Iterable[SourceRef]) -> List[SourceRef]:
    """Deduplicate source references while preserving first-seen order."""

    seen: set[tuple[object, ...]] = set()
    unique: list[SourceRef] = []
    for ref in refs:
        key = (ref.source_type, ref.source_id, ref.path, ref.line_start, ref.line_end, ref.page, ref.heading)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique


def _section_for_context_item(item: ContextItem) -> str:
    provider = str(item.metadata.get("context_provider") or "")
    if item.type == "mcp" or provider == "mcp" or str(item.id).startswith("mcp:"):
        return "mcp"
    if item.type == "skill" or provider == "skill" or str(item.id).startswith("skill:"):
        return "skills"
    if item.type == "markdown_memory":
        return "markdown_memory"
    if item.type == "attachment_preview":
        return "attachments"
    if item.type == "episodic_memory":
        return "episodic_recall"
    if item.type == "file_memory_preview":
        return "file_memory_preview"
    if item.type == "core_governance" or item.type == "core_memory":
        return "core_governance"
    if item.type == "capability":
        return "capabilities"
    return "project_context"


def _normalize_summary_section(summary: ContextItemSummary) -> ContextItemSummary:
    section = SECTION_ALIASES.get(summary.section, summary.section)
    if section == summary.section:
        return summary
    return summary.model_copy(update={"section": section})


def _renderable_sections(pack: ContextPack, *, debug_core: bool) -> list[tuple[str, list[ContextItem]]]:
    sections = [
        ("system", pack.system),
        ("markdown_memory", pack.markdown_memory),
        ("project_context", pack.project_context),
        ("episodic_recall", pack.episodic_recall),
        ("file_memory_preview", pack.file_memory_preview),
        ("attachments", pack.attachments),
        ("capabilities", pack.capabilities),
        ("mcp", pack.mcp),
        ("skills", pack.skills),
        ("runtime_notes", pack.runtime_notes),
        ("conversation", pack.conversation),
    ]
    if debug_core:
        sections.insert(2, ("core_governance", pack.core_governance))
    return sections


def _render_context_item(section: str, item: ContextItem) -> str:
    if section == "system":
        return item.content
    return f"[Context: {section} | {item.title}]\n{item.content}"


def _normalize_section_budgets(section_budgets: dict[str, int]) -> dict[str, int]:
    normalized = dict(DEFAULT_SECTION_BUDGETS)
    normalized.update({section: int(budget) for section, budget in section_budgets.items()})
    for old, new in SECTION_ALIASES.items():
        if old in section_budgets and new not in section_budgets:
            normalized[new] = int(section_budgets[old])
    return normalized


def _dedupe_items(section: str, items: list[ContextItem]) -> tuple[list[ContextItem], list[ContextItem]]:
    selected: list[ContextItem] = []
    dropped: list[ContextItem] = []
    seen: set[tuple[object, ...]] = set()
    for item in items:
        key = (
            section,
            item.source_ref.source_type,
            item.source_ref.source_id,
            item.source_ref.path,
            item.source_ref.metadata.get("content_hash"),
            item.content,
        )
        if key in seen:
            dropped.append(item)
            continue
        seen.add(key)
        selected.append(item)
    return selected, dropped


def _message_from_conversation_item(item: ContextItem) -> ChatMessage:
    payload = item.metadata.get("message_json")
    if isinstance(payload, dict):
        try:
            message = ChatMessage.model_validate(payload)
            metadata = dict(message.metadata or {})
            metadata.update(
                {
                    "context_section": "conversation",
                    "context_item_id": item.id,
                    "source_type": item.source_ref.source_type,
                    "source_ref": item.source_ref.summary(),
                }
            )
            message.metadata = metadata
            return message
        except Exception:
            pass
    return ChatMessage(
        role="user",
        content=[TextPart(text=item.content)],
        metadata={
            "context_section": "conversation",
            "context_item_id": item.id,
            "source_type": item.source_ref.source_type,
            "source_ref": item.source_ref.summary(),
            **item.metadata,
        },
        timestamp=0.0,
    )
