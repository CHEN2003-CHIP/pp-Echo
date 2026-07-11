from __future__ import annotations

import json
from pathlib import Path

import pytest

from pp_agent.coding.repository import RepositoryAnalysis
from pp_agent.coding.repository_summary_collector import (
    RepositorySummaryCollectionLimits,
    RepositorySummaryDocument,
    build_repository_summary,
)
from pp_agent.context.project import ProjectContext


def test_repository_summary_collector_aggregates_context_analysis_and_documents(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("Agent rules", encoding="utf-8")
    (repo / ".pp-echo").mkdir()
    (repo / ".pp-echo" / "project-map.json").write_text('{"project":"demo"}', encoding="utf-8")
    (repo / "src" / "demo").mkdir(parents=True)
    (repo / "src" / "demo" / "MODULE.md").write_text("Module guidance", encoding="utf-8")

    summary = build_repository_summary(
        project_context=_project_context(repo),
        repository_analysis=_analysis(repo, module_map={"demo": ["src/demo"]}),
        repository_root=repo,
    )

    payload = summary.to_dict()
    assert payload["workspace_name"] == "repo"
    assert [source["source_key"] for source in payload["sources"]] == [
        "document:.pp-echo:project-map.json",
        "document:AGENTS.md",
        "document:CLAUDE.md",
        "document:PP_ECHO.md",
        "document:src:demo:MODULE.md",
        "project-context",
        "repository-analysis",
    ]
    assert _source(payload, "document:CLAUDE.md")["skip_reason"] == "optional_source_missing"
    assert _source(payload, "document:PP_ECHO.md")["skip_reason"] == "optional_source_missing"
    section_keys = [section["section_key"] for section in payload["sections"]]
    assert "project_metadata" in section_keys
    assert "repository_structure" in section_keys
    assert "project_instruction:AGENTS.md" in section_keys
    assert "project_map:.pp-echo:project-map.json" in section_keys
    assert "module_doc:src:demo:MODULE.md" in section_keys
    assert json.dumps(payload, sort_keys=True)


def test_repository_summary_collector_uses_stable_synthetic_source_keys(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    payload = build_repository_summary(
        project_context=_project_context(repo),
        repository_analysis=_analysis(repo),
        repository_root=repo,
        project_map_paths=(),
        module_doc_paths=(),
        instruction_filenames=(),
    ).to_dict()

    assert payload["sources"] == [
        {
            "source_key": "project-context",
            "source_kind": "project_context",
            "bytes_consumed": 0,
            "truncated": False,
            "skipped": False,
        },
        {
            "source_key": "repository-analysis",
            "source_kind": "repository_analysis",
            "bytes_consumed": 0,
            "truncated": False,
            "skipped": False,
        },
    ]


def test_missing_optional_document_is_recorded_as_skipped_warning(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    payload = build_repository_summary(
        project_context=_project_context(repo),
        repository_analysis=_analysis(repo),
        repository_root=repo,
        project_map_paths=("missing.md",),
        instruction_filenames=(),
    ).to_dict()

    missing_source = _source(payload, "document:missing.md")
    assert missing_source["skipped"] is True
    assert missing_source["skip_reason"] == "optional_source_missing"
    assert _warning_codes(payload) == ["optional_source_missing"]


@pytest.mark.parametrize("bad_path", ["../outside.md", "/tmp/outside.md", "C:/tmp/outside.md", "//server/share/file.md"])
def test_outside_or_ambiguous_paths_are_rejected(tmp_path: Path, bad_path: str) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    payload = build_repository_summary(
        project_context=_project_context(repo),
        repository_analysis=_analysis(repo),
        repository_root=repo,
        extra_documents=[RepositorySummaryDocument(bad_path, "project_instruction")],
        project_map_paths=(),
        instruction_filenames=(),
    ).to_dict()

    assert "outside_root_rejected" in _warning_codes(payload)
    assert any(source["skipped"] is True for source in payload["sources"])


def test_symlink_escape_is_rejected_before_opening_but_internal_symlink_is_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside = outside_dir / "secret.md"
    outside.write_text("outside-secret", encoding="utf-8")
    target = repo / "docs" / "inside.md"
    target.parent.mkdir()
    target.write_text("inside", encoding="utf-8")
    external_link = repo / "external.md"
    internal_link = repo / "internal.md"
    try:
        external_link.symlink_to(outside)
        internal_link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not available")

    opened_paths: list[Path] = []
    original_open = Path.open

    def spy_open(self: Path, *args: object, **kwargs: object) -> object:
        opened_paths.append(self)
        if self == outside or self == external_link:
            raise AssertionError("escaping symlink target was opened")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy_open)
    payload = build_repository_summary(
        project_context=_project_context(repo),
        repository_analysis=_analysis(repo),
        repository_root=repo,
        extra_documents=[
            RepositorySummaryDocument("external.md", "project_instruction"),
            RepositorySummaryDocument("internal.md", "project_instruction"),
        ],
        project_map_paths=(),
        instruction_filenames=(),
    ).to_dict()

    assert _source(payload, "document:external.md")["skip_reason"] == "symlink_escape_rejected"
    assert _source(payload, "document:internal.md")["skipped"] is False
    assert "symlink_escape_rejected" in _warning_codes(payload)
    assert external_link not in opened_paths
    assert outside not in opened_paths
    assert "outside-secret" not in json.dumps(payload)
    assert str(outside) not in json.dumps(payload)


def test_sensitive_sources_are_rejected_before_opening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    secret = repo / ".env"
    secret.write_text("SECRET=do-not-read", encoding="utf-8")

    original_open = Path.open

    def fail_if_sensitive_opened(self: Path, *args: object, **kwargs: object) -> object:
        if self.name == ".env":
            raise AssertionError("sensitive file was opened")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_if_sensitive_opened)

    def fail_if_read_bytes(self: Path) -> bytes:
        raise AssertionError("sensitive file was opened")

    monkeypatch.setattr(Path, "read_bytes", fail_if_read_bytes)
    payload = build_repository_summary(
        project_context=_project_context(repo),
        repository_analysis=_analysis(repo),
        repository_root=repo,
        extra_documents=[
            RepositorySummaryDocument(".env", "project_instruction"),
            RepositorySummaryDocument("keys/private.pem", "project_instruction"),
            RepositorySummaryDocument("docs/token-notes.md", "project_instruction"),
        ],
        project_map_paths=(),
        instruction_filenames=(),
    ).to_dict()

    assert _warning_codes(payload) == ["sensitive_source_rejected", "sensitive_source_rejected", "sensitive_source_rejected"]
    assert "do-not-read" not in json.dumps(payload)


def test_text_decoding_and_file_type_boundaries_are_stable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "bom.md").write_bytes(b"\xef\xbb\xbfhello")
    (repo / "bad.md").write_bytes(b"\xff\xfe\xfa")
    (repo / "binary.md").write_bytes(b"abc\x00def")
    (repo / "unsupported.py").write_text("print('no')", encoding="utf-8")

    payload = build_repository_summary(
        project_context=_project_context(repo),
        repository_analysis=_analysis(repo),
        repository_root=repo,
        extra_documents=[
            RepositorySummaryDocument("bom.md", "project_instruction"),
            RepositorySummaryDocument("bad.md", "project_instruction"),
            RepositorySummaryDocument("binary.md", "project_instruction"),
            RepositorySummaryDocument("unsupported.py", "project_instruction"),
        ],
        project_map_paths=(),
        instruction_filenames=(),
    ).to_dict()

    assert _section(payload, "project_instruction:bom.md")["content"] == "hello"
    assert sorted(_warning_codes(payload)) == ["decode_failure", "unsupported_binary", "unsupported_text_type"]


