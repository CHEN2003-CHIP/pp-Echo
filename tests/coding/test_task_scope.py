from __future__ import annotations

from pathlib import Path

from pp_agent.coding import (
    ScopeCheckResult,
    TaskScope,
    analyze_repository,
    build_task_plan,
    build_task_scope,
    check_path_in_scope,
    check_structured_changes_in_scope,
    task_scope_to_context_item,
    task_scope_to_write_scope,
)
from pp_agent.context import build_project_context
from pp_agent.observability import task_scope_to_block, task_scope_to_timeline_step, timeline_to_jsonable


def _plan(tmp_path: Path, task: str):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src" / "pp_agent" / "coding").mkdir(parents=True)
    (tmp_path / "tests" / "coding").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    context = build_project_context(tmp_path)
    analysis = analyze_repository(tmp_path, context)
    return build_task_plan(task, context, analysis), analysis, context


def test_build_task_scope_from_docs_plan(tmp_path: Path) -> None:
    plan, analysis, context = _plan(tmp_path, "update README docs")

    scope = build_task_scope(plan, analysis, context)

    assert "docs/**" in scope.allowed_paths
    assert "README.md" in scope.allowed_paths
    assert scope.risk_level == "low"


def test_build_task_scope_from_coding_plan(tmp_path: Path) -> None:
    plan, analysis, context = _plan(tmp_path, "extend coding intelligence planner")

    scope = build_task_scope(plan, analysis, context)

    assert "src/pp_agent/coding/**" in scope.allowed_paths
    assert "tests/coding/**" in scope.allowed_paths
    assert scope.max_files_changed == 8


def test_build_task_scope_from_unknown_plan_is_conservative(tmp_path: Path) -> None:
    plan, analysis, context = _plan(tmp_path, "make it better")

    scope = build_task_scope(plan, analysis, context)

    assert scope.risk_level == "unknown"
    assert scope.max_files_changed == 2
    assert any("unknown" in warning.lower() for warning in scope.warnings)


def test_task_scope_contains_default_disallowed_paths(tmp_path: Path) -> None:
    plan, analysis, context = _plan(tmp_path, "extend coding intelligence planner")

    scope = build_task_scope(plan, analysis, context)

    assert ".env" in scope.disallowed_paths
    assert ".git/**" in scope.disallowed_paths
    assert "*.key" in scope.disallowed_paths


def test_check_path_in_scope_allows_allowed_file(tmp_path: Path) -> None:
    plan, analysis, context = _plan(tmp_path, "extend coding intelligence planner")
    scope = build_task_scope(plan, analysis, context)

    result = check_path_in_scope(scope, "src/pp_agent/coding/planner.py")

    assert result.allowed
    assert result.matched_rule == "src/pp_agent/coding/**"


def test_check_path_in_scope_blocks_env(tmp_path: Path) -> None:
    scope = TaskScope(task="x", allowed_paths=["src/**"], disallowed_paths=[".env"])

    result = check_path_in_scope(scope, ".env")

    assert not result.allowed
    assert result.matched_rule == ".env"


def test_check_path_in_scope_blocks_git(tmp_path: Path) -> None:
    scope = TaskScope(task="x", allowed_paths=[".git/**"], disallowed_paths=[".git/**"])

    result = check_path_in_scope(scope, ".git/config")

    assert not result.allowed


def test_check_path_in_scope_blocks_absolute_path() -> None:
    result = check_path_in_scope(TaskScope(task="x"), "/tmp/file")

    assert not result.allowed


def test_check_path_in_scope_blocks_drive_path() -> None:
    result = check_path_in_scope(TaskScope(task="x"), "C:/tmp/file")

    assert not result.allowed


def test_check_path_in_scope_blocks_unc_path() -> None:
    result = check_path_in_scope(TaskScope(task="x"), "//server/share/file")

    assert not result.allowed


def test_check_path_in_scope_blocks_parent_traversal() -> None:
    result = check_path_in_scope(TaskScope(task="x"), "src/../.env")

    assert not result.allowed


def test_check_path_in_scope_blocks_delete_when_delete_disabled() -> None:
    scope = TaskScope(task="x", allowed_paths=["src/**"], disallowed_paths=[])

    result = check_path_in_scope(scope, "src/a.py", action="delete")

    assert not result.allowed


