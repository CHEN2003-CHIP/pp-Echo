from __future__ import annotations

import json
from pathlib import Path

import pytest

from pp_agent.coding.repository_summary_collector import RepositorySummaryCollectionLimits
from pp_agent.coding.scoped_instruction import resolve_scoped_instructions


def test_nested_agents_excludes_root_instruction(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("root", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "AGENTS.md").write_text("src rules", encoding="utf-8")
    (repo / "src" / "a.py").write_text("print('a')", encoding="utf-8")

    result = resolve_scoped_instructions(repository_root=repo, target_path="src/a.py")

    assert [item.source_path for item in result.instructions] == ["src/AGENTS.md"]
    assert result.instructions[0].scope_root == "src"
    assert result.instructions[0].source_kind == "AGENTS.md"
    assert result.instructions[0].content == "src rules"


def test_claude_fallback_and_same_directory_precedence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "CLAUDE.md").write_text("claude fallback", encoding="utf-8")
    (repo / "src" / "a.py").write_text("print('a')", encoding="utf-8")

    fallback = resolve_scoped_instructions(repository_root=repo, target_path="src/a.py")

    assert [item.source_path for item in fallback.instructions] == ["src/CLAUDE.md"]
    assert fallback.instructions[0].source_kind == "CLAUDE.md"

    (repo / "src" / "AGENTS.md").write_text("agents canonical", encoding="utf-8")
    precedence = resolve_scoped_instructions(repository_root=repo, target_path="src/a.py")

    assert [item.source_path for item in precedence.instructions] == ["src/AGENTS.md"]
    assert precedence.instructions[0].content == "agents canonical"


def test_cumulative_ancestry_is_shallow_to_nearest_and_root_excluded(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("root", encoding="utf-8")
    (repo / "packages").mkdir()
    (repo / "packages" / "AGENTS.md").write_text("packages", encoding="utf-8")
    (repo / "packages" / "frontend").mkdir()
    (repo / "packages" / "frontend" / "CLAUDE.md").write_text("frontend", encoding="utf-8")
    (repo / "packages" / "frontend" / "src").mkdir()
    (repo / "packages" / "frontend" / "src" / "a.py").write_text("print('a')", encoding="utf-8")

    result = resolve_scoped_instructions(repository_root=repo, target_path=repo / "packages" / "frontend" / "src" / "a.py")

    assert [item.source_path for item in result.instructions] == [
        "packages/AGENTS.md",
        "packages/frontend/CLAUDE.md",
    ]
    assert [item.scope_root for item in result.instructions] == ["packages", "packages/frontend"]


def test_non_existing_file_like_target_uses_parent_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "AGENTS.md").write_text("planned target rules", encoding="utf-8")

    result = resolve_scoped_instructions(repository_root=repo, target_path="src/new_file.py")

    assert [item.source_path for item in result.instructions] == ["src/AGENTS.md"]


def test_target_outside_root_is_rejected_without_absolute_path_leak(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("outside", encoding="utf-8")

    result = resolve_scoped_instructions(repository_root=repo, target_path=outside)
    dumped = json.dumps(result.to_dict(), sort_keys=True)

    assert result.instructions == ()
    assert [warning.code for warning in result.warnings] == ["outside_root_rejected"]
    assert str(outside) not in dumped


def test_target_symlink_escape_is_rejected_before_external_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "AGENTS.md").write_text("outside-secret", encoding="utf-8")
    link = repo / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not available")

    original_open = Path.open

    def fail_external_open(self: Path, *args: object, **kwargs: object) -> object:
        if self == outside / "AGENTS.md":
            raise AssertionError("external instruction was opened")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_external_open)
    result = resolve_scoped_instructions(repository_root=repo, target_path="linked/a.py")
    dumped = json.dumps(result.to_dict(), sort_keys=True)

    assert result.instructions == ()
    assert [warning.code for warning in result.warnings] == ["symlink_escape_rejected"]
    assert "outside-secret" not in dumped
    assert str(outside) not in dumped


