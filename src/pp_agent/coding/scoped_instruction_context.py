from __future__ import annotations

from pathlib import PurePosixPath
from typing import Iterable

from pp_agent.coding.scoped_activation import ScopedInstructionActivationRecord
from pp_agent.context.item import ContextItem
from pp_agent.context.source_ref import SourceRef


SCOPED_INSTRUCTION_PRIORITY_BASE = 59
SCOPED_INSTRUCTION_PRIORITY_DEPTH_LIMIT = 20
DIGEST_SEMANTICS = "bounded_decoded_canonical_content"


def scoped_instruction_records_to_context_items(records: Iterable[ScopedInstructionActivationRecord]) -> tuple[ContextItem, ...]:
    """Convert active scoped instruction records into project-context items.

    The adapter is intentionally pure: it consumes already-active records and does not resolve
    scoped instructions, inspect task scope, call tools, or read the filesystem.
    """

    items: list[ContextItem] = []
    seen_sources: set[str] = set()
    for record in sorted(records, key=_budget_sort_key):
        instruction = record.instruction
        if instruction.source_path in seen_sources:
            continue
        seen_sources.add(instruction.source_path)
        items.append(
            ContextItem(
                id=f"scoped-instruction:{instruction.source_path}",
                type="project_context",
                title=f"Scoped instruction: {instruction.source_path}",
                content=instruction.content,
                source_ref=SourceRef(
                    source_type="project_context",
                    source_id=instruction.source_identity,
                    path=instruction.source_path,
                    metadata={
                        "scoped_instruction_source_kind": instruction.source_kind,
                        "scope_root": instruction.scope_root,
                        "content_hash": instruction.content_digest,
                        "content_digest": instruction.content_digest,
                        "digest_semantics": DIGEST_SEMANTICS,
                        "bytes_consumed": instruction.bytes_consumed,
                        "truncated": instruction.truncated,
                    },
                ),
                priority=_budget_priority(instruction.scope_root),
                metadata={
                    "context_section": "project_context",
                    "scoped_instruction": True,
                    "scoped_instruction_source_path": instruction.source_path,
                    "scoped_instruction_source_kind": instruction.source_kind,
                    "scope_root": instruction.scope_root,
                    "content_digest": instruction.content_digest,
                    "digest_semantics": DIGEST_SEMANTICS,
                    "bytes_consumed": instruction.bytes_consumed,
                    "truncated": instruction.truncated,
                    "trigger_kind": record.trigger_kind,
                    "trigger_path": record.trigger_path,
                },
            )
        )
    return tuple(items)


def scoped_instruction_context_render_key(item: ContextItem) -> tuple[int, str]:
    """Return the shallow-to-nearest render key for scoped instruction items."""

    return (_scope_depth(str(item.metadata.get("scope_root") or "")), item.id)


def _budget_sort_key(record: ScopedInstructionActivationRecord) -> tuple[int, str]:
    instruction = record.instruction
    return (-_scope_depth(instruction.scope_root), instruction.source_path)


def _budget_priority(scope_root: str) -> int:
    depth = min(_scope_depth(scope_root), SCOPED_INSTRUCTION_PRIORITY_DEPTH_LIMIT)
    return SCOPED_INSTRUCTION_PRIORITY_BASE + depth


def _scope_depth(scope_root: str) -> int:
    if not scope_root:
        return 0
    return len(PurePosixPath(scope_root).parts)