def test_check_path_in_scope_blocks_network_when_network_disabled() -> None:
    scope = TaskScope(task="x", allowed_paths=["src/**"], disallowed_paths=[])

    result = check_path_in_scope(scope, "src/a.py", action="network")

    assert not result.allowed


def test_check_structured_changes_in_scope_allows_allowed_changes(tmp_path: Path) -> None:
    plan, analysis, context = _plan(tmp_path, "extend coding intelligence planner")
    scope = build_task_scope(plan, analysis, context)

    result = check_structured_changes_in_scope(scope, [{"path": "src/pp_agent/coding/scope.py", "change_type": "modified"}])

    assert result.allowed


def test_check_structured_changes_in_scope_blocks_disallowed_change(tmp_path: Path) -> None:
    plan, analysis, context = _plan(tmp_path, "extend coding intelligence planner")
    scope = build_task_scope(plan, analysis, context)

    result = check_structured_changes_in_scope(scope, [{"path": ".env", "change_type": "modified"}])

    assert not result.allowed


def test_check_structured_changes_in_scope_blocks_delete(tmp_path: Path) -> None:
    plan, analysis, context = _plan(tmp_path, "extend coding intelligence planner")
    scope = build_task_scope(plan, analysis, context)

    result = check_structured_changes_in_scope(scope, [{"path": "src/pp_agent/coding/scope.py", "change_type": "deleted"}])

    assert not result.allowed


def test_check_structured_changes_in_scope_blocks_too_many_files() -> None:
    scope = TaskScope(task="x", allowed_paths=["src/**"], disallowed_paths=[], max_files_changed=1)

    result = check_structured_changes_in_scope(
        scope,
        [{"path": "src/a.py", "change_type": "modified"}, {"path": "src/b.py", "change_type": "modified"}],
    )

    assert not result.allowed
    assert result.matched_rule == "max_files_changed"


def test_task_scope_to_context_item(tmp_path: Path) -> None:
    plan, analysis, context = _plan(tmp_path, "extend coding intelligence planner")
    scope = build_task_scope(plan, analysis, context)

    item = task_scope_to_context_item(scope)

    assert item.title == "Task scope"
    assert item.metadata["task_scope"]["risk_level"] == "medium"  # type: ignore[index]


def test_task_scope_to_write_scope(tmp_path: Path) -> None:
    plan, analysis, context = _plan(tmp_path, "extend coding intelligence planner")
    scope = build_task_scope(plan, analysis, context)

    write_scope = task_scope_to_write_scope(scope)

    assert write_scope.allowed_paths == scope.allowed_paths
    assert write_scope.disallowed_paths == scope.disallowed_paths
    assert write_scope.allow_delete == scope.allow_delete
    assert write_scope.max_files_changed == scope.max_files_changed
    assert write_scope.risk_level == scope.risk_level
    assert write_scope.source == "task_scope"


def test_task_scope_to_timeline_step(tmp_path: Path) -> None:
    plan, analysis, context = _plan(tmp_path, "extend coding intelligence planner")
    scope = build_task_scope(plan, analysis, context)

    payload = timeline_to_jsonable(task_scope_to_timeline_step(scope))

    assert payload["type"] == "task_scope"
    assert payload["title"] == "Generated task scope"


def test_task_scope_to_timeline_block(tmp_path: Path) -> None:
    plan, analysis, context = _plan(tmp_path, "extend coding intelligence planner")
    scope = build_task_scope(plan, analysis, context)

    payload = timeline_to_jsonable(task_scope_to_block(scope))

    assert payload["type"] == "task_scope"
    assert payload["details"]["allow_delete"] is False


def test_task_scope_public_models_have_docstrings() -> None:
    assert TaskScope.__doc__
    assert ScopeCheckResult.__doc__


def test_task_scope_public_helpers_have_docstrings() -> None:
    assert build_task_scope.__doc__
    assert check_path_in_scope.__doc__
    assert check_structured_changes_in_scope.__doc__
    assert task_scope_to_context_item.__doc__
    assert task_scope_to_write_scope.__doc__
    assert task_scope_to_timeline_step.__doc__
    assert task_scope_to_block.__doc__