def test_budgets_record_truncation_and_skips(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.md").write_text("abcdef", encoding="utf-8")
    (repo / "b.md").write_text("ghijkl", encoding="utf-8")
    (repo / "c.md").write_text("mnopqr", encoding="utf-8")

    payload = build_repository_summary(
        project_context=_project_context(repo),
        repository_analysis=_analysis(repo),
        repository_root=repo,
        extra_documents=[
            RepositorySummaryDocument("a.md", "project_instruction"),
            RepositorySummaryDocument("b.md", "project_instruction"),
            RepositorySummaryDocument("c.md", "project_instruction"),
        ],
        project_map_paths=(),
        instruction_filenames=(),
        limits=RepositorySummaryCollectionLimits(per_file_bytes=4, total_bytes=8, max_documents=2, section_bytes=3, max_warnings=20),
    ).to_dict()

    assert _source(payload, "document:a.md")["bytes_consumed"] == 4
    assert _source(payload, "document:a.md")["truncated"] is True
    assert _source(payload, "document:c.md")["skip_reason"] == "document_count_exceeded"
    assert _section(payload, "project_instruction:a.md")["content"] == "abc"
    assert _section(payload, "project_instruction:a.md")["truncated"] is True
    assert "read_budget_exceeded" in _warning_codes(payload)
    assert "section_truncated" in _warning_codes(payload)


def test_warning_limit_is_bounded(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    payload = build_repository_summary(
        project_context=_project_context(repo),
        repository_analysis=_analysis(repo),
        repository_root=repo,
        extra_documents=[
            RepositorySummaryDocument("missing-a.md", "project_instruction"),
            RepositorySummaryDocument("missing-b.md", "project_instruction"),
            RepositorySummaryDocument("missing-c.md", "project_instruction"),
        ],
        project_map_paths=(),
        instruction_filenames=(),
        limits=RepositorySummaryCollectionLimits(max_warnings=2),
    ).to_dict()

    assert len(payload["warnings"]) == 2
    assert payload["warnings"][-1]["code"] == "warning_limit_reached"  # type: ignore[index]


def test_collector_output_is_deterministic_for_candidate_order(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.md").write_text("a", encoding="utf-8")
    (repo / "b.md").write_text("b", encoding="utf-8")

    first = build_repository_summary(
        project_context=_project_context(repo),
        repository_analysis=_analysis(repo),
        repository_root=repo,
        extra_documents=[
            RepositorySummaryDocument("b.md", "project_instruction"),
            RepositorySummaryDocument("a.md", "project_instruction"),
        ],
        project_map_paths=(),
        instruction_filenames=(),
    ).to_dict()
    second = build_repository_summary(
        project_context=_project_context(repo),
        repository_analysis=_analysis(repo),
        repository_root=repo,
        extra_documents=[
            RepositorySummaryDocument("a.md", "project_instruction"),
            RepositorySummaryDocument("b.md", "project_instruction"),
        ],
        project_map_paths=(),
        instruction_filenames=(),
    ).to_dict()

    assert first == second
    assert str(tmp_path) not in json.dumps(first)


def _project_context(repo: Path) -> ProjectContext:
    return ProjectContext(
        workspace_path=str(repo),
        workspace_name=repo.name,
        detected_languages=["Python"],
        detected_frameworks=["pytest"],
        important_paths=["src", "tests"],
        likely_test_commands=["python -m pytest tests -q"],
        manifest_files=["AGENTS.md"],
        warnings=["context-warning"],
    )


def _analysis(repo: Path, *, module_map: dict[str, list[str]] | None = None) -> RepositoryAnalysis:
    return RepositoryAnalysis(
        workspace_path=str(repo),
        workspace_name=repo.name,
        project_type="Python package",
        languages=["Python"],
        frameworks=["pytest"],
        source_roots=["src"],
        test_roots=["tests"],
        doc_roots=["docs"],
        config_files=["pyproject.toml"],
        entry_points=["src"],
        module_map=module_map or {},
        likely_test_commands=["python -m pytest tests -q"],
        warnings=["analysis-warning"],
    )


def _source(payload: dict[str, object], source_key: str) -> dict[str, object]:
    return next(source for source in payload["sources"] if source["source_key"] == source_key)  # type: ignore[index,return-value]


def _section(payload: dict[str, object], section_key: str) -> dict[str, object]:
    return next(section for section in payload["sections"] if section["section_key"] == section_key)  # type: ignore[index,return-value]


def _warning_codes(payload: dict[str, object]) -> list[str]:
    return [str(warning["code"]) for warning in payload["warnings"]]  # type: ignore[index]
