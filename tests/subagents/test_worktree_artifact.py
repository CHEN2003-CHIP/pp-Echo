from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pp_agent.storage.approvals import PendingActionStore
from pp_agent.subagents.capabilities import SubAgentProfile, ToolCapabilityPolicy, WorkspacePolicy
from pp_agent.subagents.worktree import WorktreeManager
from pp_agent.tools.base import ToolExecutionResult
from pp_agent.tools.file_tools import MAX_EDIT_FILE_BYTES
from pp_agent.tools.policy import PermissionDomain
from pp_agent.tools.registry import ToolRegistry
from pp_agent.tools.shell_tool import SHELL_OUTPUT_PREVIEW_MAX_CHARS


def _git(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=workspace, capture_output=True, text=True, check=False)


def _init_repo(workspace: Path) -> None:
    _git(workspace, "init")
    _git(workspace, "config", "user.name", "pp-agent-test")
    _git(workspace, "config", "user.email", "pp-agent-test@example.invalid")
    (workspace / "demo.txt").write_text("one\n", encoding="utf-8")
    _git(workspace, "add", "demo.txt")
    _git(workspace, "commit", "-m", "init")


def _worktree_profile(*, allow_dynamic: bool = False) -> SubAgentProfile:
    return SubAgentProfile(
        name="code-worker",
        tool=ToolCapabilityPolicy(
            allowlist=["read_file", "write_file", "edit_file", "run_shell", "local.write"],
            allow_dynamic_tools=allow_dynamic,
        ),
        workspace=WorkspacePolicy(mode="worktree", allow_write_tools=True),
    )


def test_worktree_write_file_produces_patch_artifact_and_parent_approve_applies(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "demo.txt").write_text("parent\n", encoding="utf-8")
    manager = WorktreeManager(tmp_path)
    handle = manager.create(run_id="run1", agent="code-worker", node_id="code_patch", attempt=1)
    registry = ToolRegistry(Path(handle.worktree_path), capability_profile=_worktree_profile())

    result = registry.execute("write_file", {"path": "demo.txt", "content": "child\n", "overwrite": True})
    assert result.details["patch_artifact_pending"] is True
    assert (tmp_path / "demo.txt").read_text(encoding="utf-8") == "parent\n"

    artifact = manager.finalize(handle)
    assert artifact is not None
    assert artifact.changed_paths == ["demo.txt"]
    patch_text = Path(artifact.patch_path).read_text(encoding="utf-8")
    assert "-parent" in patch_text
    assert "+child" in patch_text
    assert "-one" not in patch_text

    payload = manager.stage_pending_artifact(
        artifact,
        tmp_path / ".pp-agent" / "pending-edits",
        session_id="parent-session-1",
        workflow="code_change",
    )
    assert payload["details"]["session_id"] == "parent-session-1"
    assert payload["details"]["workflow"] == "code_change"
    assert payload["details"]["artifact_id"] == artifact.artifact_id
    approval = ToolRegistry(tmp_path).host_execute("approve_pending_action", {"token": payload["token"]})
    assert approval.is_error is False
    assert (tmp_path / "demo.txt").read_text(encoding="utf-8") == "child\n"


