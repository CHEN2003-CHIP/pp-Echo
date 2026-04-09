from __future__ import annotations

from pathlib import Path
from typing import Any

from pp_agent.tools.metadata import ANALYSIS_HINTS_DEPRECATED_SINCE, ANALYSIS_HINTS_REMOVAL_TARGET, ToolMetadata


REMOVAL_READINESS_CRITERIA = [
    {
        "id": "no_author_legacy_hints",
        "label": "No author-facing legacy analysis_hints remain in runtime metadata.",
        "blocking": True,
    },
    {
        "id": "formal_primary_semantics_only",
        "label": "Primary dynamic-tool semantics come from formal declarations only.",
        "blocking": True,
    },
    {
        "id": "runtime_internal_overrides_private_only",
        "label": "Only private runtime-internal risk overrides may remain, and they do not count as author migration blockers.",
        "blocking": False,
    },
    {
        "id": "formal_examples_and_docs_only",
        "label": "Examples, docs, and AGENTS guidance use formal declarations only for public registrations.",
        "blocking": True,
    },
]


def suggested_replacements_for_hint(key: str) -> list[str]:
    mapping = {
        "requests_network": ["Use requests_network_hint=True where the risk is a declared tool property."],
        "touches_external": ["Use touches_external_hint=True where the risk is a declared tool property."],
        "destructive_hint": ["Move destructive semantics into the tool's permission domain, sensitivity, or runtime-only internal override."],
        "protected_path_hint": ["Protected path behavior should come from policy/path analysis rather than author-facing analysis_hints."],
        "touches_workspace": ["Prefer explicit tool declarations and stable effect analysis; remove author-facing touches_workspace hints."],
    }
    return mapping.get(key, ["Remove the legacy hint and use formal declarations instead."])


def _severity_for(metadata: ToolMetadata) -> str:
    return "warning" if metadata.legacy_hint_origin == "author" else "info"


def _message_for(metadata: ToolMetadata) -> str:
    if metadata.legacy_hint_origin == "author":
        return (
            f"Author-facing analysis_hints remain deprecated since v{ANALYSIS_HINTS_DEPRECATED_SINCE} "
            f"and must be migrated before v{ANALYSIS_HINTS_REMOVAL_TARGET}."
        )
    return "Runtime-internal risk overrides remain for conservative compatibility and do not count as author migration blockers."


def build_legacy_hint_readiness_report(metadata_map: dict[str, ToolMetadata], *, advisory_source_hits: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    author_count = 0
    runtime_internal_count = 0
    for tool_name, metadata in sorted(metadata_map.items()):
        if not metadata.uses_legacy_analysis_hints:
            continue
        hint_keys = sorted(metadata.analysis_hints)
        usage_origin = metadata.legacy_hint_origin
        if usage_origin == "author":
            author_count += 1
        else:
            runtime_internal_count += 1
        items.append(
            {
                "tool_name": tool_name,
                "family": metadata.tool_family,
                "usage_origin": usage_origin,
                "hint_keys": hint_keys,
                "severity": _severity_for(metadata),
                "message": _message_for(metadata),
                "suggested_replacements": [replacement for key in hint_keys for replacement in suggested_replacements_for_hint(key)],
                "counts_toward_removal_blocker": metadata.counts_toward_removal_blocker,
                "declaration_strength": metadata.declaration_strength,
            }
        )

    criteria = []
    for criterion in REMOVAL_READINESS_CRITERIA:
        satisfied = True
        if criterion["id"] == "no_author_legacy_hints":
            satisfied = author_count == 0
        elif criterion["id"] == "formal_primary_semantics_only":
            satisfied = author_count == 0
        elif criterion["id"] == "runtime_internal_overrides_private_only":
            satisfied = True
        elif criterion["id"] == "formal_examples_and_docs_only":
            satisfied = True
        criteria.append({**criterion, "satisfied": satisfied})

    blocking_items = [item["label"] for item in criteria if item["blocking"] and not item["satisfied"]]
    author_blockers = [item for item in items if item["counts_toward_removal_blocker"]]
    runtime_internal_findings = [item for item in items if item["usage_origin"] == "runtime_internal"]
    release_gate_passed = author_count == 0
    return {
        "deprecated_since": ANALYSIS_HINTS_DEPRECATED_SINCE,
        "removal_target": ANALYSIS_HINTS_REMOVAL_TARGET,
        "ready_for_v0_4_removal": release_gate_passed,
        "release_gate_passed": release_gate_passed,
        "release_gate_failures": blocking_items,
        "author_legacy_usage_count": author_count,
        "runtime_internal_override_count": runtime_internal_count,
        "author_blockers": author_blockers,
        "runtime_internal_findings": runtime_internal_findings,
        "items": items,
        "criteria": criteria,
        "blocking_items": blocking_items,
        "advisory_source_hits": advisory_source_hits or [],
    }


def scan_workspace_for_legacy_analysis_hints(workspace: Path) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    candidate_roots = [workspace / ".pp-agent" / "extensions", workspace / ".pi" / "extensions"]
    for root in candidate_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            parts = {part.lower() for part in path.parts}
            if ".git" in parts or "__pycache__" in parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if "analysis_hints" not in line:
                    continue
                hits.append(
                    {
                        "path": str(path),
                        "line": lineno,
                        "content": line.strip(),
                        "message": "Possible legacy analysis_hints usage found in extension source by static scan. Advisory only; readiness is determined from runtime metadata.",
                    }
                )
    return hits


def render_legacy_hint_readiness_text(report: dict[str, Any]) -> str:
    lines = [
        f"Legacy Analysis Hints Readiness (deprecated since v{report['deprecated_since']}, removal target v{report['removal_target']})",
        f"Ready for v0.4.0 removal: {report['ready_for_v0_4_removal']}",
        f"Release gate passed: {report.get('release_gate_passed', report['ready_for_v0_4_removal'])}",
        f"Author-facing legacy usage: {report['author_legacy_usage_count']}",
        f"Runtime-internal overrides: {report['runtime_internal_override_count']}",
        "",
        "Criteria:",
    ]
    for criterion in report["criteria"]:
        lines.append(f"- [{'x' if criterion['satisfied'] else ' '}] {criterion['label']}")
    if report["items"]:
        lines.extend(["", "Runtime metadata findings:"])
        for item in report["items"]:
            lines.append(
                f"- {item['tool_name']} ({item['family']}, origin={item['usage_origin']}): "
                f"hints={', '.join(item['hint_keys'])}; blocker={item['counts_toward_removal_blocker']}"
            )
    if report["advisory_source_hits"]:
        lines.extend(["", "Advisory source hits:"])
        for hit in report["advisory_source_hits"]:
            lines.append(f"- {hit['path']}:{hit['line']} -> {hit['content']}")
    return "\n".join(lines)
