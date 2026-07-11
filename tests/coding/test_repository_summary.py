from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from uuid import UUID

import pytest

from pp_agent.coding import (
    REPOSITORY_SUMMARY_SCHEMA_VERSION,
    RepositorySummary,
    RepositorySummarySection,
    RepositorySummarySource,
    RepositorySummaryWarning,
    repository_relative_posix_path,
    repository_summary_to_dict,
)


def test_minimal_repository_summary_serializes_to_json() -> None:
    summary = RepositorySummary(workspace_name="demo")

    payload = summary.to_dict()

    assert payload == {
        "schema_version": REPOSITORY_SUMMARY_SCHEMA_VERSION,
        "workspace_name": "demo",
        "project_type": "unknown",
        "sections": [],
        "sources": [],
        "warnings": [],
    }
    assert json.dumps(payload)


def test_repository_summary_output_is_stable_for_different_input_order() -> None:
    first = RepositorySummary(
        workspace_name="demo",
        project_type="Python package",
        sections=[
            RepositorySummarySection("tests", "Tests", "test_commands", ["python -m pytest tests -q"], ["tests"]),
            RepositorySummarySection("modules", "Modules", "module_map", {"tools": ["src/pp_agent/tools"], "runtime": ["src/pp_agent/runtime"]}, ["map"]),
        ],
        sources=[
            RepositorySummarySource("tests", "test_command", path="tests"),
            RepositorySummarySource("map", "project_map", path=".pp-echo\\project-map.json"),
        ],
        warnings=[
            RepositorySummaryWarning("section_truncated", "Module section was truncated", source_key="map"),
            RepositorySummaryWarning("optional_source_missing", "No module doc", severity="skipped"),
        ],
    )
    second = RepositorySummary(
        workspace_name="demo",
        project_type="Python package",
        sections=list(reversed(first.sections)),
        sources=list(reversed(first.sources)),
        warnings=list(reversed(first.warnings)),
    )

    assert first.to_dict() == second.to_dict()


def test_repository_relative_posix_path_normalizes_without_filesystem_access() -> None:
    assert repository_relative_posix_path("src\\pp_agent\\coding") == "src/pp_agent/coding"
    assert repository_relative_posix_path("./tests//coding") == "tests/coding"

    for path in ("/tmp/demo", "C:/Users/demo", "../outside", "src/../outside"):
        with pytest.raises(ValueError):
            repository_relative_posix_path(path)


def test_duplicate_section_keys_are_rejected() -> None:
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[
            RepositorySummarySection("modules", "Modules", "module_map"),
            RepositorySummarySection("modules", "Other", "module_map"),
        ],
    )

    with pytest.raises(ValueError, match="duplicate repository summary section"):
        summary.to_dict()


def test_duplicate_identical_sources_are_deduped_but_conflicts_are_rejected() -> None:
    source = RepositorySummarySource("agents", "project_instruction", path="AGENTS.md", bytes_consumed=12)
    summary = RepositorySummary(workspace_name="demo", sources=[source, source])

    assert summary.to_dict()["sources"] == [source.to_dict()]

    conflicted = RepositorySummary(
        workspace_name="demo",
        sources=[
            source,
            RepositorySummarySource("agents", "project_instruction", path="AGENTS.md", bytes_consumed=13),
        ],
    )

    with pytest.raises(ValueError, match="conflicting repository summary source"):
        conflicted.to_dict()


def test_warning_skip_and_truncation_metadata_are_explicit_strings() -> None:
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[RepositorySummarySection("instructions", "Instructions", "project_instruction", "bounded excerpt", ["agents"], truncated=True)],
        sources=[
            RepositorySummarySource(
                "agents",
                "project_instruction",
                path="AGENTS.md",
                bytes_consumed=16,
                truncated=True,
                skipped=True,
                skip_reason="read_budget_exceeded",
            )
        ],
        warnings=[
            RepositorySummaryWarning(
                "read_budget_exceeded",
                "AGENTS.md exceeded the read budget.",
                severity="skipped",
                source_key="agents",
            )
        ],
    )

    payload = summary.to_dict()

    assert payload["sections"][0]["truncated"] is True  # type: ignore[index]
    assert payload["sources"][0]["truncated"] is True  # type: ignore[index]
    assert payload["sources"][0]["skipped"] is True  # type: ignore[index]
    assert payload["sources"][0]["skip_reason"] == "read_budget_exceeded"  # type: ignore[index]
    assert payload["warnings"][0]["code"] == "read_budget_exceeded"  # type: ignore[index]
    assert payload["warnings"][0]["severity"] == "skipped"  # type: ignore[index]


