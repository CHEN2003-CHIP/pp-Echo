from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from pp_agent.coding import ScopedInstruction, ScopedInstructionActivationRecord, scoped_instruction_records_to_context_items


def _record(
    source_path: str,
    content: str,
    *,
    scope_root: str,
    digest: str,
    trigger_kind: str = "task_scope",
    trigger_path: str = "src/a.py",
    source_kind: str = "AGENTS.md",
    truncated: bool = False,
) -> ScopedInstructionActivationRecord:
    return ScopedInstructionActivationRecord(
        instruction=ScopedInstruction(
            source_path=source_path,
            scope_root=scope_root,
            source_kind=source_kind,  # type: ignore[arg-type]
            content=content,
            content_digest=digest,
            bytes_consumed=len(content),
            truncated=truncated,
        ),
        trigger_kind=trigger_kind,
        trigger_path=trigger_path,
    )


def test_scoped_instruction_record_becomes_project_context_item() -> None:
    items = scoped_instruction_records_to_context_items(
        [_record("src/AGENTS.md", "Use local rules.", scope_root="src", digest="d1", trigger_path="src/a.py")]
    )

    assert len(items) == 1
    item = items[0]
    assert item.id == "scoped-instruction:src/AGENTS.md"
    assert item.type == "project_context"
    assert item.title == "Scoped instruction: src/AGENTS.md"
    assert item.content == "Use local rules."
    assert item.priority == 60
    assert item.source_ref.source_type == "project_context"
    assert item.source_ref.source_id == "src/AGENTS.md"
    assert item.source_ref.path == "src/AGENTS.md"
    assert item.source_ref.metadata["scoped_instruction_source_kind"] == "AGENTS.md"
    assert item.source_ref.metadata["scope_root"] == "src"
    assert item.source_ref.metadata["content_hash"] == "d1"
    assert item.source_ref.metadata["digest_semantics"] == "bounded_decoded_canonical_content"
    assert item.metadata["context_section"] == "project_context"
    assert item.metadata["scoped_instruction"] is True
    assert item.metadata["trigger_kind"] == "task_scope"
    assert item.metadata["trigger_path"] == "src/a.py"


def test_scoped_instruction_items_use_nearest_first_budget_order() -> None:
    items = scoped_instruction_records_to_context_items(
        [
            _record("src/AGENTS.md", "shallow", scope_root="src", digest="d1"),
            _record("src/pkg/AGENTS.md", "nearest", scope_root="src/pkg", digest="d2", trigger_path="src/pkg/a.py"),
        ]
    )

    assert [item.id for item in items] == [
        "scoped-instruction:src/pkg/AGENTS.md",
        "scoped-instruction:src/AGENTS.md",
    ]
    assert [item.priority for item in items] == [61, 60]


def test_scoped_instruction_adapter_deduplicates_sources_deterministically() -> None:
    first = _record("src/AGENTS.md", "first", scope_root="src", digest="d1")
    duplicate = _record("src/AGENTS.md", "duplicate", scope_root="src", digest="d1", trigger_path="src/b.py")

    items = scoped_instruction_records_to_context_items([duplicate, first])

    assert [item.id for item in items] == ["scoped-instruction:src/AGENTS.md"]
    assert items[0].content == "duplicate"


def test_scoped_instruction_metadata_is_json_safe_and_relative() -> None:
    items = scoped_instruction_records_to_context_items(
        [
            _record(
                "src/pkg/CLAUDE.md",
                "Use nested fallback.",
                scope_root="src/pkg",
                digest="d2",
                trigger_kind="read_file",
                trigger_path="src/pkg/a.py",
                source_kind="CLAUDE.md",
                truncated=True,
            )
        ]
    )

    payload = items[0].model_dump(mode="json")
    dumped = json.dumps(payload, sort_keys=True)

    assert "E:\\" not in dumped
    assert "C:\\" not in dumped
    assert "Use nested fallback." in dumped
    assert payload["metadata"]["truncated"] is True
    assert payload["source_ref"]["metadata"]["truncated"] is True
    assert not _contains_type(payload, (Path, set, datetime, UUID))


def test_scoped_instruction_adapter_excludes_warnings_and_raw_state() -> None:
    items = scoped_instruction_records_to_context_items(
        [_record("src/AGENTS.md", "content", scope_root="src", digest="d1")]
    )
    dumped = json.dumps([item.model_dump(mode="json") for item in items], sort_keys=True)

    assert "warnings" not in dumped
    assert "active_by_source_path" not in dumped
    assert "ScopedInstructionActivationState" not in dumped


def test_scoped_instruction_adapter_does_not_read_filesystem(monkeypatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("scoped instruction context adapter must not read files")

    monkeypatch.setattr(Path, "open", fail)
    monkeypatch.setattr(Path, "read_text", fail)
    monkeypatch.setattr(Path, "read_bytes", fail)

    assert scoped_instruction_records_to_context_items([_record("src/AGENTS.md", "content", scope_root="src", digest="d1")])


def test_empty_scoped_instruction_records_return_empty_tuple() -> None:
    assert scoped_instruction_records_to_context_items([]) == ()


def _contains_type(value: object, types: tuple[type[object], ...]) -> bool:
    if isinstance(value, types):
        return True
    if isinstance(value, dict):
        return any(_contains_type(key, types) or _contains_type(item, types) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_type(item, types) for item in value)
    return False
