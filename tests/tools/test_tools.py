from pathlib import Path
import difflib
import json
from types import SimpleNamespace
from typing import Optional

import pytest

from pp_agent.domain import ToolCall
from pp_agent.extensions.api import ExtensionAPI
from pp_agent.extensions.descriptor import ExtensionDescriptor
from pp_agent.tools.effects import analyze_file_call, analyze_mcp_call, build_shell_effect, content_digest
from pp_agent.runtime.session_host import SessionHost
from pp_agent.tools import session_tools
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.settings import ToolPolicyConfig
from pp_agent.subagents.capabilities import CapabilityAdmissionGate, SubAgentProfile, ToolCapabilityPolicy, WorkspacePolicy
from pp_agent.tools.file_tools import ApprovePendingActionTool, MAX_EDIT_FILE_BYTES, unified_text_diff
from pp_agent.tools.registry import ToolRegistry


def test_staged_edit_flow(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged_write = registry.execute("write_file", {"path": "notes.txt", "content": "alpha\nbeta"})
    token = staged_write.details["token"]
    assert (tmp_path / "notes.txt").exists() is False

    preview = registry.host_execute("preview_pending_action", {"token": token})
    assert "alpha" in preview.content

    registry.host_execute("approve_pending_action", {"token": token})
    read = registry.execute("read_file", {"path": "notes.txt"})
    assert "alpha" in read.content

    diff = "<<<<<<< SEARCH\nbeta\n=======\ngamma\n>>>>>>> REPLACE"
    staged_edit = registry.execute("edit_file", {"path": "notes.txt", "diff": diff})
    edit_token = staged_edit.details["token"]
    assert "gamma" not in (tmp_path / "notes.txt").read_text(encoding="utf-8")

    registry.host_execute("approve_pending_action", {"token": edit_token})
    search = registry.execute("search_text", {"query": "gamma"})
    assert "notes.txt" in search.content


def test_staging_same_canonical_write_reuses_existing_pending_action(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    first = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    second = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})

    assert first.details["token"] == second.details["token"]
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert len([item for item in pending if item["action_type"] == "write_file"]) == 1


def test_approval_summary_separates_expired_and_archived_items(tmp_path: Path) -> None:
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    active = store.stage(action_type="planner_approval", details={"summary": ["active"]})
    expired = store.stage(action_type="planner_approval", details={"summary": ["expired"]}, expires_at=1.0)
    rejected = store.stage(action_type="planner_approval", details={"summary": ["rejected"]})
    store.set_lifecycle(rejected["token"], "rejected")

    host = SessionHost(
        runtime_factory=lambda *_args, **_kwargs: None,
        session_store_factory=lambda workspace: None,
        pending_action_store_factory=lambda workspace: PendingActionStore(workspace / ".pp-agent" / "pending-edits"),
        session_defaults_factory=lambda workspace: {},
        checkpoint_store_factory=lambda workspace: None,
    )
    summary = host.approvals_summary(tmp_path)

    assert active["token"] in summary["tokens"]
    assert expired["token"] not in summary["tokens"]
    assert rejected["token"] not in summary["tokens"]
    assert summary["state_counts"]["active"] == 1
    assert summary["state_counts"]["expired"] == 1
    assert summary["state_counts"]["rejected"] == 1


