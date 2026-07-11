from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pp_agent.coding.scoped_activation import (
    ScopedInstructionActivationState,
    concrete_task_scope_targets,
)
from pp_agent.coding.scope import TaskScope
from pp_agent.tools.base import ToolExecutionResult


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def _read_result(path: Path | str, *, is_error: bool = False, **details: object) -> ToolExecutionResult:
    payload = {"path": str(path), **details}
    return ToolExecutionResult(tool_call_id="", tool_name="read_file", content="ok", details=payload, is_error=is_error)


def test_concrete_task_scope_targets_ignore_broad_patterns_and_root() -> None:
    scope = TaskScope(
        task="x",
        allowed_paths=[
            "src/core/a.py",
            "src/**",
            ".",
            "/tmp/file.py",
            "C:/tmp/file.py",
            "tests\\unit\\test_demo.py",
        ],
    )

    assert concrete_task_scope_targets(scope) == ("src/core/a.py", "tests/unit/test_demo.py")


def test_task_scope_seed_activates_single_concrete_target(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src" / "core").mkdir(parents=True)
    (repo / "src" / "AGENTS.md").write_text("src rules", encoding="utf-8")
    (repo / "src" / "core" / "a.py").write_text("print('a')", encoding="utf-8")
    state = ScopedInstructionActivationState(repository_root=repo)

    state.seed_task_scope(TaskScope(task="x", allowed_paths=["src/core/a.py"]))

    active = state.active_instructions()
    assert [item.source_path for item in active] == ["src/AGENTS.md"]
    assert state.seeded_targets == ["src/core/a.py"]


def test_task_scope_seed_dedupes_same_instruction_from_multiple_targets(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src" / "core").mkdir(parents=True)
    (repo / "src" / "core" / "AGENTS.md").write_text("core rules", encoding="utf-8")
    (repo / "src" / "core" / "a.py").write_text("a", encoding="utf-8")
    (repo / "src" / "core" / "b.py").write_text("b", encoding="utf-8")
    state = ScopedInstructionActivationState(repository_root=repo)

    state.seed_task_scope(TaskScope(task="x", allowed_paths=["src/core/a.py", "src/core/b.py"]))

    assert [item.source_path for item in state.active_instructions()] == ["src/core/AGENTS.md"]


def test_task_scope_seed_builds_deterministic_union_for_multiple_scopes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "packages" / "api").mkdir(parents=True)
    (repo / "packages" / "web").mkdir(parents=True)
    (repo / "packages" / "AGENTS.md").write_text("packages", encoding="utf-8")
    (repo / "packages" / "api" / "AGENTS.md").write_text("api", encoding="utf-8")
    (repo / "packages" / "web" / "AGENTS.md").write_text("web", encoding="utf-8")
    (repo / "packages" / "api" / "a.py").write_text("a", encoding="utf-8")
    (repo / "packages" / "web" / "b.py").write_text("b", encoding="utf-8")

    first = ScopedInstructionActivationState(repository_root=repo)
    first.seed_task_scope(TaskScope(task="x", allowed_paths=["packages/api/a.py", "packages/web/b.py"]))
    second = ScopedInstructionActivationState(repository_root=repo)
    second.seed_task_scope(TaskScope(task="x", allowed_paths=["packages/web/b.py", "packages/api/a.py"]))

    assert [item.source_path for item in first.active_instructions()] == [
        "packages/AGENTS.md",
        "packages/api/AGENTS.md",
        "packages/web/AGENTS.md",
    ]
    assert [item.source_path for item in first.active_instructions()] == [item.source_path for item in second.active_instructions()]


def test_root_only_and_broad_task_scope_targets_do_not_activate(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("root", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "AGENTS.md").write_text("src", encoding="utf-8")
    state = ScopedInstructionActivationState(repository_root=repo)

    state.seed_task_scope(TaskScope(task="x", allowed_paths=[".", "src/**"]))

    assert state.active_instructions() == ()
    assert state.seeded_targets == []


def test_successful_read_file_lazily_activates_scoped_instruction(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "AGENTS.md").write_text("src rules", encoding="utf-8")
    target = repo / "src" / "a.py"
    target.write_text("a", encoding="utf-8")
    state = ScopedInstructionActivationState(repository_root=repo)

    assert state.active_instructions() == ()
    state.observe_read_result(tool_name="read_file", result=_read_result(target))

    assert [item.source_path for item in state.active_instructions()] == ["src/AGENTS.md"]
    assert state.observed_read_targets == ["src/a.py"]


def test_failed_denied_outside_or_attachment_reads_do_not_activate(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "AGENTS.md").write_text("src rules", encoding="utf-8")
    target = repo / "src" / "a.py"
    target.write_text("a", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("outside", encoding="utf-8")
    state = ScopedInstructionActivationState(repository_root=repo)

    state.observe_read_result(tool_name="read_file", result=_read_result(target, is_error=True))
    state.observe_read_result(tool_name="read_file", result=_read_result(target, policy_denied=True, is_error=True))
    state.observe_read_result(tool_name="read_file", result=_read_result(outside))
    state.observe_read_result(tool_name="read_file", result=_read_result("attachment.txt", attachment_fallback=True))
    state.observe_read_result(tool_name="list_files", result=_read_result(target))

    assert state.active_instructions() == ()
    assert state.observed_read_targets == []


def test_repeated_successful_read_suppresses_duplicate_claim_in_continuation(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "src").mkdir()
    target = repo / "src" / "a.py"
    target.write_text("a", encoding="utf-8")
    state = ScopedInstructionActivationState(repository_root=repo)
    calls: list[str] = []

    def fake_resolver(*, repository_root: Path, target_path: str):
        calls.append(target_path)
        return SimpleNamespace(instructions=(), warnings=())

    monkeypatch.setattr("pp_agent.coding.scoped_activation.resolve_scoped_instructions", fake_resolver)

    state.begin_continuation()
    state.observe_read_result(tool_name="read_file", result=_read_result(target))
    state.observe_read_result(tool_name="read_file", result=_read_result(target))

    assert calls == ["src/a.py"]


def test_freshness_replaces_stale_version_for_same_source_path(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src").mkdir()
    instruction = repo / "src" / "AGENTS.md"
    instruction.write_text("version a", encoding="utf-8")
    target = repo / "src" / "a.py"
    target.write_text("a", encoding="utf-8")
    state = ScopedInstructionActivationState(repository_root=repo)

    state.observe_read_result(tool_name="read_file", result=_read_result(target))
    old_digest = state.active_instructions()[0].content_digest
    instruction.write_text("version b", encoding="utf-8")
    state.begin_continuation()
    state.observe_read_result(tool_name="read_file", result=_read_result(target))

    active = state.active_instructions()
    assert len(active) == 1
    assert active[0].source_path == "src/AGENTS.md"
    assert active[0].content_digest != old_digest
    assert active[0].content == "version b"


def test_resolver_warnings_are_retained_without_absolute_path_leak(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "AGENTS.md").write_bytes(b"abc\x00def")
    target = repo / "src" / "a.py"
    target.write_text("a", encoding="utf-8")
    state = ScopedInstructionActivationState(repository_root=repo)

    state.observe_read_result(tool_name="read_file", result=_read_result(target))
    payload = state.to_dict()

    assert [warning.code for warning in state.warnings] == ["unsupported_binary"]
    assert str(repo) not in str(payload)
