from __future__ import annotations

from pp_agent.coding import (
    ScopeEnforcementResult,
    TaskScope,
    enforce_path_scope,
    enforce_structured_changes_scope,
    scope_enforcement_to_context_item,
    scope_enforcement_to_details,
)
from pp_agent.observability import scope_enforcement_to_block, scope_enforcement_to_timeline_step, timeline_to_jsonable


def test_enforce_structured_changes_scope_skips_without_scope() -> None:
    result = enforce_structured_changes_scope(None, [{"path": "src/a.py", "change_type": "modified"}])

    assert result.allowed is None
    assert result.warnings == ["Scope enforcement skipped."]
    assert result.checked_paths == ["src/a.py"]


def test_enforce_structured_changes_scope_allows_allowed_changes() -> None:
    scope = TaskScope(task="x", allowed_paths=["src/**"], disallowed_paths=[], risk_level="medium")

    result = enforce_structured_changes_scope(scope, [{"path": "src/a.py", "change_type": "modified"}])

    assert result.allowed is True
    assert result.risk_level == "medium"


def test_enforce_structured_changes_scope_blocks_disallowed_path() -> None:
    scope = TaskScope(task="x", allowed_paths=["src/**"], disallowed_paths=[".env"], risk_level="high")

    result = enforce_structured_changes_scope(scope, [{"path": ".env", "change_type": "modified"}])

    assert result.allowed is False
    assert result.failed_path == ".env"
    assert result.matched_rule == ".env"


def test_enforce_structured_changes_scope_blocks_delete_when_disabled() -> None:
    scope = TaskScope(task="x", allowed_paths=["src/**"], disallowed_paths=[], allow_delete=False)

    result = enforce_structured_changes_scope(scope, [{"path": "src/a.py", "change_type": "deleted"}])

    assert result.allowed is False
    assert result.reason == "Delete is denied by task scope."


def test_enforce_structured_changes_scope_blocks_too_many_files() -> None:
    scope = TaskScope(task="x", allowed_paths=["src/**"], disallowed_paths=[], max_files_changed=1)

    result = enforce_structured_changes_scope(
        scope,
        [{"path": "src/a.py", "change_type": "modified"}, {"path": "src/b.py", "change_type": "modified"}],
    )

    assert result.allowed is False
    assert result.matched_rule == "max_files_changed"


def test_enforce_path_scope_skips_without_scope() -> None:
    result = enforce_path_scope(None, "src/a.py", "edit")

    assert result.allowed is None
    assert result.checked_paths == ["src/a.py"]


def test_enforce_path_scope_allows_allowed_path() -> None:
    scope = TaskScope(task="x", allowed_paths=["src/**"], disallowed_paths=[])

    result = enforce_path_scope(scope, "src/a.py", "edit")

    assert result.allowed is True
    assert result.matched_rule == "src/**"


def test_enforce_path_scope_blocks_env() -> None:
    scope = TaskScope(task="x", allowed_paths=["src/**"], disallowed_paths=[".env"])

    result = enforce_path_scope(scope, ".env", "edit")

    assert result.allowed is False
    assert result.failed_path == ".env"


def test_scope_enforcement_to_context_item() -> None:
    result = enforce_path_scope(TaskScope(task="x", allowed_paths=["src/**"], disallowed_paths=[]), "src/a.py", "edit")

    item = scope_enforcement_to_context_item(result)

    assert item["title"] == "Scope enforcement"
    assert item["metadata"]["scope_enforcement"]["allowed"] is True


def test_scope_enforcement_to_details() -> None:
    result = enforce_path_scope(None, "src/a.py", "edit")

    details = scope_enforcement_to_details(result)

    assert details["allowed"] is None
    assert details["checked_paths"] == ["src/a.py"]


def test_scope_enforcement_to_timeline_step_allowed() -> None:
    result = enforce_path_scope(TaskScope(task="x", allowed_paths=["src/**"], disallowed_paths=[]), "src/a.py", "edit")

    payload = timeline_to_jsonable(scope_enforcement_to_timeline_step(result))

    assert payload["type"] == "scope_enforcement"
    assert payload["status"] == "succeeded"


def test_scope_enforcement_to_timeline_step_blocked() -> None:
    result = enforce_path_scope(TaskScope(task="x", allowed_paths=["src/**"], disallowed_paths=[".env"]), ".env", "edit")

    payload = timeline_to_jsonable(scope_enforcement_to_timeline_step(result))

    assert payload["status"] == "failed"
    assert payload["title"] == "Task scope check failed"


def test_scope_enforcement_to_timeline_step_skipped() -> None:
    result = enforce_path_scope(None, "src/a.py", "edit")

    payload = timeline_to_jsonable(scope_enforcement_to_timeline_step(result))

    assert payload["status"] == "skipped"
    assert payload["title"] == "Task scope check not applied"


def test_scope_enforcement_to_block() -> None:
    result = enforce_path_scope(None, "src/a.py", "edit")

    payload = timeline_to_jsonable(scope_enforcement_to_block(result))

    assert payload["type"] == "scope_enforcement"
    assert payload["details"]["warnings"] == ["Scope enforcement skipped."]


def test_scope_enforcement_public_models_have_docstrings() -> None:
    assert ScopeEnforcementResult.__doc__


def test_scope_enforcement_public_helpers_have_docstrings() -> None:
    assert enforce_structured_changes_scope.__doc__
    assert enforce_path_scope.__doc__
    assert scope_enforcement_to_context_item.__doc__
    assert scope_enforcement_to_details.__doc__
    assert scope_enforcement_to_timeline_step.__doc__
    assert scope_enforcement_to_block.__doc__