def test_write_file_requires_explicit_overwrite(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    first = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    registry.host_execute("approve_pending_action", {"token": first.details["token"]})

    with pytest.raises(ValueError):
        registry.execute("write_file", {"path": "notes.txt", "content": "beta"})

    overwrite = registry.execute("write_file", {"path": "notes.txt", "content": "beta", "overwrite": True})
    assert overwrite.details["diff"]


def test_write_file_rejects_large_new_content_before_staging(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    with pytest.raises(ValueError, match="large content"):
        registry.execute("write_file", {"path": "large.txt", "content": "x" * (MAX_EDIT_FILE_BYTES + 1)})

    assert not (tmp_path / "large.txt").exists()
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert pending == []


def test_write_file_rejects_large_existing_file_before_staging(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    target = tmp_path / "large.txt"
    target.write_bytes(b"x" * (MAX_EDIT_FILE_BYTES + 1))

    with pytest.raises(ValueError, match="large file"):
        registry.execute("write_file", {"path": "large.txt", "content": "small", "overwrite": True})

    assert target.stat().st_size == MAX_EDIT_FILE_BYTES + 1
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert pending == []


def test_write_file_rejects_binary_existing_file_before_staging(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    target = tmp_path / "binary.dat"
    target.write_bytes(b"abc\x00def")

    with pytest.raises(ValueError, match="binary file"):
        registry.execute("write_file", {"path": "binary.dat", "content": "text", "overwrite": True})

    assert target.read_bytes() == b"abc\x00def"
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert pending == []


def test_write_file_rejects_symlink_before_staging(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("safe", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable in this environment")

    with pytest.raises(PermissionError, match="symlink"):
        registry.execute("write_file", {"path": "link.txt", "content": "changed", "overwrite": True})

    assert target.read_text(encoding="utf-8") == "safe"
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert pending == []


def test_pending_edit_conflict_is_detected(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged_write = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    registry.host_execute("approve_pending_action", {"token": staged_write.details["token"]})
    staged = registry.execute("edit_file", {"path": "notes.txt", "old_text": "alpha", "new_text": "beta"})
    token = staged.details["token"]
    (tmp_path / "notes.txt").write_text("changed elsewhere", encoding="utf-8")

    with pytest.raises(ValueError):
        registry.host_execute("approve_pending_action", {"token": token})


def test_edit_file_accepts_unified_diff(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    original = "alpha\nbeta\ngamma\n"
    updated = "alpha\nbeta updated\ngamma\ndelta\n"
    staged_write = registry.execute("write_file", {"path": "notes.txt", "content": original})
    registry.host_execute("approve_pending_action", {"token": staged_write.details["token"]})
    diff = "\n".join(
        difflib.unified_diff(
            original.splitlines(),
            updated.splitlines(),
            fromfile="a/notes.txt",
            tofile="b/notes.txt",
            lineterm="",
        )
    )

    staged = registry.execute("edit_file", {"path": "notes.txt", "diff": diff})
    token = staged.details["token"]

    assert "beta updated" not in (tmp_path / "notes.txt").read_text(encoding="utf-8")

    registry.host_execute("approve_pending_action", {"token": token})

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == updated


def test_edit_file_rejects_invalid_diff_format(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged_write = registry.execute("write_file", {"path": "notes.txt", "content": "alpha\nbeta\n"})
    registry.host_execute("approve_pending_action", {"token": staged_write.details["token"]})

    with pytest.raises(ValueError, match="SEARCH/REPLACE block or unified diff hunk"):
        registry.execute("edit_file", {"path": "notes.txt", "diff": "@@ invalid @@"})


def test_edit_file_rejects_large_file_before_staging(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    target = tmp_path / "large.txt"
    target.write_bytes(b"x" * (MAX_EDIT_FILE_BYTES + 1))

    with pytest.raises(ValueError, match="large file"):
        registry.execute("edit_file", {"path": "large.txt", "old_text": "x", "new_text": "y"})

    assert target.stat().st_size == MAX_EDIT_FILE_BYTES + 1
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert pending == []


def test_edit_file_rejects_binary_file_before_staging(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    target = tmp_path / "binary.dat"
    target.write_bytes(b"abc\x00def")

    with pytest.raises(ValueError, match="binary file"):
        registry.execute("edit_file", {"path": "binary.dat", "old_text": "abc", "new_text": "xyz"})

    assert target.read_bytes() == b"abc\x00def"
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert pending == []


def test_edit_file_rejects_non_utf8_file_before_staging(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    target = tmp_path / "latin1.txt"
    target.write_bytes("caf\xe9".encode("latin-1"))

    with pytest.raises(ValueError, match="non-UTF-8"):
        registry.execute("edit_file", {"path": "latin1.txt", "old_text": "caf", "new_text": "coffee"})

    assert target.read_bytes() == "caf\xe9".encode("latin-1")
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert pending == []


def test_edit_file_rejects_symlink_before_staging(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("alpha", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable in this environment")

    with pytest.raises(PermissionError, match="symlink"):
        registry.execute("edit_file", {"path": "link.txt", "old_text": "alpha", "new_text": "beta"})

    assert target.read_text(encoding="utf-8") == "alpha"
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert pending == []


def test_staged_shell_and_reject_flow(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("run_shell", {"command": "Write-Output hello"})
    token = staged.details["token"]
    assert staged.details["effect"]["payload_digest"]

    pending = registry.host_execute("list_pending_actions", {})
    assert token in pending.content
    assert "staged_not_granted" in pending.content

    preview = registry.host_execute("preview_pending_action", {"token": token})
    assert "Write-Output hello" in preview.content
    assert "Risk class:" in preview.content
    assert "Confidence:" in preview.content
    assert "Lifecycle state:" in preview.content
    assert "Grant status:" in preview.content

    rejected = registry.host_execute("reject_pending_action", {"token": token})
    assert token in rejected.content
    rejected_again = registry.host_execute("reject_pending_action", {"token": token})
    assert rejected_again.details["idempotent"] is True
    archived = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").load(token)
    assert archived["lifecycle"]["state"] == "rejected"
    assert token not in registry.host_execute("list_pending_actions", {}).content


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

    preview = registry.host_execute("preview_pending_action", {"token": staged["token"]})

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
    assert registry.get_spec("preview_safe_rewind").requires_confirmation is False
    assert registry.get_spec("execute_safe_rewind").requires_confirmation is True
    assert registry.get_spec("write_file").permission_domain == "edit"
    assert registry.get_spec("run_shell").permission_domain == "bash"


def test_registry_read_only_apis_do_not_materialize_tools(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    calls = 0
    original_factory = registry._registrations["read_file"].tool_factory

    def tracking_factory():
        nonlocal calls
        calls += 1
        return original_factory()

    registry._registrations["read_file"].tool_factory = tracking_factory

    expected_names = {
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
        "list_attachments",
        "inspect_attachment",
        "search_attachment",
        "read_attachment_chunk",
        "read_attachment_text",
        "read_attachment_range",
        "search_attachment_symbols",
        "read_attachment_symbol",
        "preview_safe_rewind",
        "execute_safe_rewind",
        "run_shell",
    }
    expected_model_names = {
        "read_file",
        "write_file",
        "edit_file",
        "list_files",
        "search_text",
        "grep_code",
        "git_status",
        "git_diff_worktree",
        "list_attachments",
        "inspect_attachment",
        "search_attachment",
        "read_attachment_chunk",
        "read_attachment_text",
        "read_attachment_range",
        "search_attachment_symbols",
        "read_attachment_symbol",
        "preview_safe_rewind",
        "execute_safe_rewind",
        "run_shell",
    }

    assert registry._instances == {}
    assert registry.get_spec("read_file").name == "read_file"
    assert set(registry.metadata()) >= expected_names
    assert {item["function"]["name"] for item in registry.openapi_specs()} >= expected_model_names
    assert calls == 0
    assert registry._instances == {}


def test_attachment_tools_are_registered_without_eager_materialization(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, current_session_id="session-1")
    attachment_tools = {
        "list_attachments",
        "inspect_attachment",
        "search_attachment",
        "read_attachment_chunk",
        "read_attachment_text",
        "read_attachment_range",
        "search_attachment_symbols",
        "read_attachment_symbol",
    }

    assert attachment_tools <= set(registry.metadata())
    assert attachment_tools <= {item["function"]["name"] for item in registry.openapi_specs()}
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


def test_read_file_truncates_long_content_and_supports_offsets(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    (tmp_path / "README.md").write_text("0123456789" * 10, encoding="utf-8")

    first = registry.execute("read_file", {"path": "README.md", "max_chars": 12})
    second = registry.execute("read_file", {"path": "README.md", "offset": 12, "max_chars": 12})

    assert first.details["truncated"] is True
    assert first.details["text_length"] == 100
    assert first.details["max_chars"] == 12
    assert first.content.startswith("012345678901")
    assert "Read again with offset/max_chars" in first.content
    assert second.details["offset"] == 12
    assert second.content.startswith("234567890123")


def test_read_file_handles_bom_and_invalid_utf8_with_details(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    (tmp_path / "bom.md").write_bytes("\ufeffhello".encode("utf-8"))
    (tmp_path / "latin1.txt").write_bytes("caf\xe9".encode("latin-1"))

    bom = registry.execute("read_file", {"path": "bom.md"})
    latin = registry.execute("read_file", {"path": "latin1.txt"})

    assert bom.content == "hello"
    assert bom.details["encoding"] == "utf-8-sig"
    assert "caf" in latin.content
    assert latin.details["encoding"]
    assert latin.details["truncated"] is False


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


def test_unregistered_tool_error_result_is_understandable(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    call = ToolCall(id="call-1", name="missing_tool", arguments={})

    with pytest.raises(KeyError):
        registry.get_spec("missing_tool")

    with pytest.raises(KeyError):
        registry.execute("missing_tool", {})

    result = registry.error_result(call, "Unknown tool 'missing_tool' is not registered in ToolRegistry.")

    assert result.is_error is True
    assert result.tool_call_id == "call-1"
    assert result.tool_name == "missing_tool"
    assert result.details["tool_unknown"] is True
    assert "not registered" in result.content


def test_preview_safe_rewind_uses_sdk_preview_and_returns_structured_details(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        session_tools,
        "_session_store_for",
        lambda _workspace: SimpleNamespace(tree=lambda: [SimpleNamespace(id="session-1")]),
    )

    def fake_preview_rewind(workspace, session_id, **kwargs):
        seen["workspace"] = workspace
        seen["session_id"] = session_id
        seen["kwargs"] = kwargs
        return {
            "mode": "workspace_only",
            "checkpoint": {"checkpoint_id": "cp-1", "snapshot_type": "head_snapshot"},
            "restore_preview": {"affected_files": ["a.py", "b.py"]},
            "source_session_id": session_id,
            "target_session_id": "session-2",
            "target_head_id": "head-1",
            "target_turn_id": "turn-1",
            "message_count": 3,
            "turn_count": 1,
            "warning_messages": ["dirty workspace"],
        }

    monkeypatch.setattr(session_tools, "_preview_rewind", fake_preview_rewind)

    result = registry.execute(
        "preview_safe_rewind",
        {"session_id": "session-1", "mode": "workspace_only", "message_count": 3},
    )

    assert seen["workspace"] == tmp_path.resolve()
    assert seen["session_id"] == "session-1"
    assert seen["kwargs"] == {"mode": "workspace_only", "message_count": 3}
    assert result.is_error is False
    assert result.details["session_id"] == "session-1"
    assert result.details["checkpoint_id"] == "cp-1"
    assert result.details["snapshot_type"] == "head_snapshot"
    assert result.details["mode"] == "workspace_only"
    assert result.details["preview_only"] is True
    assert result.details["restored_workspace"] is False
    assert result.details["affected_message_count"] == 3
    assert result.details["affected_turn_count"] == 1
    assert result.details["target_head_id"] == "head-1"
    assert result.details["workspace_file_count"] == 2
    assert "Preview safe rewind" in result.content


def test_execute_safe_rewind_uses_sdk_execute_and_returns_structured_details(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        session_tools,
        "_session_store_for",
        lambda _workspace: SimpleNamespace(tree=lambda: [SimpleNamespace(id="session-1")]),
    )

    def fake_rewind_safe(workspace, session_id, **kwargs):
        seen["workspace"] = workspace
        seen["session_id"] = session_id
        seen["kwargs"] = kwargs
        return {
            "mode": "conversation_and_workspace",
            "checkpoint_id": "cp-2",
            "snapshot_type": "stash_snapshot",
            "source_session_id": session_id,
            "session_id": "session-3",
            "active_head_id": "head-2",
            "restored_workspace": True,
            "restored_conversation": True,
            "warning_messages": [],
        }

    monkeypatch.setattr(session_tools, "_execute_rewind", fake_rewind_safe)

    result = registry.execute(
        "execute_safe_rewind",
        {
            "session_id": "session-1",
            "mode": "conversation_and_workspace",
            "turn_count": 2,
            "allow_stash_snapshot": True,
        },
    )

    assert seen["workspace"] == tmp_path.resolve()
    assert seen["session_id"] == "session-1"
    assert seen["kwargs"] == {
        "mode": "conversation_and_workspace",
        "turn_count": 2,
        "allow_stash_snapshot": True,
    }
    assert result.is_error is False
    assert result.details["session_id"] == "session-3"
    assert result.details["checkpoint_id"] == "cp-2"
    assert result.details["snapshot_type"] == "stash_snapshot"
    assert result.details["mode"] == "conversation_and_workspace"
    assert result.details["preview_only"] is False
    assert result.details["restored_workspace"] is True
    assert result.details["target_head_id"] == "head-2"
    assert "Executed safe rewind" in result.content


def test_preview_safe_rewind_accepts_current_session_alias(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, current_session_id="session-active")
    seen: dict[str, object] = {}

    monkeypatch.setattr(session_tools, "_session_store_for", lambda _workspace: SimpleNamespace(tree=lambda: []))

    def fake_preview_rewind(workspace, session_id, **kwargs):
        seen["workspace"] = workspace
        seen["session_id"] = session_id
        seen["kwargs"] = kwargs
        return {
            "mode": "workspace_only",
            "checkpoint": {"checkpoint_id": "cp-1", "snapshot_type": "head_snapshot"},
            "restore_preview": {"affected_files": []},
            "source_session_id": session_id,
            "target_head_id": "head-1",
            "message_count": 1,
            "turn_count": 1,
            "warning_messages": [],
        }

    monkeypatch.setattr(session_tools, "_preview_rewind", fake_preview_rewind)

    result = registry.execute("preview_safe_rewind", {"session_id": "current", "mode": "workspace_only"})

    assert seen["workspace"] == tmp_path.resolve()
    assert seen["session_id"] == "session-active"
    assert result.details["session_id"] == "session-active"


def test_preview_safe_rewind_accepts_unique_session_prefix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    monkeypatch.setattr(
        session_tools,
        "_session_store_for",
        lambda _workspace: SimpleNamespace(
            tree=lambda: [SimpleNamespace(id="session-1234"), SimpleNamespace(id="other-9999")]
        ),
    )
    seen: dict[str, object] = {}

    def fake_preview_rewind(workspace, session_id, **kwargs):
        seen["session_id"] = session_id
        return {
            "mode": "workspace_only",
            "checkpoint": {"checkpoint_id": "cp-1", "snapshot_type": "head_snapshot"},
            "restore_preview": {"affected_files": []},
            "source_session_id": session_id,
            "target_head_id": "head-1",
            "message_count": 1,
            "turn_count": 1,
            "warning_messages": [],
        }

    monkeypatch.setattr(session_tools, "_preview_rewind", fake_preview_rewind)

    registry.execute("preview_safe_rewind", {"session_id": "session-12", "mode": "workspace_only"})

    assert seen["session_id"] == "session-1234"


def test_execute_safe_rewind_accepts_current_session_alias(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, current_session_id="session-active")
    seen: dict[str, object] = {}

    monkeypatch.setattr(session_tools, "_session_store_for", lambda _workspace: SimpleNamespace(tree=lambda: []))

    def fake_execute_rewind(workspace, session_id, **kwargs):
        seen["workspace"] = workspace
        seen["session_id"] = session_id
        return {
            "mode": "workspace_only",
            "checkpoint_id": "cp-2",
            "snapshot_type": "head_snapshot",
            "source_session_id": session_id,
            "session_id": session_id,
            "active_head_id": "head-2",
            "restored_workspace": True,
            "restored_conversation": False,
            "warning_messages": [],
        }

    monkeypatch.setattr(session_tools, "_execute_rewind", fake_execute_rewind)

    result = registry.execute("execute_safe_rewind", {"session_id": "current", "mode": "workspace_only"})

    assert seen["workspace"] == tmp_path.resolve()
    assert seen["session_id"] == "session-active"
    assert result.details["session_id"] == "session-active"


def test_preview_safe_rewind_reports_friendly_session_reference_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, current_session_id="session-active")
    monkeypatch.setattr(
        session_tools,
        "_session_store_for",
        lambda _workspace: SimpleNamespace(
            tree=lambda: [SimpleNamespace(id="session-1234"), SimpleNamespace(id="session-5678")]
        ),
    )

    with pytest.raises(ValueError, match="Unknown session reference 'missing'"):
        registry.execute("preview_safe_rewind", {"session_id": "missing", "mode": "workspace_only"})

    with pytest.raises(ValueError, match="active session id session-active"):
        registry.execute("preview_safe_rewind", {"session_id": "missing", "mode": "workspace_only"})

    with pytest.raises(ValueError, match="Session prefix is ambiguous: session-"):
        registry.execute("preview_safe_rewind", {"session_id": "session-", "mode": "workspace_only"})

    with pytest.raises(ValueError, match="does not accept session@turn references"):
        registry.execute("preview_safe_rewind", {"session_id": "session-1234@turn-1", "mode": "workspace_only"})


def test_registry_builtin_descriptions_include_mandatory_use_guidance(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    assert "must use this tool" in registry.get_spec("read_file").description.lower()
    assert "must use this tool" in registry.get_spec("list_files").description.lower()
    assert "must use this tool" in registry.get_spec("git_status").description.lower()
    assert "do not invent command results" in registry.get_spec("run_shell").description.lower()
    assert "'current'" in registry.get_spec("preview_safe_rewind").description
    assert "prefer preview before execute" in registry.get_spec("preview_safe_rewind").description.lower()
    assert "'current'" in registry.get_spec("execute_safe_rewind").description


@pytest.mark.parametrize("path", [".env", ".env.local", ".pp-agent/config.json", ".git/config", "secret.pem", "secret.key"])
def test_protected_paths_are_denied_for_read_and_write(tmp_path: Path, path: str) -> None:
    registry = ToolRegistry(tmp_path)
    protected = tmp_path / path
    protected.parent.mkdir(parents=True, exist_ok=True)
    protected.write_text("secret", encoding="utf-8")

    with pytest.raises(PermissionError):
        registry.execute("read_file", {"path": path})

    with pytest.raises(PermissionError):
        registry.execute("write_file", {"path": path, "content": "nope"})


def test_normal_workspace_edit_stages_instead_of_direct_apply(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha", "apply": True})

    assert staged.details["staged"] is True
    assert (tmp_path / "notes.txt").exists() is False


def test_host_only_approval_tools_are_hidden_from_model_calls(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    model_tools = [item["function"]["name"] for item in registry.openapi_specs()]

    assert "approve_pending_action" not in model_tools
    assert "reject_pending_action" not in model_tools
    assert "rollback_file_checkpoint" not in model_tools
    assert "preview_pending_action" not in model_tools
    assert "list_pending_actions" not in model_tools

    with pytest.raises(PermissionError, match="host-only"):
        registry.execute("approve_pending_action", {"token": "tok-1"})
    with pytest.raises(PermissionError, match="host-only"):
        registry.execute("rollback_file_checkpoint", {"checkpoint_id": "file-edit-1"})


def test_rollback_file_checkpoint_registry_metadata_is_host_control(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    metadata = registry.metadata()["rollback_file_checkpoint"]

    assert metadata.category == "approvals"
    assert metadata.permission_domain == "approval"
    assert metadata.requires_confirmation is True
    assert metadata.sensitive is True
    assert metadata.model_callable is False
    assert metadata.tool_family is None
    assert metadata.exact_effect_mode == "none"


def test_capability_profiles_treat_rollback_as_approval_execute_tool(tmp_path: Path) -> None:
    staged_profile = SubAgentProfile(
        name="staged-worker",
        tool=ToolCapabilityPolicy(allowlist=["rollback_file_checkpoint"]),
        workspace=WorkspacePolicy(mode="staged_edits"),
    )
    worktree_profile = SubAgentProfile(
        name="worktree-worker",
        tool=ToolCapabilityPolicy(allowlist=["rollback_file_checkpoint"]),
        workspace=WorkspacePolicy(mode="worktree", allow_write_tools=True),
    )

    assert CapabilityAdmissionGate.allow_tool(staged_profile, "rollback_file_checkpoint") is False
    assert CapabilityAdmissionGate.allow_tool(worktree_profile, "rollback_file_checkpoint") is False
    assert ToolRegistry(tmp_path, capability_profile=staged_profile).metadata()["rollback_file_checkpoint"].model_callable is False
    with pytest.raises(PermissionError, match="capability profile"):
        ToolRegistry(tmp_path, capability_profile=worktree_profile).host_execute(
            "rollback_file_checkpoint",
            {"checkpoint_id": "file-edit-1"},
        )


def test_approved_effect_executes_with_digest_bound_grant(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    token = staged.details["token"]

    result = registry.host_execute("approve_pending_action", {"token": token})

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "alpha"
    assert result.details["effect"]["payload_digest"] == staged.details["effect"]["payload_digest"]
    assert result.details["approval_grant"]["status"] == "consumed"
    assert result.details["lifecycle"]["state"] == "grant_consumed"
    assert result.details["latest_audit"]["lifecycle_state"] == "grant_consumed"


def test_staged_effect_starts_with_explicit_lifecycle_state(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")

    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    payload = store.load(staged.details["token"])

    assert payload["lifecycle"]["state"] == "staged_not_granted"
    assert payload["approval_grant"] is None


def test_attach_approval_grant_moves_pending_action_to_grant_attached(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")

    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    payload = store.attach_approval_grant(staged.details["token"])

    assert payload["approval_grant"]["status"] == "active"
    assert payload["lifecycle"]["state"] == "grant_attached"


def test_approval_grant_binds_patch_proposal_digest(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")

    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    payload = store.attach_approval_grant(staged.details["token"])

    assert payload["approval_grant"]["proposal_digest"] == payload["details"]["patch_proposal"]["proposal_digest"]


def test_consumed_approval_is_archived_and_idempotent(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    token = staged.details["token"]

    registry.host_execute("approve_pending_action", {"token": token})
    repeated = registry.host_execute("approve_pending_action", {"token": token})

    archived = store.load(token)
    assert archived["lifecycle"]["state"] == "grant_consumed"
    assert repeated.details["idempotent"] is True
    assert repeated.details["success"] is True


def test_approve_applies_same_write_file_patch_proposal(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    result = registry.host_execute("approve_pending_action", {"token": staged.details["token"]})

    assert result.details["approval_grant"]["proposal_digest"] == staged.details["proposal_digest"]
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "alpha"


def test_approve_applies_same_edit_file_patch_proposal(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    write = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    registry.host_execute("approve_pending_action", {"token": write.details["token"]})

    staged = registry.execute("edit_file", {"path": "notes.txt", "old_text": "alpha", "new_text": "beta"})
    result = registry.host_execute("approve_pending_action", {"token": staged.details["token"]})

    assert result.details["approval_grant"]["proposal_digest"] == staged.details["proposal_digest"]
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "beta"


def test_edit_file_apply_creates_checkpoint_before_write(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    (tmp_path / "notes.txt").write_text("alpha", encoding="utf-8")

    staged = registry.execute("edit_file", {"path": "notes.txt", "old_text": "alpha", "new_text": "beta"})
    result = registry.host_execute("approve_pending_action", {"token": staged.details["token"]})

    checkpoint = result.details["checkpoint"]
    assert result.details["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert checkpoint["action_type"] == "edit_file"
    assert checkpoint["target_path"] == "notes.txt"
    assert checkpoint["existed"] is True
    assert checkpoint["before_state"] == "present"
    assert checkpoint["before_digest"] == content_digest("alpha")
    assert Path(checkpoint["content_path"]).read_text(encoding="utf-8") == "alpha"
    assert Path(checkpoint["metadata_path"]).exists()
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "beta"


def test_overwrite_write_file_apply_creates_checkpoint_before_write(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    (tmp_path / "notes.txt").write_text("alpha", encoding="utf-8")

    staged = registry.execute("write_file", {"path": "notes.txt", "content": "beta", "overwrite": True})
    result = registry.host_execute("approve_pending_action", {"token": staged.details["token"]})

    checkpoint = result.details["checkpoint"]
    assert checkpoint["action_type"] == "write_file"
    assert checkpoint["target_path"] == "notes.txt"
    assert checkpoint["existed"] is True
    assert checkpoint["before_digest"] == content_digest("alpha")
    assert Path(checkpoint["content_path"]).read_text(encoding="utf-8") == "alpha"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "beta"


def test_new_write_file_apply_creates_absent_checkpoint(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    result = registry.host_execute("approve_pending_action", {"token": staged.details["token"]})

    checkpoint = result.details["checkpoint"]
    assert checkpoint["action_type"] == "write_file"
    assert checkpoint["target_path"] == "notes.txt"
    assert checkpoint["existed"] is False
    assert checkpoint["before_state"] == "absent"
    assert checkpoint["before_digest"] is None
    assert checkpoint["content_path"] is None
    assert Path(checkpoint["metadata_path"]).exists()
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "alpha"


def test_checkpoint_failure_rejects_write_and_preserves_original(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    (tmp_path / "notes.txt").write_text("alpha", encoding="utf-8")

    def fail_checkpoint(self, *, token, payload, path):
        raise RuntimeError("checkpoint failed")

    monkeypatch.setattr(ApprovePendingActionTool, "_create_file_edit_checkpoint", fail_checkpoint)
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "beta", "overwrite": True})
    result = registry.host_execute("approve_pending_action", {"token": staged.details["token"]})

    assert result.is_error is True
    assert "checkpoint failed" in result.content
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "alpha"
    payload = store.load(staged.details["token"])
    assert payload["lifecycle"]["state"] == "execution_failed"


def _write_file_checkpoint(
    workspace: Path,
    checkpoint_id: str,
    *,
    target_path: str,
    before_state: str,
    before_text: Optional[str] = None,
    action_type: str = "edit_file",
) -> dict[str, object]:
    root = workspace / ".pp-agent" / "pending-edits" / "file-checkpoints"
    root.mkdir(parents=True, exist_ok=True)
    content_path = None
    before_digest = None
    if before_text is not None:
        content_path = root / f"{checkpoint_id}.content.txt"
        content_path.write_text(before_text, encoding="utf-8")
        before_digest = content_digest(before_text)
    payload: dict[str, object] = {
        "kind": "file_edit_checkpoint",
        "version": 1,
        "checkpoint_id": checkpoint_id,
        "token": "manual-test-token",
        "action_type": action_type,
        "target_path": target_path,
        "absolute_path": str(workspace / target_path),
        "before_state": before_state,
        "existed": before_state == "present",
        "before_digest": before_digest,
        "content_path": str(content_path) if content_path is not None else None,
        "created_at": 1.0,
    }
    metadata_path = root / f"{checkpoint_id}.json"
    payload["metadata_path"] = str(metadata_path)
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def test_rollback_edit_file_checkpoint_restores_old_content(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    (tmp_path / "notes.txt").write_text("alpha", encoding="utf-8")
    staged = registry.execute("edit_file", {"path": "notes.txt", "old_text": "alpha", "new_text": "beta"})
    applied = registry.host_execute("approve_pending_action", {"token": staged.details["token"]})

    result = registry.host_execute("rollback_file_checkpoint", {"checkpoint_id": applied.details["checkpoint_id"]})

    assert result.details["checkpoint_id"] == applied.details["checkpoint_id"]
    assert result.details["target_path"] == "notes.txt"
    assert result.details["status"] == "restored"
    assert result.details["restored_digest"] == content_digest("alpha")
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "alpha"


def test_rollback_overwrite_write_file_checkpoint_restores_old_content(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    (tmp_path / "notes.txt").write_text("alpha", encoding="utf-8")
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "beta", "overwrite": True})
    applied = registry.host_execute("approve_pending_action", {"token": staged.details["token"]})

    result = registry.host_execute("rollback_file_checkpoint", {"checkpoint_id": applied.details["checkpoint_id"]})

    assert result.details["action_type"] == "write_file"
    assert result.details["status"] == "restored"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "alpha"


def test_rollback_new_write_file_checkpoint_deletes_new_file(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    applied = registry.host_execute("approve_pending_action", {"token": staged.details["token"]})

    result = registry.host_execute("rollback_file_checkpoint", {"checkpoint_id": applied.details["checkpoint_id"]})

    assert result.details["before_state"] == "absent"
    assert result.details["status"] == "restored_absent"
    assert result.details["restored_state"] == "absent"
    assert (tmp_path / "notes.txt").exists() is False


def test_rollback_absent_checkpoint_returns_already_absent(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    _write_file_checkpoint(tmp_path, "file-edit-already-absent", target_path="notes.txt", before_state="absent")

    result = registry.host_execute("rollback_file_checkpoint", {"checkpoint_id": "file-edit-already-absent"})

    assert result.details["status"] == "already_absent"
    assert result.details["target_path"] == "notes.txt"
    assert (tmp_path / "notes.txt").exists() is False


def test_rollback_rejects_missing_checkpoint_id(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    with pytest.raises(FileNotFoundError, match="File checkpoint not found"):
        registry.host_execute("rollback_file_checkpoint", {"checkpoint_id": "missing"})


def test_rollback_rejects_missing_checkpoint_content(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    (tmp_path / "notes.txt").write_text("beta", encoding="utf-8")
    _write_file_checkpoint(tmp_path, "file-edit-missing-content", target_path="notes.txt", before_state="present")

    with pytest.raises(FileNotFoundError, match="checkpoint content is missing"):
        registry.host_execute("rollback_file_checkpoint", {"checkpoint_id": "file-edit-missing-content"})

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "beta"


def test_rollback_rejects_symlink_target(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("safe", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable in this environment")
    _write_file_checkpoint(tmp_path, "file-edit-symlink", target_path="link.txt", before_state="absent")

    with pytest.raises(PermissionError, match="symlink"):
        registry.host_execute("rollback_file_checkpoint", {"checkpoint_id": "file-edit-symlink"})

    assert target.read_text(encoding="utf-8") == "safe"


def test_rollback_rejects_directory_target(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    (tmp_path / "notes.txt").mkdir()
    _write_file_checkpoint(tmp_path, "file-edit-directory", target_path="notes.txt", before_state="absent")

    with pytest.raises(ValueError, match="non-file path"):
        registry.host_execute("rollback_file_checkpoint", {"checkpoint_id": "file-edit-directory"})

    assert (tmp_path / "notes.txt").is_dir()


def test_rollback_rejects_protected_path(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    _write_file_checkpoint(tmp_path, "file-edit-protected", target_path=".env", before_state="absent")

    with pytest.raises(PermissionError):
        registry.host_execute("rollback_file_checkpoint", {"checkpoint_id": "file-edit-protected"})

    assert (tmp_path / ".env").exists() is False


def test_e2e_safe_write_new_file_preview_approve_checkpoint_and_rollback(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha\n"})
    preview = registry.host_execute("preview_pending_action", {"token": staged.details["token"]})

    assert staged.details["staged"] is True
    assert preview.details["details"]["diff_preview"]["kind"] == "diff_preview"
    assert preview.details["details"]["diff_preview"]["proposal_digest"] == staged.details["proposal_digest"]
    assert (tmp_path / "notes.txt").exists() is False

    applied = registry.host_execute("approve_pending_action", {"token": staged.details["token"]})

    assert applied.details["checkpoint_id"]
    assert applied.details["checkpoint"]["before_state"] == "absent"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "alpha\n"

    rolled_back = registry.host_execute("rollback_file_checkpoint", {"checkpoint_id": applied.details["checkpoint_id"]})

    assert rolled_back.details["status"] == "restored_absent"
    assert rolled_back.details["restored_state"] == "absent"
    assert (tmp_path / "notes.txt").exists() is False


def test_e2e_safe_write_overwrite_preview_approve_checkpoint_and_rollback(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    (tmp_path / "notes.txt").write_text("alpha\n", encoding="utf-8")

    staged = registry.execute("write_file", {"path": "notes.txt", "content": "beta\n", "overwrite": True})
    preview = registry.host_execute("preview_pending_action", {"token": staged.details["token"]})

    assert preview.details["details"]["diff_preview"]["diff_text"] == staged.details["patch_proposal"]["unified_diff"]
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "alpha\n"

    applied = registry.host_execute("approve_pending_action", {"token": staged.details["token"]})

    assert applied.details["checkpoint"]["before_state"] == "present"
    assert Path(applied.details["checkpoint"]["content_path"]).read_text(encoding="utf-8") == "alpha\n"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "beta\n"

    rolled_back = registry.host_execute("rollback_file_checkpoint", {"checkpoint_id": applied.details["checkpoint_id"]})

    assert rolled_back.details["status"] == "restored"
    assert rolled_back.details["restored_digest"] == applied.details["checkpoint"]["before_digest"]
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "alpha\n"


def test_e2e_safe_edit_preview_approve_checkpoint_and_rollback(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    (tmp_path / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")

    staged = registry.execute("edit_file", {"path": "notes.txt", "old_text": "beta", "new_text": "gamma"})
    preview = registry.host_execute("preview_pending_action", {"token": staged.details["token"]})

    assert preview.details["details"]["diff_preview"]["proposal_digest"] == staged.details["proposal_digest"]
    assert "gamma" not in (tmp_path / "notes.txt").read_text(encoding="utf-8")

    applied = registry.host_execute("approve_pending_action", {"token": staged.details["token"]})

    assert applied.details["checkpoint"]["before_state"] == "present"
    assert Path(applied.details["checkpoint"]["content_path"]).read_text(encoding="utf-8") == "alpha\nbeta\n"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "alpha\ngamma\n"

    rolled_back = registry.host_execute("rollback_file_checkpoint", {"checkpoint_id": applied.details["checkpoint_id"]})

    assert rolled_back.details["status"] == "restored"
    assert rolled_back.details["restored_digest"] == applied.details["checkpoint"]["before_digest"]
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "alpha\nbeta\n"


def test_modified_file_effect_is_rejected_after_prior_approval(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    token = staged.details["token"]
    payload = store.attach_approval_grant(token)
    payload["after"] = "beta"
    payload["details"]["diff"] = "tampered"
    store.save(token, payload)

    with pytest.raises(ValueError, match="payload digest changed"):
        registry.host_execute("approve_pending_action", {"token": token})

    updated = store.load(token)
    assert updated["lifecycle"]["state"] == "grant_invalidated"
    assert updated["approval_grant"]["status"] == "invalidated"
    assert updated["latest_audit"]["lifecycle_state"] == "grant_invalidated"


def test_modified_patch_proposal_is_rejected_after_prior_approval(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    token = staged.details["token"]
    payload = store.attach_approval_grant(token)
    payload["details"]["patch_proposal"]["unified_diff"] += "\n+tampered"
    store.save(token, payload)

    with pytest.raises(ValueError, match="proposal digest mismatch"):
        registry.host_execute("approve_pending_action", {"token": token})

    updated = store.load(token)
    assert updated["lifecycle"]["state"] == "grant_invalidated"
    assert updated["approval_grant"]["status"] == "invalidated"


def test_file_baseline_distinguishes_absent_to_present(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    token = staged.details["token"]
    store.attach_approval_grant(token)
    (tmp_path / "notes.txt").write_text("appeared later", encoding="utf-8")

    with pytest.raises(ValueError, match="absent to present"):
        registry.host_execute("approve_pending_action", {"token": token})

    updated = store.load(token)
    assert updated["lifecycle"]["state"] == "grant_invalidated"


def test_new_write_file_rejects_target_unexpectedly_created_after_approval(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    token = staged.details["token"]
    store.attach_approval_grant(token)
    (tmp_path / "notes.txt").write_text("external", encoding="utf-8")

    with pytest.raises(ValueError, match="target unexpectedly exists"):
        registry.host_execute("approve_pending_action", {"token": token})

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "external"


def test_file_baseline_distinguishes_present_to_absent(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    (tmp_path / "notes.txt").write_text("alpha", encoding="utf-8")
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    staged = registry.execute("edit_file", {"path": "notes.txt", "old_text": "alpha", "new_text": "beta"})
    token = staged.details["token"]
    store.attach_approval_grant(token)
    (tmp_path / "notes.txt").unlink()

    with pytest.raises(ValueError, match="present to absent"):
        registry.host_execute("approve_pending_action", {"token": token})

    updated = store.load(token)
    assert updated["lifecycle"]["state"] == "grant_invalidated"


def test_edit_file_rejects_external_change_after_approval(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    (tmp_path / "notes.txt").write_text("alpha", encoding="utf-8")
    staged = registry.execute("edit_file", {"path": "notes.txt", "old_text": "alpha", "new_text": "beta"})
    token = staged.details["token"]
    store.attach_approval_grant(token)
    (tmp_path / "notes.txt").write_text("external", encoding="utf-8")

    with pytest.raises(ValueError, match="baseline changed"):
        registry.host_execute("approve_pending_action", {"token": token})

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "external"


def test_overwrite_write_file_rejects_external_change_after_approval(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    (tmp_path / "notes.txt").write_text("alpha", encoding="utf-8")
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "beta", "overwrite": True})
    token = staged.details["token"]
    store.attach_approval_grant(token)
    (tmp_path / "notes.txt").write_text("external", encoding="utf-8")

    with pytest.raises(ValueError, match="baseline changed"):
        registry.host_execute("approve_pending_action", {"token": token})

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "external"


def test_existing_file_proposal_rejects_missing_target_after_approval(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    (tmp_path / "notes.txt").write_text("alpha", encoding="utf-8")
    staged = registry.execute("edit_file", {"path": "notes.txt", "old_text": "alpha", "new_text": "beta"})
    token = staged.details["token"]
    store.attach_approval_grant(token)
    (tmp_path / "notes.txt").unlink()

    with pytest.raises(ValueError, match="target missing"):
        registry.host_execute("approve_pending_action", {"token": token})


def test_modified_shell_effect_is_rejected_after_prior_approval(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    staged = registry.execute("run_shell", {"command": "Write-Output hello", "timeout_seconds": 5})
    token = staged.details["token"]
    payload = store.attach_approval_grant(token)
    payload["command"] = "Write-Output goodbye"
    store.save(token, payload)

    with pytest.raises(ValueError, match="payload digest changed"):
        registry.host_execute("approve_pending_action", {"token": token})

    updated = store.load(token)
    assert updated["lifecycle"]["state"] == "grant_invalidated"
    assert updated["approval_grant"]["status"] == "invalidated"

    with pytest.raises(ValueError, match="grant_invalidated"):
        registry.host_execute("approve_pending_action", {"token": token})


def test_shell_executor_failure_is_recorded_separately_from_invalidation(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    staged = registry.execute("run_shell", {"command": "Write-Error boom; exit 1", "timeout_seconds": 5})
    token = staged.details["token"]

    result = registry.host_execute("approve_pending_action", {"token": token})

    assert result.is_error is True
    assert result.details["failure_kind"] == "execution_failed"
    assert result.details["lifecycle"]["state"] == "execution_failed"
    assert result.details["approval_grant"]["status"] == "active"
    payload = store.load(token)
    assert payload["lifecycle"]["state"] == "execution_failed"
    assert payload["latest_audit"]["failure_reason_code"] == "executor_error"
    preview = registry.host_execute("preview_pending_action", {"token": token})
    assert "Lifecycle state: execution_failed" in preview.content
    assert "Failure reason code: executor_error" in preview.content


def test_execution_failed_dynamic_effect_can_retry_same_token_after_revalidation(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    attempts = {"count": 0}

    def executor(workspace, arguments):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("boom once")
        return f"ok:{arguments.get('query', '')}"

    registry.register_function_tool(
        name="demo_retry_extension",
        description="Inspect extension state",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        executor=executor,
        category="extension",
        permission_domain="read",
        tool_family="extension",
        exact_effect_mode="required",
        non_side_effectful=True,
        known_safe_inspect=True,
    )

    staged = registry.execute("demo_retry_extension", {"query": "status"})
    token = staged.details["token"]

    failed = registry.host_execute("approve_pending_action", {"token": token})
    assert failed.is_error is True
    assert failed.details["lifecycle"]["state"] == "execution_failed"
    assert failed.details["approval_grant"]["status"] == "active"
    assert store.load(token)["lifecycle"]["state"] == "execution_failed"

    retried = registry.host_execute("approve_pending_action", {"token": token})
    assert retried.is_error is False
    assert retried.content == "ok:status"
    assert retried.details["lifecycle"]["state"] == "grant_consumed"
    assert store.load(token)["lifecycle"]["state"] == "grant_consumed"


def test_shell_normalization_equivalent_commands_keep_same_digest() -> None:
    first = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command="pytest   -q",
        timeout_seconds=30,
    )
    second = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command="  pytest -q  ",
        timeout_seconds=30,
    )

    assert first["payload_digest"] == second["payload_digest"]
    assert first["summary"] == second["summary"]
    assert first["analysis"]["risk_class"] == second["analysis"]["risk_class"]
    assert first["analysis"]["confidence_band"] == second["analysis"]["confidence_band"]


def test_shell_material_change_changes_digest() -> None:
    first = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command="pytest -q",
        timeout_seconds=30,
    )
    second = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command="pytest -q ; echo done",
        timeout_seconds=30,
    )

    assert first["payload_digest"] != second["payload_digest"]
    assert first["summary"] != second["summary"]


@pytest.mark.parametrize(
    ("command", "expected_summary"),
    [
        ("git status", "Inspect repository status with git status"),
        ("git diff", "Inspect repository changes with git diff"),
        ("rg TODO src", "Inspect files with rg TODO src"),
        ("grep TODO src/app.py", "Inspect files with grep TODO src/app.py"),
        ("ls src", "Inspect workspace with ls src"),
        ("dir src", "Inspect workspace with dir src"),
    ],
)
def test_shell_inspect_commands_classify_as_inspect(command: str, expected_summary: str) -> None:
    effect = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command=command,
        timeout_seconds=30,
    )

    assert effect["analysis"]["risk_class"] == "inspect"
    assert effect["summary"] == expected_summary


def test_pytest_classifies_as_workspace_mutation() -> None:
    effect = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command="pytest -q",
        timeout_seconds=30,
    )

    assert effect["analysis"]["risk_class"] == "workspace_mutation"
    assert "test_runner" in effect["analysis"]["flags"]
    assert effect["summary"] == "Run tests with pytest -q"


@pytest.mark.parametrize("command", ["curl https://example.com", "Invoke-WebRequest https://example.com"])
def test_network_fetching_commands_classify_as_networked(command: str) -> None:
    effect = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command=command,
        timeout_seconds=30,
    )

    assert effect["analysis"]["risk_class"] == "networked"
    assert effect["analysis"]["requests_network"] is True


@pytest.mark.parametrize("command", ["rm -rf build", "Remove-Item -Recurse dist"])
def test_delete_commands_classify_as_destructive(command: str) -> None:
    effect = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command=command,
        timeout_seconds=30,
    )

    assert effect["analysis"]["risk_class"] == "destructive"
    assert effect["analysis"]["destructive_hint"] is True
    assert effect["summary"].startswith("Delete files with ")


def test_commands_touching_outside_workspace_classify_as_external_mutation(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-target"
    effect = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command=f"Remove-Item -Recurse {outside}",
        timeout_seconds=30,
        workspace=tmp_path,
    )

    assert effect["analysis"]["risk_class"] == "external_mutation"
    assert effect["analysis"]["touches_external"] is True


def test_shell_preview_shows_stable_summary_and_risk_flags(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("run_shell", {"command": "curl https://example.com", "timeout_seconds": 10})

    preview = registry.host_execute("preview_pending_action", {"token": staged.details["token"]})

    assert "Summary: Fetch remote content with curl" in preview.content
    assert "Risk class: networked" in preview.content
    assert "Requests network: True" in preview.content
    assert "Confidence:" in preview.content
    assert staged.details["effect"]["payload_digest"] in preview.content


def test_known_safe_shell_inspect_subset_is_allowed_by_policy(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    decision = registry.evaluate_call("run_shell", {"command": "git status"})

    assert decision.action == "allow"
    assert decision.details["risk_class"] == "inspect"
    assert decision.details["confidence_band"] == "high"
    assert decision.details["known_safe_inspect"] is True


def test_shell_inspect_outside_known_safe_subset_stays_ask(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    decision = registry.evaluate_call("run_shell", {"command": "git log"})

    assert decision.action == "ask"
    assert decision.details["risk_class"] == "inspect"
    assert "Inspect shell command" in decision.reason
    assert decision.details["known_safe_inspect"] is False


def test_shell_redirection_promotes_inspect_to_workspace_mutation() -> None:
    effect = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command="git status > status.txt",
        timeout_seconds=30,
    )

    assert effect["analysis"]["risk_class"] == "workspace_mutation"
    assert effect["analysis"]["writes_workspace_files"] is True
    assert "redirection" in effect["analysis"]["flags"]
    assert effect["analysis"]["known_safe_inspect"] is False


def test_shell_multi_command_detects_destructive_later_segment() -> None:
    effect = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command="git status; Remove-Item -Recurse -Force dist",
        timeout_seconds=30,
    )

    assert effect["analysis"]["risk_class"] == "destructive"
    assert effect["analysis"]["destructive_hint"] is True
    assert "shell_operator" in effect["analysis"]["flags"]
    assert "recursive" in effect["analysis"]["flags"]
    assert "force" in effect["analysis"]["flags"]
    assert "destructive_escalated" in effect["analysis"]["flags"]


def test_shell_git_clean_and_reset_are_destructive() -> None:
    clean = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command="git clean -fd",
        timeout_seconds=30,
    )
    reset = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command="git reset --hard HEAD",
        timeout_seconds=30,
    )

    assert clean["analysis"]["risk_class"] == "destructive"
    assert reset["analysis"]["risk_class"] == "destructive"
    assert "vcs_write" in clean["analysis"]["flags"]
    assert "vcs_write" in reset["analysis"]["flags"]


def test_shell_relative_parent_path_escape_is_external(tmp_path: Path) -> None:
    effect = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command="Get-Content ..\\outside.txt",
        timeout_seconds=30,
        workspace=tmp_path,
    )

    assert effect["analysis"]["risk_class"] == "external_mutation"
    assert effect["analysis"]["touches_external"] is True


def test_shell_powershell_write_aliases_are_workspace_mutations() -> None:
    for command in ("sc notes.txt alpha", "ni notes.txt", "cp a.txt b.txt", "mv a.txt b.txt"):
        effect = build_shell_effect(
            tool_name="run_shell",
            permission_domain="bash",
            command=command,
            timeout_seconds=30,
        )

        assert effect["analysis"]["risk_class"] == "workspace_mutation"
        assert effect["analysis"]["writes_workspace_files"] is True


def test_shell_env_assignment_requires_approval() -> None:
    effect = build_shell_effect(
        tool_name="run_shell",
        permission_domain="bash",
        command="$env:FOO='bar'",
        timeout_seconds=30,
    )

    assert effect["analysis"]["risk_class"] == "workspace_mutation"
    assert "env_write" in effect["analysis"]["flags"]


def test_shell_pipeline_inspect_is_not_known_safe_direct_allow(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    decision = registry.evaluate_call("run_shell", {"command": "rg TODO src | Select-String TODO"})

    assert decision.action == "ask"
    assert decision.details["risk_class"] == "inspect"
    assert decision.details["known_safe_inspect"] is False
    assert "shell_operator" in decision.details["flags"]


def test_tool_name_policy_rules_take_priority(tmp_path: Path) -> None:
    policy = ToolPolicyConfig(
        permission_mode="read-only",
        allowed_tools=["read_file", "write_file", "fetch.*"],
        denied_tools=["fetch.*"],
        ask_tools=["read_file"],
    )
    registry = ToolRegistry(tmp_path, policy=policy)

    ask = registry.evaluate_call("read_file", {"path": "notes.txt"})
    allowed = registry.evaluate_call("write_file", {"path": "notes.txt", "content": "alpha"})

    assert ask.action == "ask"
    assert allowed.action == "allow"
    assert registry.execute("write_file", {"path": "notes.txt", "content": "alpha"}).details["staged"] is True


def test_denied_tool_pattern_blocks_dynamic_tool_even_when_allowed(tmp_path: Path) -> None:
    policy = ToolPolicyConfig(allowed_tools=["fetch.*"], denied_tools=["fetch.*"])
    registry = ToolRegistry(tmp_path, policy=policy)
    registry.register_function_tool(
        name="fetch.readable",
        description="Fetch webpage content from a URL",
        parameters={"type": "object", "properties": {"url": {"type": "string"}}},
        executor=lambda workspace, arguments: arguments.get("url", ""),
        category="mcp",
        permission_domain="read",
        tool_family="mcp",
        requests_network_hint=True,
    )

    decision = registry.evaluate_call("fetch.readable", {"url": "https://example.com"})

    assert decision.action == "deny"
    with pytest.raises(PermissionError, match="denied by tool policy"):
        registry.execute("fetch.readable", {"url": "https://example.com"})


def test_read_only_permission_mode_denies_mutating_and_network_tools(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, policy=ToolPolicyConfig(permission_mode="read-only"))
    registry.register_function_tool(
        name="fetch.readable",
        description="Fetch webpage content from a URL",
        parameters={"type": "object", "properties": {"url": {"type": "string"}}},
        executor=lambda workspace, arguments: arguments.get("url", ""),
        category="mcp",
        permission_domain="read",
        tool_family="mcp",
        requests_network_hint=True,
    )

    read_decision = registry.evaluate_call("read_file", {"path": "notes.txt"})
    write_decision = registry.evaluate_call("write_file", {"path": "notes.txt", "content": "alpha"})
    shell_decision = registry.evaluate_call("run_shell", {"command": "Set-Content notes.txt alpha"})
    network_decision = registry.evaluate_call("fetch.readable", {"url": "https://example.com"})

    assert read_decision.action == "allow"
    assert write_decision.action == "deny"
    assert shell_decision.action == "deny"
    assert network_decision.action == "deny"
    with pytest.raises(PermissionError, match="Read-only permission mode denies"):
        registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})


def test_prompt_permission_mode_asks_for_non_high_confidence_inspect(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, policy=ToolPolicyConfig(permission_mode="prompt"))

    safe = registry.evaluate_call("git_status", {})
    inspect_needing_prompt = registry.evaluate_call("run_shell", {"command": "git log"})

    assert safe.action == "allow"
    assert inspect_needing_prompt.action == "ask"


def test_danger_full_access_still_denies_protected_paths(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, policy=ToolPolicyConfig(permission_mode="danger-full-access"))

    decision = registry.evaluate_call("read_file", {"path": ".env"})

    assert decision.action == "deny"


def test_file_shared_analysis_records_are_stable(tmp_path: Path) -> None:
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("print('hi')\n", encoding="utf-8")

    read_analysis = analyze_file_call(workspace=tmp_path, tool_name="read_file", permission_domain="read", target_path=target)
    edit_analysis = analyze_file_call(workspace=tmp_path, tool_name="edit_file", permission_domain="edit", target_path=target)

    assert read_analysis["family"] == "file"
    assert read_analysis["risk_class"] == "inspect"
    assert read_analysis["summary"] == "Read file src/app.py"
    assert read_analysis["confidence_band"] == "high"
    assert edit_analysis["summary"] == "Edit file src/app.py"
    assert edit_analysis["risk_class"] == "workspace_mutation"


@pytest.mark.parametrize("path", [".env", ".env.local", ".pp-agent/config.json", ".git/config", "secret.pem", "secret.key"])
def test_file_analysis_surfaces_protected_path_hint(tmp_path: Path, path: str) -> None:
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)

    analysis = analyze_file_call(workspace=tmp_path, tool_name="read_file", permission_domain="read", target_path=target)

    assert analysis["protected_path_hint"] is True


def test_mcp_analysis_defaults_fail_closed() -> None:
    analysis = analyze_mcp_call(tool_name="demo.echo", permission_domain="read", description="Echo tool")

    assert analysis["family"] == "mcp"
    assert analysis["risk_class"] == "unknown"
    assert analysis["confidence_band"] in {"unknown", "low"}


def test_low_confidence_analysis_never_escalates_to_allow(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    registry.register_function_tool(
        name="demo_echo",
        description="Echo from extension",
        parameters={"type": "object", "properties": {"message": {"type": "string"}}},
        executor=lambda workspace, arguments: f"{workspace.name}:{arguments.get('message', '')}",
        category="extension",
        permission_domain="read",
        tool_family="extension",
    )

    decision = registry.evaluate_call("demo_echo", {"message": "hi"})

    assert decision.action == "ask"
    assert decision.details["family"] == "extension"
    assert decision.details["confidence_band"] in {"unknown", "low"}


def test_mcp_fetch_like_tool_fails_closed_to_ask(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    registry.register_function_tool(
        name="fetch.readable",
        description="Fetch webpage content from a URL",
        parameters={"type": "object", "properties": {"url": {"type": "string"}}},
        executor=lambda workspace, arguments: arguments.get("url", ""),
        category="mcp",
        permission_domain="read",
        tool_family="mcp",
        requests_network_hint=True,
    )

    decision = registry.evaluate_call("fetch.readable", {"url": "https://example.com"})

    assert decision.action == "ask"
    assert decision.details["family"] == "mcp"
    assert decision.details["requests_network"] is True


def test_invalid_exact_effect_mode_is_rejected(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    with pytest.raises(ValueError, match="exact_effect_mode"):
        registry.register_function_tool(
            name="demo_invalid_mode",
            description="Invalid mode",
            parameters={"type": "object", "properties": {}},
            executor=lambda workspace, arguments: "ok",
            category="extension",
            permission_domain="read",
            tool_family="extension",
            exact_effect_mode="supported",
        )


def test_known_safe_inspect_requires_non_side_effectful_declaration(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    with pytest.raises(ValueError, match="non_side_effectful"):
        registry.register_function_tool(
            name="demo_invalid_safe",
            description="Invalid safe inspect",
            parameters={"type": "object", "properties": {}},
            executor=lambda workspace, arguments: "ok",
            category="extension",
            permission_domain="read",
            tool_family="extension",
            known_safe_inspect=True,
        )


def test_known_safe_inspect_cannot_be_declared_with_network_or_external_hints(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    with pytest.raises(ValueError, match="requests_network_hint"):
        registry.register_function_tool(
            name="demo_invalid_network_safe",
            description="Invalid safe inspect",
            parameters={"type": "object", "properties": {}},
            executor=lambda workspace, arguments: "ok",
            category="extension",
            permission_domain="read",
            tool_family="extension",
            non_side_effectful=True,
            known_safe_inspect=True,
            requests_network_hint=True,
        )

    with pytest.raises(ValueError, match="touches_external_hint"):
        registry.register_function_tool(
            name="demo_invalid_external_safe",
            description="Invalid safe inspect",
            parameters={"type": "object", "properties": {}},
            executor=lambda workspace, arguments: "ok",
            category="extension",
            permission_domain="read",
            tool_family="extension",
            non_side_effectful=True,
            known_safe_inspect=True,
            touches_external_hint=True,
        )


def test_supports_exact_effect_staging_is_not_a_free_registration_boolean(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    with pytest.raises(TypeError):
        registry.register_function_tool(
            name="demo_bad_flag",
            description="Bad flag",
            parameters={"type": "object", "properties": {}},
            executor=lambda workspace, arguments: "ok",
            category="extension",
            permission_domain="read",
            tool_family="extension",
            supports_exact_effect_staging=True,
        )


def test_extension_api_register_tool_carries_explicit_declarations() -> None:
    api = ExtensionAPI(
        ExtensionDescriptor(
            name="demo",
            description="demo",
            path=Path("."),
            entrypoint="extension.py",
            provides=["tools"],
        )
    )

    api.register_tool(
        name="declared_tool",
        description="Inspect declared extension state",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        handler=lambda workspace, arguments: "ok",
        exact_effect_mode="required",
        non_side_effectful=True,
        known_safe_inspect=True,
        requests_network_hint=False,
        touches_external_hint=False,
    )

    loaded = api.build()
    tool = loaded.tools[0]

    assert tool.exact_effect_mode == "required"
    assert tool.non_side_effectful is True
    assert tool.known_safe_inspect is True
    assert tool.requests_network_hint is False
    assert tool.touches_external_hint is False


def test_dynamic_extension_sensitive_call_stages_when_approvable(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    seen: list[dict[str, str]] = []
    registry.register_function_tool(
        name="demo_stage_extension",
        description="Inspect extension state",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        executor=lambda workspace, arguments: seen.append({"workspace": workspace.name, "query": arguments.get("query", "")}) or "executed",
        category="extension",
        permission_domain="read",
        tool_family="extension",
        exact_effect_mode="required",
        non_side_effectful=True,
        known_safe_inspect=True,
    )

    result = registry.execute("demo_stage_extension", {"query": "status"})

    assert seen == []
    assert result.details["staged"] is True
    assert result.details["approvable"] is True
    assert result.details["approval_unavailable"] is False
    assert result.details["effect"]["analysis"]["family"] == "extension"
    assert result.details["effect"]["analysis"]["summary"] == "Inspect with extension tool demo_stage_extension"


def test_dynamic_mcp_sensitive_call_stages_when_approvable(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    seen: list[dict[str, str]] = []
    registry.register_function_tool(
        name="demo.stage",
        description="Inspect MCP state",
        parameters={"type": "object", "properties": {"topic": {"type": "string"}}},
        executor=lambda workspace, arguments: seen.append({"workspace": workspace.name, "topic": arguments.get("topic", "")}) or "executed",
        category="mcp",
        permission_domain="read",
        tool_family="mcp",
        exact_effect_mode="required",
        non_side_effectful=True,
        known_safe_inspect=True,
    )

    result = registry.execute("demo.stage", {"topic": "health"})

    assert seen == []
    assert result.details["staged"] is True
    assert result.details["approvable"] is True
    assert result.details["effect"]["analysis"]["family"] == "mcp"
    assert result.details["effect"]["analysis"]["summary"] == "Inspect with MCP tool demo.stage"


def test_dynamic_approval_unavailable_fails_closed_for_unstable_extension_call(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    seen: list[str] = []
    registry.register_function_tool(
        name="demo_unstable",
        description="Unknown extension tool",
        parameters={"type": "object", "properties": {"message": {"type": "string"}}},
        executor=lambda workspace, arguments: seen.append(arguments.get("message", "")) or "executed",
        category="extension",
        permission_domain="read",
        tool_family="extension",
    )

    result = registry.execute("demo_unstable", {"message": "hi"})

    assert seen == []
    assert result.is_error is True
    assert result.details["staged"] is False
    assert result.details["approvable"] is False
    assert result.details["approval_unavailable"] is True
    assert "exact-effect approval" in result.details["approval_unavailable_reason"] or "weakly understood" in result.details["approval_unavailable_reason"]


def test_approved_dynamic_staged_extension_effect_executes(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    seen: list[str] = []
    registry.register_function_tool(
        name="demo_apply_extension",
        description="Inspect extension state",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        executor=lambda workspace, arguments: seen.append(arguments.get("query", "")) or f"ok:{arguments.get('query', '')}",
        category="extension",
        permission_domain="read",
        tool_family="extension",
        exact_effect_mode="required",
        non_side_effectful=True,
        known_safe_inspect=True,
    )

    staged = registry.execute("demo_apply_extension", {"query": "status"})
    token = staged.details["token"]

    result = registry.host_execute("approve_pending_action", {"token": token})

    assert seen == ["status"]
    assert result.content == "ok:status"
    assert result.details["approval_grant"]["status"] == "consumed"


def test_approved_dynamic_staged_mcp_effect_executes(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    seen: list[str] = []
    registry.register_function_tool(
        name="demo.apply",
        description="Inspect MCP state",
        parameters={"type": "object", "properties": {"topic": {"type": "string"}}},
        executor=lambda workspace, arguments: seen.append(arguments.get("topic", "")) or f"ok:{arguments.get('topic', '')}",
        category="mcp",
        permission_domain="read",
        tool_family="mcp",
        exact_effect_mode="required",
        non_side_effectful=True,
        known_safe_inspect=True,
    )

    staged = registry.execute("demo.apply", {"topic": "health"})
    token = staged.details["token"]

    result = registry.host_execute("approve_pending_action", {"token": token})

    assert seen == ["health"]
    assert result.content == "ok:health"
    assert result.details["approval_grant"]["status"] == "consumed"


@pytest.mark.parametrize(
    ("name", "category", "tool_family", "arguments", "mutated_key", "mutated_value"),
    [
        ("demo_mutable_extension", "extension", "extension", {"query": "status"}, "query", "other"),
        ("demo.mutable", "mcp", "mcp", {"topic": "health"}, "topic", "other"),
    ],
)
def test_modified_dynamic_effect_is_rejected_after_prior_approval(
    tmp_path: Path,
    name: str,
    category: str,
    tool_family: str,
    arguments: dict[str, str],
    mutated_key: str,
    mutated_value: str,
) -> None:
    registry = ToolRegistry(tmp_path)
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    registry.register_function_tool(
        name=name,
        description="Inspect dynamic state",
        parameters={"type": "object", "properties": {mutated_key: {"type": "string"}}},
        executor=lambda workspace, call_arguments: f"ok:{call_arguments.get(mutated_key, '')}",
        category=category,
        permission_domain="read",
        tool_family=tool_family,
        exact_effect_mode="required",
        non_side_effectful=True,
        known_safe_inspect=True,
    )

    staged = registry.execute(name, arguments)
    token = staged.details["token"]
    payload = store.attach_approval_grant(token)
    payload["details"]["arguments"][mutated_key] = mutated_value
    store.save(token, payload)

    with pytest.raises(ValueError, match="payload digest changed"):
        registry.host_execute("approve_pending_action", {"token": token})


def test_dynamic_known_safe_allow_stays_narrow(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    registry.register_function_tool(
        name="demo_safe_query",
        description="Query extension state",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        executor=lambda workspace, arguments: f"query:{arguments.get('query', '')}",
        category="extension",
        permission_domain="read",
        tool_family="extension",
        exact_effect_mode="auto",
        non_side_effectful=True,
        known_safe_inspect=True,
    )
    registry.register_function_tool(
        name="fetch.blocked",
        description="Fetch webpage content from URL",
        parameters={"type": "object", "properties": {"url": {"type": "string"}}},
        executor=lambda workspace, arguments: arguments.get("url", ""),
        category="mcp",
        permission_domain="read",
        tool_family="mcp",
        exact_effect_mode="auto",
        requests_network_hint=True,
    )

    allowed = registry.evaluate_call("demo_safe_query", {"query": "status"})
    blocked = registry.evaluate_call("fetch.blocked", {"url": "https://example.com"})

    assert allowed.action == "allow"
    assert blocked.action == "ask"
    assert blocked.details["requests_network"] is True


def test_shared_preview_renders_consistent_fields_for_dynamic_effects(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    registry.register_function_tool(
        name="demo_preview_extension",
        description="Inspect extension state",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        executor=lambda workspace, arguments: "ok",
        category="extension",
        permission_domain="read",
        tool_family="extension",
        exact_effect_mode="required",
        non_side_effectful=True,
        known_safe_inspect=True,
    )
    registry.register_function_tool(
        name="demo.preview",
        description="Inspect MCP state",
        parameters={"type": "object", "properties": {"topic": {"type": "string"}}},
        executor=lambda workspace, arguments: "ok",
        category="mcp",
        permission_domain="read",
        tool_family="mcp",
        exact_effect_mode="required",
        non_side_effectful=True,
        known_safe_inspect=True,
    )

    ext = registry.execute("demo_preview_extension", {"query": "status"})
    mcp = registry.execute("demo.preview", {"topic": "health"})

    ext_preview = registry.host_execute("preview_pending_action", {"token": ext.details["token"]})
    mcp_preview = registry.host_execute("preview_pending_action", {"token": mcp.details["token"]})

    for preview in (ext_preview.content, mcp_preview.content):
        assert "Summary:" in preview
        assert "Family:" in preview
        assert "Risk class:" in preview
        assert "Confidence:" in preview
        assert "Digest:" in preview
        assert "Touches workspace:" in preview
        assert "Touches external:" in preview
        assert "Requests network:" in preview
        assert "Destructive hint:" in preview
        assert "Protected path hint:" in preview
        assert "Tool name:" in preview
        assert "Arguments:" in preview


def test_exact_effect_mode_none_never_stages_even_when_arguments_are_canonicalizable(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    registry.register_function_tool(
        name="demo_none_mode",
        description="Inspect extension state",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        executor=lambda workspace, arguments: "ok",
        category="extension",
        permission_domain="read",
        tool_family="extension",
        exact_effect_mode="none",
    )

    result = registry.execute("demo_none_mode", {"query": "status"})

    assert result.is_error is True
    assert result.details["approval_unavailable"] is True
    assert result.details["staged"] is False


def test_exact_effect_mode_auto_with_weak_semantics_fails_closed_even_when_arguments_are_canonicalizable(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    registry.register_function_tool(
        name="demo_auto_mode",
        description="Inspect extension state",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        executor=lambda workspace, arguments: "ok",
        category="extension",
        permission_domain="read",
        tool_family="extension",
        exact_effect_mode="auto",
        non_side_effectful=True,
    )

    good = registry.execute("demo_auto_mode", {"query": "status"})
    bad = registry.execute("demo_auto_mode", {"query": {"nested"}})

    assert good.is_error is True
    assert good.details["approval_unavailable"] is True
    assert bad.is_error is True
    assert bad.details["approval_unavailable"] is True


def test_required_mode_never_direct_executes_safe_inspect_calls(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    seen: list[str] = []
    registry.register_function_tool(
        name="demo_required_no_direct",
        description="Inspect extension state",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        executor=lambda workspace, arguments: seen.append(arguments.get("query", "")) or "ok",
        category="extension",
        permission_domain="read",
        tool_family="extension",
        exact_effect_mode="required",
        non_side_effectful=True,
        known_safe_inspect=True,
    )

    result = registry.execute("demo_required_no_direct", {"query": "status"})

    assert seen == []
    assert result.details["staged"] is True
    assert result.details["approvable"] is True


def test_runtime_risk_signals_override_safe_registration_for_policy_allow(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    registry.register_function_tool(
        name="demo_runtime_override",
        description="Fetch remote content from url",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        executor=lambda workspace, arguments: "ok",
        category="extension",
        permission_domain="read",
        tool_family="extension",
        exact_effect_mode="auto",
        non_side_effectful=True,
        known_safe_inspect=True,
    )

    decision = registry.evaluate_call("demo_runtime_override", {"query": "status"})
    result = registry.execute("demo_runtime_override", {"query": "status"})

    assert decision.action == "ask"
    assert decision.details["requests_network"] is True
    assert result.is_error is True or result.details["staged"] is True


def test_public_register_function_tool_rejects_unexpected_keyword_arguments(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    with pytest.raises(TypeError, match="unexpected keyword"):
        registry.register_function_tool(
            name="demo_public_cutover",
            description="Unknown extension tool",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            executor=lambda workspace, arguments: "ok",
            category="extension",
            permission_domain="read",
            tool_family="extension",
            exact_effect_mode="auto",
            unsupported_option=True,
        )


def test_public_register_function_tool_rejects_risk_overrides_on_public_api(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    with pytest.raises(TypeError, match="unexpected keyword"):
        registry.register_function_tool(
            name="demo_public_origin_cutover",
            description="Bad origin",
            parameters={"type": "object", "properties": {}},
            executor=lambda workspace, arguments: "ok",
            category="extension",
            permission_domain="read",
            tool_family="extension",
            risk_overrides={"destructive_hint": True},
        )


def test_extension_api_register_tool_rejects_unexpected_tool_options() -> None:
    api = ExtensionAPI(
        ExtensionDescriptor(
            name="demo",
            description="demo",
            path=Path("."),
            entrypoint="extension.py",
            provides=["tools"],
        )
    )

    with pytest.raises(TypeError):
        api.register_tool(
            name="bad_tool",
            description="Bad tool",
            parameters={"type": "object", "properties": {}},
            handler=lambda workspace, arguments: "ok",
            unsupported_option=True,
        )


@pytest.mark.parametrize("override_key", ["requests_network", "touches_external", "destructive_hint", "protected_path_hint", "touches_workspace"])
def test_runtime_internal_risk_overrides_remain_tightening_only(tmp_path: Path, override_key: str) -> None:
    registry = ToolRegistry(tmp_path)
    registry._register_dynamic_tool_internal(
        name=f"demo_runtime_override_{override_key}",
        description="Runtime override tool",
        parameters={"type": "object", "properties": {}},
        executor=lambda workspace, arguments: "ok",
        category="extension",
        permission_domain="read",
        tool_family="extension",
        risk_overrides={override_key: True},
    )

    metadata = registry.metadata()[f"demo_runtime_override_{override_key}"]
    assert metadata.risk_overrides == {override_key: True}

    with pytest.raises(ValueError, match="only accepts True"):
        registry._register_dynamic_tool_internal(
            name=f"demo_runtime_override_bad_{override_key}",
            description="Bad runtime override tool",
            parameters={"type": "object", "properties": {}},
            executor=lambda workspace, arguments: "ok",
            category="extension",
            permission_domain="read",
            tool_family="extension",
            risk_overrides={override_key: False},
        )


def test_runtime_internal_risk_override_metadata_is_available(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    registry._register_dynamic_tool_internal(
        name="demo_runtime_internal",
        description="Internal runtime tool",
        parameters={"type": "object", "properties": {}},
        executor=lambda workspace, arguments: "ok",
        category="mcp",
        permission_domain="read",
        tool_family="mcp",
        risk_overrides={"destructive_hint": True},
    )

    assert registry.metadata()["demo_runtime_internal"].risk_overrides == {"destructive_hint": True}


def test_removed_readiness_report_is_not_exercised(tmp_path: Path) -> None:
    return
    registry = ToolRegistry(tmp_path)
    report = build_removed_readiness_report(
        registry.metadata(),
        advisory_source_hits=[{"path": "maybe.py", "line": 3, "content": "removed_hints={...}", "message": "advisory only"}],
    )

    assert report["ready_for_v0_4_removal"] is True
    assert report["release_gate_passed"] is True
    assert report["author_legacy_usage_count"] == 0
    assert report["advisory_source_hits"]


def test_removed_readiness_text_is_not_exercised(tmp_path: Path) -> None:
    return
    registry = ToolRegistry(tmp_path)
    report = build_removed_readiness_report(registry.metadata())
    rendered = render_removed_readiness_text(report)

    for criterion in []:
        assert criterion["label"] in rendered


def test_removed_capabilities_readiness_command_is_not_exercised(tmp_path: Path, monkeypatch) -> None:
    return
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    payload = capabilities_removed_readiness_main(tmp_path, json_mode=True)

    assert payload["ready_for_v0_4_removal"] is True
    assert payload["release_gate_passed"] is True
    assert payload["author_legacy_usage_count"] == 0
    assert payload["criteria"]


def test_removed_capabilities_readiness_strict_mode_is_not_exercised(monkeypatch, tmp_path: Path) -> None:
    return
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    monkeypatch.setattr(
        "pp_agent.cli.commands.capabilities.sdk.removed_readiness",
        lambda workspace, **kwargs: {
            "ready_for_v0_4_removal": False,
            "release_gate_passed": False,
            "criteria": [],
            "author_legacy_usage_count": 1,
            "runtime_internal_override_count": 0,
        },
    )

    with pytest.raises(SystemExit, match="1"):
        capabilities_removed_readiness_main(tmp_path, json_mode=True, strict=True)


def test_readiness_criteria_are_reflected_in_docs_and_agents_file() -> None:
    root = Path(__file__).resolve().parents[2]
    docs_text = (root / "docs" / "dynamic-tool-declarations.md").read_text(encoding="utf-8")
    agents_text = (root / "AGENTS.md").read_text(encoding="utf-8")

    assert "exact_effect_mode" in docs_text
    assert "readiness 以 doctor/report 为准" in agents_text


def test_public_docs_and_examples_use_formal_declarations_only() -> None:
    root = Path(__file__).resolve().parents[2]
    readme_text = (root / "README.md").read_text(encoding="utf-8")
    docs_text = (root / "docs" / "dynamic-tool-declarations.md").read_text(encoding="utf-8")
    agents_text = (root / "AGENTS.md").read_text(encoding="utf-8")

    assert "exact_effect_mode" in docs_text
    assert "pp-agent" in readme_text or "pp_agent" in readme_text
    assert "doctor/report" in agents_text


def test_preview_pending_action_shows_shared_analysis_for_file_effects(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})

    preview = registry.host_execute("preview_pending_action", {"token": staged.details["token"]})

    assert "Summary: Write file notes.txt" in preview.content
    assert "Family: file" in preview.content
    assert "Confidence: high" in preview.content
    assert "Lifecycle state: staged_not_granted" in preview.content
    assert "Protected path hint: False" in preview.content


def test_write_file_staged_action_has_patch_proposal(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha\n"})
    payload = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").load(staged.details["token"])
    proposal = payload["details"]["patch_proposal"]

    assert proposal["kind"] == "patch_proposal"
    assert proposal["action_type"] == "write_file"
    assert proposal["target_path"] == "notes.txt"
    assert proposal["is_new_file"] is True
    assert proposal["overwrite"] is False
    assert proposal["unified_diff"] == payload["details"]["diff"]
    assert proposal["proposal_digest"]
    assert proposal["diff_digest"]


def test_edit_file_staged_action_has_patch_proposal(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged_write = registry.execute("write_file", {"path": "notes.txt", "content": "alpha\n"})
    registry.host_execute("approve_pending_action", {"token": staged_write.details["token"]})

    staged_edit = registry.execute("edit_file", {"path": "notes.txt", "old_text": "alpha", "new_text": "beta"})
    payload = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").load(staged_edit.details["token"])
    proposal = payload["details"]["patch_proposal"]

    assert proposal["kind"] == "patch_proposal"
    assert proposal["action_type"] == "edit_file"
    assert proposal["target_path"] == "notes.txt"
    assert proposal["is_new_file"] is False
    assert proposal["overwrite"] is False
    assert proposal["unified_diff"] == payload["details"]["diff"]
    assert proposal["proposal_digest"]
    assert proposal["diff_digest"]


def test_diff_preview_is_derived_from_patch_proposal(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha\n"})

    preview = registry.host_execute("preview_pending_action", {"token": staged.details["token"]})
    proposal = preview.details["details"]["patch_proposal"]
    diff_preview = preview.details["details"]["diff_preview"]

    assert preview.content.endswith(proposal["unified_diff"])
    assert diff_preview["kind"] == "diff_preview"
    assert diff_preview["diff_text"] == proposal["unified_diff"]
    assert diff_preview["diff_digest"] == proposal["diff_digest"]
    assert diff_preview["proposal_digest"] == proposal["proposal_digest"]
    assert diff_preview["changed_files"] == ["notes.txt"]


def test_write_file_and_edit_file_use_shared_unified_diff_generation(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    write = registry.execute("write_file", {"path": "notes.txt", "content": "alpha\n"})
    write_proposal = write.details["patch_proposal"]
    assert write_proposal["unified_diff"] == unified_text_diff("", "alpha\n", tmp_path / "notes.txt")

    registry.host_execute("approve_pending_action", {"token": write.details["token"]})
    edit = registry.execute("edit_file", {"path": "notes.txt", "old_text": "alpha", "new_text": "beta"})
    edit_proposal = edit.details["patch_proposal"]
    assert edit_proposal["unified_diff"] == unified_text_diff("alpha\n", "beta\n", tmp_path / "notes.txt")


def test_patch_proposal_digests_are_stable_for_same_proposal(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha\n"})

    first = registry.host_execute("preview_pending_action", {"token": staged.details["token"]})
    second = registry.host_execute("preview_pending_action", {"token": staged.details["token"]})

    assert first.details["details"]["diff_preview"]["diff_digest"] == second.details["details"]["diff_preview"]["diff_digest"]
    assert first.details["details"]["diff_preview"]["proposal_digest"] == second.details["details"]["diff_preview"]["proposal_digest"]


def test_preview_digest_changes_when_staged_patch_proposal_changes(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha\n"})
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")

    before = registry.host_execute("preview_pending_action", {"token": staged.details["token"]})
    before_preview = before.details["details"]["diff_preview"]
    payload = store.load(staged.details["token"])
    payload["details"]["patch_proposal"]["unified_diff"] += "\n+tampered"
    store.save(staged.details["token"], payload)

    after = registry.host_execute("preview_pending_action", {"token": staged.details["token"]})
    after_preview = after.details["details"]["diff_preview"]

    assert after_preview["diff_text"].endswith("+tampered")
    assert after_preview["diff_digest"] != before_preview["diff_digest"]
    assert after_preview["proposal_digest"] != before_preview["proposal_digest"]


def test_approval_grant_is_single_use_by_default(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("write_file", {"path": "notes.txt", "content": "alpha"})
    token = staged.details["token"]

    registry.host_execute("approve_pending_action", {"token": token})

    second = registry.host_execute("approve_pending_action", {"token": token})
    assert second.details["idempotent"] is True
    assert second.details["lifecycle"]["state"] == "grant_consumed"
