from __future__ import annotations

import json
from typing import Any

from pp_agent.coding.repository_summary import RepositorySummary
from pp_agent.context.item import ContextItem
from pp_agent.context.source_ref import SourceRef


ELIGIBLE_SECTION_KINDS = frozenset({"project_instruction", "module_doc"})
PROJECT_INSTRUCTION_PRIORITY = 60
MODULE_GUIDANCE_PRIORITY = 58


def repository_summary_to_context_items(summary: RepositorySummary) -> tuple[ContextItem, ...]:
    """Convert selected repository-summary guidance into project-context items.

    The adapter is intentionally pure: it consumes an already-built RepositorySummary and does
    not read files, call collectors, invoke tools, or render provider messages.
    """

    payload = summary.to_dict()
    sources_by_key = {str(source["source_key"]): source for source in payload["sources"] if isinstance(source, dict)}
    items: list[ContextItem] = []
    for section in payload["sections"]:
        if not isinstance(section, dict):
            continue
        kind = str(section.get("kind") or "")
        if kind not in ELIGIBLE_SECTION_KINDS:
            continue
        usable_sources = _usable_sources(section, sources_by_key)
        if not usable_sources:
            continue
        primary_source = usable_sources[0]
        content = _render_content(section.get("content"))
        if not content:
            continue
        section_key = str(section["section_key"])
        items.append(
            ContextItem(
                id=f"repository-summary:{section_key}",
                type="project_context",
                title=str(section["title"]),
                content=content,
                source_ref=_source_ref(primary_source),
                priority=_priority(kind),
                metadata={
                    "context_section": "project_context",
                    "repository_summary_section": section_key,
                    "repository_summary_section_kind": kind,
                    "repository_summary_source_ids": [str(source["source_key"]) for source in usable_sources],
                    "truncated": bool(section.get("truncated", False)),
                },
            )
        )
    return tuple(sorted(items, key=lambda item: (item.priority * -1, item.id)))


def _usable_sources(section: dict[str, object], sources_by_key: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    source_keys = section.get("source_keys", [])
    if not isinstance(source_keys, list):
        return []
    sources: list[dict[str, object]] = []
    for key in sorted({str(source_key) for source_key in source_keys}):
        source = sources_by_key.get(key)
        if source is None or bool(source.get("skipped", False)):
            continue
        sources.append(source)
    return sources


def _source_ref(source: dict[str, object]) -> SourceRef:
    metadata = _source_metadata(source)
    return SourceRef(
        source_type=_source_type(str(source["source_kind"])),
        source_id=str(source["source_key"]),
        path=str(source["path"]) if source.get("path") else None,
        metadata=metadata,
    )


def _source_type(source_kind: str) -> str:
    if source_kind == "module_doc":
        return "module_doc"
    if source_kind == "project_map":
        return "project_map"
    return "project_context"


def _priority(section_kind: str) -> int:
    if section_kind == "module_doc":
        return MODULE_GUIDANCE_PRIORITY
    return PROJECT_INSTRUCTION_PRIORITY


def _source_metadata(source: dict[str, object]) -> dict[str, object]:
    metadata: dict[str, object] = {
        "repository_summary_source_kind": str(source["source_kind"]),
        "bytes_consumed": int(source.get("bytes_consumed", 0)),
        "truncated": bool(source.get("truncated", False)),
    }
    symbol = source.get("symbol")
    if symbol:
        metadata["symbol"] = str(symbol)
    return metadata


def _render_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        lines = [f"- {str(item).strip()}" for item in content if str(item).strip()]
        return "\n".join(lines).strip()
    if isinstance(content, dict):
        return json.dumps(_json_safe(content), ensure_ascii=False, sort_keys=True).strip()
    return str(content).strip()


def _json_safe(value: object) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
