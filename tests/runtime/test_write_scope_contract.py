from __future__ import annotations

from pp_agent.runtime.scope_contract import (
    WriteScope,
    WriteScopeCheckResult,
    check_path_against_write_scope,
    check_structured_changes_against_write_scope,
    write_scope_check_to_dict,
    write_scope_from_dict,
    write_scope_to_dict,
)


def test_write_scope_serializes_to_dict() -> None:
    payload = write_scope_to_dict(WriteScope(allowed_paths=["src/**"], disallowed_paths=[".env"], allow_delete=False, max_files_changed=2, risk_level="medium", source="task_scope"))

    assert payload == {
        "allowed_paths": ["src/**"],
        "disallowed_paths": [".env"],
        "allow_delete": False,
        "max_files_changed": 2,
        "risk_level": "medium",
        "source": "task_scope",
    }


def test_write_scope_from_dict_round_trip() -> None:
    scope = WriteScope(allowed_paths=["src/**"], disallowed_paths=[".env"], max_files_changed=2)

    assert write_scope_from_dict(write_scope_to_dict(scope)) == scope


def test_write_scope_from_none_returns_none() -> None:
    assert write_scope_from_dict(None) is None


def test_check_path_without_scope_skips() -> None:
    result = check_path_against_write_scope(None, "src/a.py")

    assert result.allowed is None
    assert result.warnings == ["Write scope check skipped."]


def test_check_path_allows_allowed_file() -> None:
    result = check_path_against_write_scope(WriteScope(allowed_paths=["src/**"]), "src/a.py")

    assert result.allowed is True
    assert result.matched_rule == "src/**"


def test_check_path_blocks_disallowed_env() -> None:
    result = check_path_against_write_scope(WriteScope(allowed_paths=["src/**"], disallowed_paths=[".env"]), ".env")

    assert result.allowed is False
    assert result.matched_rule == ".env"


def test_check_path_blocks_git() -> None:
    result = check_path_against_write_scope(WriteScope(allowed_paths=[".git/**"], disallowed_paths=[".git/**"]), ".git/config")

    assert result.allowed is False


def test_check_path_blocks_absolute_path() -> None:
    assert check_path_against_write_scope(WriteScope(allowed_paths=["src/**"]), "/tmp/file").allowed is False


def test_check_path_blocks_drive_path() -> None:
    assert check_path_against_write_scope(WriteScope(allowed_paths=["src/**"]), "C:/tmp/file").allowed is False


def test_check_path_blocks_unc_path() -> None:
    assert check_path_against_write_scope(WriteScope(allowed_paths=["src/**"]), "//server/share").allowed is False


def test_check_path_blocks_parent_traversal() -> None:
    assert check_path_against_write_scope(WriteScope(allowed_paths=["src/**"]), "src/../.env").allowed is False


def test_check_path_blocks_delete_when_delete_disabled() -> None:
    result = check_path_against_write_scope(WriteScope(allowed_paths=["src/**"], allow_delete=False), "src/a.py", action="delete")

    assert result.allowed is False
    assert result.reason == "Delete is denied by write scope."


def test_check_path_blocks_when_allowed_paths_empty() -> None:
    result = check_path_against_write_scope(WriteScope(), "src/a.py")

    assert result.allowed is False
    assert result.reason == "No allowed paths are defined by write scope."


def test_check_structured_changes_without_scope_skips() -> None:
    result = check_structured_changes_against_write_scope(None, [{"path": "src/a.py", "change_type": "modified"}])

    assert result.allowed is None
    assert result.checked_paths == ["src/a.py"]


def test_check_structured_changes_allows_allowed_changes() -> None:
    result = check_structured_changes_against_write_scope(WriteScope(allowed_paths=["src/**"]), [{"path": "src/a.py", "change_type": "modified"}])

    assert result.allowed is True


def test_check_structured_changes_blocks_disallowed_change() -> None:
    result = check_structured_changes_against_write_scope(WriteScope(allowed_paths=["src/**"], disallowed_paths=[".env"]), [{"path": ".env", "change_type": "modified"}])

    assert result.allowed is False
    assert result.failed_path == ".env"


def test_check_structured_changes_blocks_delete() -> None:
    result = check_structured_changes_against_write_scope(WriteScope(allowed_paths=["src/**"], allow_delete=False), [{"path": "src/a.py", "change_type": "deleted"}])

    assert result.allowed is False


def test_check_structured_changes_blocks_too_many_files() -> None:
    result = check_structured_changes_against_write_scope(
        WriteScope(allowed_paths=["src/**"], max_files_changed=1),
        [{"path": "src/a.py", "change_type": "modified"}, {"path": "src/b.py", "change_type": "modified"}],
    )

    assert result.allowed is False
    assert result.matched_rule == "max_files_changed"


def test_write_scope_public_models_have_docstrings() -> None:
    assert WriteScope.__doc__
    assert WriteScopeCheckResult.__doc__


def test_write_scope_public_helpers_have_docstrings() -> None:
    assert write_scope_to_dict.__doc__
    assert write_scope_from_dict.__doc__
    assert write_scope_check_to_dict.__doc__
    assert check_path_against_write_scope.__doc__
    assert check_structured_changes_against_write_scope.__doc__
