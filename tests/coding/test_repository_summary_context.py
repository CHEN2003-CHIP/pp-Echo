from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from pp_agent.coding import (
    RepositorySummary,
    RepositorySummarySection,
    RepositorySummarySource,
    RepositorySummaryWarning,
    repository_summary_to_context_items,
)


def test_project_instruction_section_becomes_project_context_item() -> None:
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[
            RepositorySummarySection(
                "project_instruction:AGENTS.md",
                "Project instruction: AGENTS.md",
                "project_instruction",
                "Use focused tests.",
                ["document:AGENTS.md"],
            )
        ],
        sources=[RepositorySummarySource("document:AGENTS.md", "project_instruction", path="AGENTS.md", bytes_consumed=18)],
    )

    items = repository_summary_to_context_items(summary)

    assert len(items) == 1
    item = items[0]
    assert item.id == "repository-summary:project_instruction:AGENTS.md"
    assert item.type == "project_context"
    assert item.content == "Use focused tests."
    assert item.source_ref.source_type == "project_context"
    assert item.source_ref.source_id == "document:AGENTS.md"
    assert item.source_ref.path == "AGENTS.md"
    assert item.source_ref.metadata["repository_summary_source_kind"] == "project_instruction"
    assert item.metadata["context_section"] == "project_context"


def test_module_guidance_section_becomes_independent_item() -> None:
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[
            RepositorySummarySection(
                "module_doc:src:pp_agent:coding:MODULE.md",
                "Module guidance: src/pp_agent/coding/MODULE.md",
                "module_doc",
                ["Keep adapters pure.", "Use focused tests."],
                ["document:src:pp_agent:coding:MODULE.md"],
                truncated=True,
            )
        ],
        sources=[
            RepositorySummarySource(
                "document:src:pp_agent:coding:MODULE.md",
                "module_doc",
                path="src/pp_agent/coding/MODULE.md",
                bytes_consumed=42,
                truncated=True,
            )
        ],
    )

    items = repository_summary_to_context_items(summary)

    assert [item.id for item in items] == ["repository-summary:module_doc:src:pp_agent:coding:MODULE.md"]
    assert items[0].content == "- Keep adapters pure.\n- Use focused tests."
    assert items[0].source_ref.source_type == "module_doc"
    assert items[0].source_ref.path == "src/pp_agent/coding/MODULE.md"
    assert items[0].source_ref.metadata["truncated"] is True
    assert items[0].metadata["truncated"] is True


def test_general_repository_metadata_is_excluded() -> None:
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[
            RepositorySummarySection("project_metadata", "Project metadata", "project_context", {"languages": ["Python"]}, ["project-context"]),
            RepositorySummarySection("repository_structure", "Repository structure", "repository_analysis", {"source_roots": ["src"]}, ["repository-analysis"]),
            RepositorySummarySection("test_commands", "Test commands", "test_command", ["python -m pytest tests -q"], ["project-context"]),
        ],
        sources=[
            RepositorySummarySource("project-context", "project_context"),
            RepositorySummarySource("repository-analysis", "repository_analysis"),
        ],
    )

    assert repository_summary_to_context_items(summary) == ()


def test_warnings_are_not_model_facing_content() -> None:
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[
            RepositorySummarySection("project_instruction:AGENTS.md", "Project instruction: AGENTS.md", "project_instruction", "Use focused tests.", ["agents"])
        ],
        sources=[RepositorySummarySource("agents", "project_instruction", path="AGENTS.md")],
        warnings=[RepositorySummaryWarning("decode_failure", "Sensitive warning text should stay trace-only.", source_key="agents")],
    )

    items = repository_summary_to_context_items(summary)
    dumped = json.dumps([item.model_dump(mode="json") for item in items], sort_keys=True)

    assert len(items) == 1
    assert "Sensitive warning text" not in dumped
    assert all(item.title != "Warnings" for item in items)


def test_source_mapping_keeps_json_safe_relative_provenance() -> None:
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[
            RepositorySummarySection("module_doc:src:MODULE.md", "Module guidance: src/MODULE.md", "module_doc", {"policy": ["small steps"]}, ["module"])
        ],
        sources=[RepositorySummarySource("module", "module_doc", path="src\\MODULE.md", symbol="Module", bytes_consumed=12, truncated=True)],
    )

    item = repository_summary_to_context_items(summary)[0]
    payload = item.model_dump(mode="json")

    assert payload["source_ref"]["source_id"] == "module"
    assert payload["source_ref"]["path"] == "src/MODULE.md"
    assert payload["source_ref"]["metadata"] == {
        "repository_summary_source_kind": "module_doc",
        "bytes_consumed": 12,
        "truncated": True,
        "symbol": "Module",
    }
    assert "E:\\" not in json.dumps(payload)
    assert not _contains_type(payload, (Path, set, datetime, UUID))


def test_skipped_source_and_missing_source_do_not_create_items() -> None:
    skipped = RepositorySummary(
        workspace_name="demo",
        sections=[RepositorySummarySection("module_doc:missing", "Module guidance", "module_doc", "missing", ["missing"])],
        sources=[RepositorySummarySource("missing", "module_doc", path="src/MODULE.md", skipped=True, skip_reason="optional_source_missing")],
    )
    no_source = RepositorySummary(
        workspace_name="demo",
        sections=[RepositorySummarySection("project_instruction:none", "Project instruction", "project_instruction", "orphan", [])],
    )

    assert repository_summary_to_context_items(skipped) == ()
    assert repository_summary_to_context_items(no_source) == ()


def test_output_is_deterministic_for_input_order_changes() -> None:
    instruction = RepositorySummarySection("project_instruction:AGENTS.md", "Project instruction: AGENTS.md", "project_instruction", "A", ["agents"])
    module = RepositorySummarySection("module_doc:src:MODULE.md", "Module guidance: src/MODULE.md", "module_doc", "B", ["module"])
    agents = RepositorySummarySource("agents", "project_instruction", path="AGENTS.md")
    module_source = RepositorySummarySource("module", "module_doc", path="src/MODULE.md")
    first = RepositorySummary(workspace_name="demo", sections=[module, instruction], sources=[module_source, agents])
    second = RepositorySummary(workspace_name="demo", sections=[instruction, module], sources=[agents, module_source])

    first_payload = [item.model_dump(mode="json") for item in repository_summary_to_context_items(first)]
    second_payload = [item.model_dump(mode="json") for item in repository_summary_to_context_items(second)]

    assert first_payload == second_payload
    assert [item["id"] for item in first_payload] == [
        "repository-summary:project_instruction:AGENTS.md",
        "repository-summary:module_doc:src:MODULE.md",
    ]


def test_adapter_does_not_read_filesystem_or_call_collectors(monkeypatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("adapter must not read files")

    monkeypatch.setattr(Path, "open", fail)
    monkeypatch.setattr(Path, "read_text", fail)
    monkeypatch.setattr(Path, "read_bytes", fail)
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[RepositorySummarySection("project_instruction:AGENTS.md", "Project instruction: AGENTS.md", "project_instruction", "Use focused tests.", ["agents"])],
        sources=[RepositorySummarySource("agents", "project_instruction", path="AGENTS.md")],
    )

    assert repository_summary_to_context_items(summary)


def test_empty_summary_returns_empty_tuple() -> None:
    assert repository_summary_to_context_items(RepositorySummary(workspace_name="demo")) == ()


def _contains_type(value: object, types: tuple[type[object], ...]) -> bool:
    if isinstance(value, types):
        return True
    if isinstance(value, dict):
        return any(_contains_type(key, types) or _contains_type(item, types) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_type(item, types) for item in value)
    return False