def test_worktree_write_file_reuses_safe_edit_guard(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    manager = WorktreeManager(tmp_path)
    handle = manager.create(run_id="run-guard", agent="code-worker", node_id="code_patch", attempt=1)
    registry = ToolRegistry(Path(handle.worktree_path), capability_profile=_worktree_profile())

    with pytest.raises(ValueError, match="large content"):
        registry.execute("write_file", {"path": "large.txt", "content": "x" * (MAX_EDIT_FILE_BYTES + 1)})

    assert not (Path(handle.worktree_path) / "large.txt").exists()


def test_worktree_shell_denies_network_and_allows_workspace_local_patch(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    manager = WorktreeManager(tmp_path)
    handle = manager.create(run_id="run2", agent="code-worker", node_id="code_patch", attempt=1)
    registry = ToolRegistry(Path(handle.worktree_path), capability_profile=_worktree_profile())

    with pytest.raises(PermissionError):
        registry.execute("run_shell", {"command": "curl https://example.com", "timeout_seconds": 5})

    registry.execute("run_shell", {"command": "Set-Content -Path shell.txt -Value hello", "timeout_seconds": 5})
    artifact = manager.finalize(handle)
    assert artifact is not None
    assert "shell.txt" in artifact.changed_paths
    assert not (tmp_path / "shell.txt").exists()


def test_worktree_shell_result_uses_bounded_contract(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    manager = WorktreeManager(tmp_path)
    handle = manager.create(run_id="run-shell-result", agent="code-worker", node_id="code_patch", attempt=1)
    registry = ToolRegistry(Path(handle.worktree_path), capability_profile=_worktree_profile())
    tail = "SECRET_WORKTREE_STDOUT_TAIL_SHOULD_NOT_TRACE"
    command = f"$x = 'A' * {SHELL_OUTPUT_PREVIEW_MAX_CHARS + 100}; Set-Content -Path shell.txt -Value hello; Write-Output ($x + '{tail}')"

    result = registry.execute("run_shell", {"command": command, "timeout_seconds": 5})

    assert result.details["backend"] == "worktree-local"
    assert result.details["sandbox_backend"] == "worktree-local"
    assert result.details["sandbox_mode"] == "worktree"
    assert result.details["timed_out"] is False
    assert result.details["returncode"] == 0
    assert result.details["stdout_truncated"] is True
    assert result.details["stdout_chars"] > SHELL_OUTPUT_PREVIEW_MAX_CHARS
    assert tail not in result.details["stdout"]
    assert tail not in result.content


def test_worktree_dynamic_workspace_tool_executes_in_isolation(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    manager = WorktreeManager(tmp_path)
    handle = manager.create(run_id="run3", agent="code-worker", node_id="code_patch", attempt=1)
    registry = ToolRegistry(Path(handle.worktree_path), capability_profile=_worktree_profile(allow_dynamic=True))

    def write_local(workspace: Path, arguments: dict) -> ToolExecutionResult:
        (workspace / arguments["path"]).write_text(arguments["content"], encoding="utf-8")
        return ToolExecutionResult(tool_call_id="", tool_name="local.write", content="ok")

    registry.register_function_tool(
        name="local.write",
        description="Write a local workspace file.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
        executor=write_local,
        category="extension",
        permission_domain=PermissionDomain.EDIT,
        tool_family="extension",
        exact_effect_mode="required",
        replace=True,
    )

    registry.execute("local.write", {"path": "dynamic.txt", "content": "from dynamic\n"})
    artifact = manager.finalize(handle)
    assert artifact is not None
    assert "dynamic.txt" in artifact.changed_paths
    assert not (tmp_path / "dynamic.txt").exists()


def test_reject_patch_artifact_marks_token_without_deleting_artifact(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    manager = WorktreeManager(tmp_path)
    handle = manager.create(run_id="run4", agent="code-worker", node_id="code_patch", attempt=1)
    ToolRegistry(Path(handle.worktree_path), capability_profile=_worktree_profile()).execute(
        "write_file",
        {"path": "demo.txt", "content": "child\n", "overwrite": True},
    )
    artifact = manager.finalize(handle)
    assert artifact is not None
    payload = manager.stage_pending_artifact(artifact, tmp_path / ".pp-agent" / "pending-edits")

    ToolRegistry(tmp_path).host_execute("reject_pending_action", {"token": payload["token"]})

    stored = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").load(payload["token"])
    assert stored["lifecycle"]["state"] == "rejected"
    assert Path(artifact.patch_path).exists()


def test_worktree_patch_artifact_approval_applies_single_line_file_to_parent_workspace(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    manager = WorktreeManager(tmp_path)
    handle = manager.create(run_id="run5", agent="code-worker", node_id="code_patch", attempt=1)
    registry = ToolRegistry(Path(handle.worktree_path), capability_profile=_worktree_profile())

    registry.execute(
        "write_file",
        {"path": "docs/worktree-smoke-web.md", "content": "pp-Echo isolated worktree smoke test\n", "overwrite": True},
    )
    artifact = manager.finalize(handle)
    assert artifact is not None

    payload = manager.stage_pending_artifact(
        artifact,
        tmp_path / ".pp-agent" / "pending-edits",
        session_id="parent-session-1",
        workflow="code_change",
    )
    approval = ToolRegistry(tmp_path).host_execute("approve_pending_action", {"token": payload["token"]})

    assert approval.is_error is False
    assert (tmp_path / "docs" / "worktree-smoke-web.md").read_text(encoding="utf-8") == "pp-Echo isolated worktree smoke test\n"