def test_instruction_symlink_escape_falls_back_to_valid_claude_without_external_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside-secret", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "CLAUDE.md").write_text("safe fallback", encoding="utf-8")
    (repo / "src" / "a.py").write_text("print('a')", encoding="utf-8")
    link = repo / "src" / "AGENTS.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is not available")

    opened_paths: list[Path] = []
    original_open = Path.open

    def spy_open(self: Path, *args: object, **kwargs: object) -> object:
        opened_paths.append(self)
        if self == outside or self == link:
            raise AssertionError("escaping instruction symlink was opened")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy_open)
    result = resolve_scoped_instructions(repository_root=repo, target_path="src/a.py")
    dumped = json.dumps(result.to_dict(), sort_keys=True)

    assert [item.source_path for item in result.instructions] == ["src/CLAUDE.md"]
    assert "symlink_escape_rejected" in [warning.code for warning in result.warnings]
    assert outside not in opened_paths
    assert link not in opened_paths
    assert "outside-secret" not in dumped
    assert str(outside) not in dumped


def test_binary_empty_and_oversized_instruction_handling(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "binary").mkdir()
    (repo / "binary" / "AGENTS.md").write_bytes(b"abc\x00def")
    (repo / "binary" / "a.py").write_text("print('a')", encoding="utf-8")
    binary = resolve_scoped_instructions(repository_root=repo, target_path="binary/a.py")
    assert [warning.code for warning in binary.warnings] == ["unsupported_binary"]

    (repo / "empty").mkdir()
    (repo / "empty" / "AGENTS.md").write_text("  \n", encoding="utf-8")
    (repo / "empty" / "a.py").write_text("print('a')", encoding="utf-8")
    empty = resolve_scoped_instructions(repository_root=repo, target_path="empty/a.py")
    assert empty.instructions == ()
    assert [warning.code for warning in empty.warnings] == ["empty_instruction"]

    (repo / "large").mkdir()
    (repo / "large" / "AGENTS.md").write_text("abcdef", encoding="utf-8")
    (repo / "large" / "a.py").write_text("print('a')", encoding="utf-8")
    large = resolve_scoped_instructions(
        repository_root=repo,
        target_path="large/a.py",
        limits=RepositorySummaryCollectionLimits(per_file_bytes=3, total_bytes=3),
    )
    assert large.instructions[0].content == "abc"
    assert large.instructions[0].bytes_consumed == 3
    assert large.instructions[0].truncated is True
    assert "read_budget_exceeded" in [warning.code for warning in large.warnings]


def test_identity_digest_json_and_windows_style_normalization_are_stable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    instruction = repo / "src" / "AGENTS.md"
    instruction.write_text("first", encoding="utf-8")
    (repo / "src" / "a.py").write_text("print('a')", encoding="utf-8")

    first = resolve_scoped_instructions(repository_root=repo, target_path="src\\a.py")
    second = resolve_scoped_instructions(repository_root=repo, target_path="src/a.py")
    first_payload = first.to_dict()

    assert first_payload == second.to_dict()
    assert first.instructions[0].source_identity == "src/AGENTS.md"
    assert first.instructions[0].source_path == "src/AGENTS.md"
    assert first.instructions[0].scope_root == "src"
    assert "\\" not in first.instructions[0].source_path
    assert ":" not in first.instructions[0].source_path
    assert str(repo) not in json.dumps(first_payload, sort_keys=True)
    assert json.dumps(first_payload, sort_keys=True)

    previous_digest = first.instructions[0].content_digest
    instruction.write_text("second", encoding="utf-8")
    changed = resolve_scoped_instructions(repository_root=repo, target_path="src/a.py")
    assert changed.instructions[0].content_digest != previous_digest


def test_target_itself_is_not_returned_as_scoped_instruction(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "packages").mkdir()
    (repo / "packages" / "AGENTS.md").write_text("parent", encoding="utf-8")
    (repo / "packages" / "frontend").mkdir()
    target = repo / "packages" / "frontend" / "AGENTS.md"
    target.write_text("target itself", encoding="utf-8")

    result = resolve_scoped_instructions(repository_root=repo, target_path="packages/frontend/AGENTS.md")

    assert [item.source_path for item in result.instructions] == ["packages/AGENTS.md"]