def test_repository_summary_payload_contains_only_json_friendly_values() -> None:
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[RepositorySummarySection("metadata", "Metadata", "mapping", {"tuple": ("a", "b"), "count": 2})],
    )

    payload = repository_summary_to_dict(summary)

    assert payload["sections"][0]["content"]["tuple"] == ["a", "b"]  # type: ignore[index]
    json.dumps(payload)
    assert not _contains_type(payload, (Path, set, UUID, Enum))


def test_repository_summary_rejects_non_json_friendly_section_content() -> None:
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[RepositorySummarySection("bad", "Bad", "mapping", {"path": Path("src")})],
    )

    with pytest.raises(TypeError, match="not JSON-friendly"):
        summary.to_dict()


def test_repository_summary_does_not_store_raw_document_body_field() -> None:
    payload = RepositorySummary(
        workspace_name="demo",
        sections=[RepositorySummarySection("instructions", "Instructions", "project_instruction", "short bounded summary", ["agents"])],
        sources=[RepositorySummarySource("agents", "project_instruction", path="AGENTS.md")],
    ).to_dict()

    dumped = json.dumps(payload)
    assert "raw" not in dumped.lower()
    assert "document_body" not in dumped
    assert payload["sections"][0]["source_keys"] == ["agents"]  # type: ignore[index]


def test_dangling_section_source_key_is_rejected() -> None:
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[RepositorySummarySection("instructions", "Instructions", "project_instruction", "summary", ["missing"])],
    )

    with pytest.raises(ValueError, match="unknown source key referenced by section: missing"):
        summary.to_dict()


def test_dangling_warning_source_key_is_rejected() -> None:
    summary = RepositorySummary(
        workspace_name="demo",
        warnings=[RepositorySummaryWarning("optional_source_missing", "No module doc", source_key="missing")],
    )

    with pytest.raises(ValueError, match="unknown source key referenced by warning: missing"):
        summary.to_dict()


def test_global_warning_without_source_key_remains_valid() -> None:
    payload = RepositorySummary(
        workspace_name="demo",
        warnings=[RepositorySummaryWarning("warning_limit_reached", "Additional warnings were omitted.")],
    ).to_dict()

    assert payload["warnings"] == [
        {
            "code": "warning_limit_reached",
            "severity": "warning",
            "message": "Additional warnings were omitted.",
        }
    ]


def test_valid_section_and_warning_source_references_serialize() -> None:
    payload = RepositorySummary(
        workspace_name="demo",
        sources=[RepositorySummarySource("agents", "project_instruction", path="AGENTS.md")],
        sections=[RepositorySummarySection("instructions", "Instructions", "project_instruction", "summary", ["agents"])],
        warnings=[RepositorySummaryWarning("section_truncated", "Instructions truncated.", source_key="agents")],
    ).to_dict()

    assert payload["sections"][0]["source_keys"] == ["agents"]  # type: ignore[index]
    assert payload["warnings"][0]["source_key"] == "agents"  # type: ignore[index]


def test_deduplicated_source_reference_remains_valid() -> None:
    source = RepositorySummarySource("agents", "project_instruction", path="AGENTS.md")
    payload = RepositorySummary(
        workspace_name="demo",
        sources=[source, source],
        sections=[RepositorySummarySection("instructions", "Instructions", "project_instruction", "summary", ["agents", "agents"])],
    ).to_dict()

    assert payload["sources"] == [source.to_dict()]
    assert payload["sections"][0]["source_keys"] == ["agents"]  # type: ignore[index]


def test_multiple_missing_section_source_keys_are_reported_in_stable_order() -> None:
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[
            RepositorySummarySection("b", "B", "kind", "summary", ["zeta", "alpha"]),
            RepositorySummarySection("a", "A", "kind", "summary", ["beta"]),
        ],
    )

    with pytest.raises(ValueError, match="unknown source key referenced by section: alpha, beta, zeta"):
        summary.to_dict()


def test_repository_summary_public_models_have_docstrings() -> None:
    assert RepositorySummary.__doc__
    assert RepositorySummarySection.__doc__
    assert RepositorySummarySource.__doc__
    assert RepositorySummaryWarning.__doc__


def _contains_type(value: object, types: tuple[type[object], ...]) -> bool:
    if isinstance(value, types):
        return True
    if isinstance(value, dict):
        return any(_contains_type(key, types) or _contains_type(item, types) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_type(item, types) for item in value)
    return False
