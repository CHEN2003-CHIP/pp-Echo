from pathlib import Path

import pytest

from pp_agent.domain import ToolCall
from storage.settings import ToolPolicyConfig
from tools.pending_actions import PendingActionStore
from tools.registry import ToolRegistry


def test_staged_edit_flow(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged_write = registry.execute("write_file", {"path": "notes.txt", "content": "alpha\nbeta"})
    token = staged_write.details["token"]
    assert (tmp_path / "notes.txt").exists() is False

    preview = registry.execute("preview_pending_action", {"token": token})
    assert "alpha" in preview.content

    registry.execute("approve_pending_action", {"token": token})
    read = registry.execute("read_file", {"path": "notes.txt"})
    assert "alpha" in read.content

    diff = "<<<<<<< SEARCH\nbeta\n=======\ngamma\n>>>>>>> REPLACE"
    staged_edit = registry.execute("edit_file", {"path": "notes.txt", "diff": diff})
    edit_token = staged_edit.details["token"]
    assert "gamma" not in (tmp_path / "notes.txt").read_text(encoding="utf-8")

    registry.execute("approve_pending_action", {"token": edit_token})
    search = registry.execute("search_text", {"query": "gamma"})
    assert "notes.txt" in search.content


def test_write_file_requires_explicit_overwrite(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    registry.execute("write_file", {"path": "notes.txt", "content": "alpha", "apply": True})

    with pytest.raises(ValueError):
        registry.execute("write_file", {"path": "notes.txt", "content": "beta", "apply": True})

    overwrite = registry.execute("write_file", {"path": "notes.txt", "content": "beta", "overwrite": True, "apply": True})
    assert overwrite.details["diff"]


def test_pending_edit_conflict_is_detected(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    registry.execute("write_file", {"path": "notes.txt", "content": "alpha", "apply": True})
    staged = registry.execute("edit_file", {"path": "notes.txt", "old_text": "alpha", "new_text": "beta"})
    token = staged.details["token"]
    (tmp_path / "notes.txt").write_text("changed elsewhere", encoding="utf-8")

    with pytest.raises(ValueError):
        registry.execute("approve_pending_action", {"token": token})


def test_staged_shell_and_reject_flow(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("run_shell", {"command": "Write-Output hello"})
    token = staged.details["token"]

    pending = registry.execute("list_pending_actions", {})
    assert token in pending.content

    preview = registry.execute("preview_pending_action", {"token": token})
    assert "Write-Output hello" in preview.content

    rejected = registry.execute("reject_pending_action", {"token": token})
    assert token in rejected.content


def test_preview_pending_planner_approval(tmp_path: Path) -> None:
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    staged = store.stage(
        action_type="planner_approval",
        details={
            "session_id": "session-1",
            "summary": ["Stage or execute write_file [write_file]", "Apply approved action via approve_pending_action [approve_pending_action]"],
        },
    )
    registry = ToolRegistry(tmp_path)

    preview = registry.execute("preview_pending_action", {"token": staged["token"]})

    assert "write_file" in preview.content
    assert "approve_pending_action" in preview.content


def test_repo_aware_tools_on_non_git_repo(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    (tmp_path / "main.py").write_text("print('hello')\n", encoding="utf-8")

    grep = registry.execute("grep_code", {"query": "hello"})
    status = registry.execute("git_status", {})
    diff = registry.execute("git_diff_worktree", {})

    assert "main.py" in grep.content
    assert diff.content
    assert status.content


def test_workspace_boundary_is_enforced(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("hello", encoding="utf-8")

    with pytest.raises(PermissionError):
        registry.execute("read_file", {"path": str(outside)})


def test_confirmation_policy_is_applied(tmp_path: Path) -> None:
    policy = ToolPolicyConfig(confirm_write_file=False, confirm_edit_file=True, confirm_run_shell=True)
    registry = ToolRegistry(tmp_path, policy=policy)

    assert registry.get_spec("write_file").requires_confirmation is False
    assert registry.get_spec("edit_file").requires_confirmation is True
    assert registry.get_spec("approve_pending_action").requires_confirmation is True


def test_registry_read_only_apis_do_not_materialize_tools(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    calls = 0
    original_factory = registry._registrations["read_file"].tool_factory

    def tracking_factory():
        nonlocal calls
        calls += 1
        return original_factory()

    registry._registrations["read_file"].tool_factory = tracking_factory

    expected_order = [
        "read_file",
        "write_file",
        "edit_file",
        "preview_pending_action",
        "approve_pending_action",
        "reject_pending_action",
        "list_pending_actions",
        "list_files",
        "search_text",
        "grep_code",
        "git_status",
        "git_diff_worktree",
        "run_shell",
    ]

    assert registry._instances == {}
    assert registry.get_spec("read_file").name == "read_file"
    assert list(registry.metadata()) == expected_order
    assert [item["function"]["name"] for item in registry.openapi_specs()] == expected_order
    assert calls == 0
    assert registry._instances == {}


def test_registry_materializes_tools_on_execute_and_reuses_cached_instance(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    calls = 0
    original_factory = registry._registrations["read_file"].tool_factory

    def tracking_factory():
        nonlocal calls
        calls += 1
        return original_factory()

    registry._registrations["read_file"].tool_factory = tracking_factory

    first = registry.execute("read_file", {"path": "notes.txt"})
    second = registry.execute("read_file", {"path": "notes.txt"})

    assert first.content == "hello"
    assert second.content == "hello"
    assert calls == 1
    assert "read_file" in registry._instances


def test_registry_does_not_cache_failed_tool_materialization(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    calls = 0

    def failing_factory():
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    registry._registrations["read_file"].tool_factory = failing_factory

    with pytest.raises(RuntimeError, match="boom"):
        registry.execute("read_file", {"path": "notes.txt"})

    with pytest.raises(RuntimeError, match="boom"):
        registry.execute("read_file", {"path": "notes.txt"})

    assert calls == 2
    assert "read_file" not in registry._instances


def test_unregistered_tool_behavior_matches_current_errors(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    call = ToolCall(id="call-1", name="missing_tool", arguments={})

    with pytest.raises(KeyError):
        registry.get_spec("missing_tool")

    with pytest.raises(KeyError):
        registry.execute("missing_tool", {})

    with pytest.raises(KeyError):
        registry.error_result(call, "nope")
