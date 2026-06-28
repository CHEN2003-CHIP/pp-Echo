from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pp_agent.attachments.context import AttachmentContextProvider
from pp_agent.capabilities.router import CapabilitySelection
from pp_agent.context.adapters import build_context_pack_from_messages
from pp_agent.context.budget import ContextItemSummary
from pp_agent.context.item import ContextItem
from pp_agent.context.pack import ContextPack
from pp_agent.context.pipeline import ContextPipeline, ContextPipelineConfig
from pp_agent.context.source_ref import SourceRef
from pp_agent.domain import ChatMessage, TextPart


def context_pipeline_config_from_settings(settings: Any) -> ContextPipelineConfig:
    """Translate Settings.context_pipeline into the runtime-independent pipeline config."""

    context_settings = settings.context_pipeline
    return ContextPipelineConfig(
        use_context_pipeline_messages=_mode_from_settings(context_settings) in {"auto", "on"},
        debug_include_core_governance=bool(context_settings.debug_include_core_governance),
        total_budget=int(context_settings.total_budget),
        section_budgets=dict(context_settings.section_budgets or {}),
    )


def build_runtime_context_pack(
    *,
    state: Any,
    messages: list[ChatMessage],
    settings: Any,
    session_id: str,
    model_profile: Any = None,
    runtime_profile: Any = None,
    capability_selection: CapabilitySelection | None = None,
) -> ContextPack:
    """Small Runtime bridge that builds the audited ContextPack for one provider call."""

    config = context_pipeline_config_from_settings(settings)
    legacy_pack = build_context_pack_from_messages(
        state=state,
        messages=messages,
        model_profile=model_profile,
        runtime_profile=runtime_profile,
        hook_metadata=dict(getattr(state, "memory_context", None) or {}),
        config=config,
        strict_core_memory=False,
    )
    workspace = Path(settings.workspace)
    global_root = Path(settings.global_dir)
    pipeline = ContextPipeline(config)
    pack = pipeline.build(
        user_message=_latest_user_text(messages),
        memory_providers={
            "markdown_memory": legacy_pack.markdown_memory,
            "core_governance": legacy_pack.core_governance or _core_governance_items_from_state(state),
            "episodic_recall": legacy_pack.episodic_recall,
            "file_memory_preview": legacy_pack.file_memory_preview,
        },
        attachment_providers=[*legacy_pack.attachments, *AttachmentContextProvider(workspace, session_id).list_items()],
        capability_selection=[*legacy_pack.capabilities, *legacy_pack.mcp, *legacy_pack.skills, *_capability_items(capability_selection)],
        conversation_items=legacy_pack.conversation,
        project_context_providers=legacy_pack.project_context,
        system_instructions=legacy_pack.system,
        runtime_notes=legacy_pack.runtime_notes,
        workspace=workspace,
        global_root=global_root,
        settings=settings.learning,
        pre_dropped_items=[*legacy_pack.budget_report.dropped_items, *_blocked_capability_summaries(capability_selection)],
        strict_core_memory=False,
    )
    pack.source_refs = _unique_source_refs([*legacy_pack.source_refs, *pack.source_refs])
    pack.final_messages = pipeline.render_messages(pack)
    return pack


def _latest_user_text(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role != "user":
            continue
        return "\n".join(part.text for part in message.content if isinstance(part, TextPart)).strip()
    return ""


def _mode_from_settings(context_settings: Any) -> str:
    mode = str(getattr(context_settings, "context_pipeline_mode", "") or "").strip().lower()
    if mode in {"off", "shadow", "auto", "on"}:
        return mode
    return "on" if bool(getattr(context_settings, "use_context_pipeline_messages", False)) else "shadow"


def _core_governance_items_from_state(state: Any) -> list[ContextItem]:
    memory_context = getattr(state, "memory_context", None) or {}
    snapshot = memory_context.get("core_memory_snapshot") if isinstance(memory_context, dict) else None
    if not isinstance(snapshot, dict):
        return []
    snapshot_hash = str(snapshot.get("snapshot_hash") or snapshot.get("workspace_id") or "core_memory")
    content = json.dumps(_safe_mapping(snapshot), ensure_ascii=False, sort_keys=True)
    return [
        ContextItem(
            id=f"core-governance:{snapshot_hash}",
            type="core_governance",
            title="Core Memory Governance Snapshot",
            content=content,
            source_ref=SourceRef(
                source_type="core_governance",
                source_id=snapshot_hash,
                metadata=_safe_mapping(snapshot),
            ),
            priority=10,
            metadata={"context_section": "core_governance"},
        )
    ]


def _capability_items(selection: CapabilitySelection | None) -> list[ContextItem]:
    if selection is None:
        return []
    items: list[ContextItem] = []
    for index, descriptor in enumerate(selection.selected):
        content = (
            f"id={descriptor.id}; kind={descriptor.kind}; risk={descriptor.risk_level}; "
            f"source={descriptor.source}; description={descriptor.description[:240]}"
        )
        items.append(
            ContextItem(
                id=f"capability:{descriptor.id}",
                type="capability",
                title=descriptor.display_name or descriptor.name,
                content=content,
                source_ref=SourceRef(
                    source_type="capability",
                    source_id=descriptor.id,
                    metadata={
                        "kind": descriptor.kind,
                        "risk_level": descriptor.risk_level,
                        "source": descriptor.source,
                    },
                ),
                priority=60 - index,
                metadata={"context_section": "capabilities", "risk_level": descriptor.risk_level},
            )
        )
    return items


def _blocked_capability_summaries(selection: CapabilitySelection | None) -> list[ContextItemSummary]:
    if selection is None:
        return []
    summaries: list[ContextItemSummary] = []
    for blocked in selection.blocked:
        summaries.append(
            ContextItemSummary(
                id=f"capability:{blocked.capability_id}",
                type="capability",
                title=blocked.capability_id,
                section="capabilities",
                priority=0,
                estimated_chars=0,
                source_ref={"source_type": "capability", "source_id": blocked.capability_id},
                reason="capability_blocked",
            )
        )
    return summaries


def _safe_mapping(value: dict[str, Any]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, item in value.items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in ("token", "secret", "password", "api_key")):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[str(key)] = item
        elif isinstance(item, list):
            safe[str(key)] = [str(entry)[:160] for entry in item[:10]]
        elif isinstance(item, dict):
            safe[str(key)] = _safe_mapping(item)
    return safe


def _unique_source_refs(refs: list[SourceRef]) -> list[SourceRef]:
    seen: set[tuple[object, ...]] = set()
    unique: list[SourceRef] = []
    for ref in refs:
        key = (ref.source_type, ref.source_id, ref.path, ref.line_start, ref.line_end, ref.page, ref.heading)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique
