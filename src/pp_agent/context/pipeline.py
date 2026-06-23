from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Dict, List, Mapping, Optional, Union

from pydantic import BaseModel, Field

from pp_agent.context.budget import ContextBudgetSectionUsage, ContextBudgeter, ContextItemSummary
from pp_agent.context.item import ContextItem
from pp_agent.context.pack import ContextPack
from pp_agent.context.source_ref import SourceRef


ContextProvider = Callable[..., Optional[Union[Iterable[ContextItem], ContextItem]]]


DEFAULT_SECTION_BUDGETS: dict[str, int] = {
    "system_instructions": 4000,
    "model_profile_summary": 1200,
    "runtime_profile_summary": 1200,
    "core_memory_snapshot": 3000,
    "episodic_memory_items": 3000,
    "attachment_previews": 4000,
    "selected_capabilities": 3000,
    "project_context": 5000,
    "recent_turns": 5000,
    "runtime_notes": 1500,
}


class ContextPipelineConfig(BaseModel):
    """Budget configuration for ContextPipeline."""

    total_budget: int = 30900
    section_budgets: Dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_SECTION_BUDGETS))


class ContextPipeline:
    """Builds a ContextPack from runtime, memory, attachment, and governance inputs."""

    def __init__(self, config: Optional[ContextPipelineConfig] = None) -> None:
        self.config = config or ContextPipelineConfig()

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
        project_context_providers: Optional[Union[Iterable[ContextItem], ContextProvider]] = None,
        system_instructions: Optional[Union[Iterable[ContextItem], ContextProvider, str]] = None,
        runtime_notes: Optional[Union[Iterable[ContextItem], ContextProvider]] = None,
        strict_core_memory: bool = True,
        pre_dropped_items: Optional[Iterable[ContextItemSummary]] = None,
    ) -> ContextPack:
        """Assemble a ContextPack without changing AgentRuntime execution semantics."""

        sections: dict[str, list[ContextItem]] = {
            "system_instructions": self._coerce_system_instructions(system_instructions),
            "model_profile_summary": self._profile_items("model_profile_summary", "model_profile", model_profile),
            "runtime_profile_summary": self._profile_items("runtime_profile_summary", "runtime_profile", runtime_profile),
            "core_memory_snapshot": [],
            "episodic_memory_items": [],
            "attachment_previews": self._collect(attachment_providers, user_message=user_message, session_state=session_state),
            "selected_capabilities": self._coerce_capabilities(capability_selection, user_message=user_message),
            "project_context": self._collect(project_context_providers, user_message=user_message, session_state=session_state),
            "recent_turns": self._recent_turn_items(session_state),
            "runtime_notes": self._collect(runtime_notes, user_message=user_message, session_state=session_state),
        }
        if memory_providers:
            sections["core_memory_snapshot"] = self._collect(
                memory_providers.get("core_memory_snapshot") or memory_providers.get("core_memory")
            )
            sections["episodic_memory_items"] = self._collect(
                memory_providers.get("episodic_memory_items") or memory_providers.get("episodic_memory")
            )

        budgeter = ContextBudgeter(total_budget=self.config.total_budget, section_budgets=self.config.section_budgets)
        selected: dict[str, list[ContextItem]] = {}
        for section, items in sections.items():
            selected[section] = budgeter.select(
                section,
                items,
                droppable=section != "core_memory_snapshot" or not strict_core_memory,
                drop_reason="core_memory_budget_exceeded_not_truncated" if section == "core_memory_snapshot" else None,
            )
        for summary in pre_dropped_items or []:
            budgeter.report.dropped_items.append(summary)
            budgeter.report.drop_reasons[summary.id] = summary.reason or "dropped"
            usage = budgeter.report.per_section.setdefault(summary.section, ContextBudgetSectionUsage(budget=0))
            usage.dropped_count += 1

        source_refs = _unique_source_refs(item.source_ref for items in selected.values() for item in items)
        return ContextPack(
            system_instructions=selected["system_instructions"],
            model_profile_summary=selected["model_profile_summary"],
            runtime_profile_summary=selected["runtime_profile_summary"],
            core_memory_snapshot=selected["core_memory_snapshot"],
            episodic_memory_items=selected["episodic_memory_items"],
            attachment_previews=selected["attachment_previews"],
            selected_capabilities=selected["selected_capabilities"],
            project_context=selected["project_context"],
            recent_turns=selected["recent_turns"],
            runtime_notes=selected["runtime_notes"],
            source_refs=source_refs,
            budget_report=budgeter.report,
        )

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
                    source_ref=SourceRef(source_type="conversation", source_id="system"),
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
                source_ref=SourceRef(source_type="conversation", source_id=str(profile_id)),
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
