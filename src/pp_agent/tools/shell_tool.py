from __future__ import annotations

from pathlib import Path
from typing import Any
from importlib import import_module

from pp_agent.domain import ToolSpec
from pp_agent.sandbox.base import SandboxExecutor, SandboxRunRequest, SandboxRunResult
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.tools.base import BaseTool, ToolExecutionResult
from pp_agent.tools.effects import build_shell_effect
from pp_agent.tools.policy import PermissionDomain


def default_local_sandbox_executor() -> SandboxExecutor:
    """Resolve the compatibility local executor without importing backend modules at tools import time."""

    return import_module("pp_agent.sandbox.local").LocalSandboxExecutor()


def shell_output(result: SandboxRunResult) -> str:
    """Combine stdout and stderr the same way the legacy PowerShell tool did."""

    return (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")


def sandbox_result_error(result: SandboxRunResult, *, stream_labels: bool = True) -> Exception:
    """Render sandbox process failures in the existing shell failure format."""

    if result.timed_out:
        return TimeoutError(f"PowerShell timed out after sandbox execution with code {result.returncode}")
    if not stream_labels:
        return RuntimeError(f"PowerShell exited with code {result.returncode}\n{shell_output(result)}".strip())
    return RuntimeError(
        "PowerShell exited with code "
        f"{result.returncode}\n"
        f"stdout:\n{result.stdout or ''}\n"
        f"stderr:\n{result.stderr or ''}".strip()
    )


def sandbox_result_details(result: SandboxRunResult) -> dict[str, Any]:
    """Return optional sandbox metadata that is safe to expose in tool details."""

    details: dict[str, Any] = {
        "sandbox_backend": result.backend,
        "sandbox_mode": result.sandbox_mode,
        "network_access": result.network_access,
        "network_allowlist": result.network_allowlist or [],
        "network_policy_mode": result.network_policy_mode,
        "network_enforced": result.network_enforced,
        "writable_roots": result.writable_roots,
        "sandbox_isolation": "none-local-compat" if result.backend == "local" else result.sandbox_mode,
    }
    if result.changed_files is not None:
        details["changed_files"] = result.changed_files
    if result.patch_summary is not None:
        details["patch_summary"] = result.patch_summary
    if result.patch is not None:
        details["patch"] = result.patch
    if result.changed_files is not None or result.patch_summary is not None or result.patch is not None:
        details["patch_truncated"] = result.patch_truncated
    if result.structured_changes is not None:
        details["structured_changes"] = result.structured_changes
        details["structured_changes_count"] = len(result.structured_changes)
    if result.structured_changes_digest is not None:
        details["structured_changes_digest"] = result.structured_changes_digest
    if result.structured_changes is not None or result.structured_changes_digest is not None:
        details["structured_changes_truncated"] = result.structured_changes_truncated
    return details


class PowerShellTool(BaseTool):
    def __init__(
        self,
        workspace,
        policy_evaluator=None,
        default_timeout_seconds: int = 30,
        sandbox_executor: SandboxExecutor | None = None,
    ) -> None:
        super().__init__(workspace, policy_evaluator=policy_evaluator)
        self.default_timeout_seconds = default_timeout_seconds
        self.sandbox_executor = sandbox_executor or default_local_sandbox_executor()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="run_shell",
            description="Stage a PowerShell command for host-side approval.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                },
                "required": ["command"],
            },
            requires_confirmation=True,
            permission_domain=PermissionDomain.BASH,
            sensitive=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        timeout = int(arguments.get("timeout_seconds", self.default_timeout_seconds))
        command = arguments["command"]
        self.enforce_policy_for_command(PermissionDomain.BASH, command)
        store = PendingActionStore(self.pending_root())
        effect = build_shell_effect(
            tool_name=self.spec.name,
            permission_domain=PermissionDomain.BASH,
            command=command,
            timeout_seconds=timeout,
            workspace=self.workspace,
        )
        payload = store.stage(
            action_type="run_shell",
            command=command,
            details={"timeout_seconds": timeout},
            effect=effect,
            origin={"source": "tool", "tool_name": self.spec.name, "kind": "shell"},
        )
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=f"Staged shell command. Approve with token {payload['token']}",
            details={"token": payload["token"], "command": command, "timeout_seconds": timeout, "staged": True, "effect": effect},
        )

    def _run(self, command: str, timeout: int) -> ToolExecutionResult:
        completed = self.sandbox_executor.run(
            SandboxRunRequest(command=command, cwd=Path(self.workspace), timeout_seconds=timeout)
        )
        output = shell_output(completed)
        if completed.returncode != 0:
            raise sandbox_result_error(completed, stream_labels=False)
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=output.strip() or "[no output]",
            details={
                "timeout_seconds": timeout,
                "returncode": completed.returncode,
                "command": command,
                **sandbox_result_details(completed),
            },
        )


class ApprovePendingShellTool(BaseTool):
    def __init__(self, workspace, default_timeout_seconds: int = 30, sandbox_executor: SandboxExecutor | None = None) -> None:
        super().__init__(workspace)
        self.default_timeout_seconds = default_timeout_seconds
        self.sandbox_executor = sandbox_executor or default_local_sandbox_executor()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="approve_pending_shell",
            description="Approve and run a staged shell command by token.",
            parameters={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]},
            requires_confirmation=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        store = PendingActionStore(self.pending_root())
        payload = store.load(arguments["token"])
        if payload["action_type"] != "run_shell":
            raise ValueError(f"Pending action {arguments['token']} is not a shell action")
        timeout = int(payload["details"].get("timeout_seconds", self.default_timeout_seconds))
        result = PowerShellTool(self.workspace, default_timeout_seconds=timeout, sandbox_executor=self.sandbox_executor)._run(payload["command"], timeout)
        store.remove(arguments["token"])
        result.tool_name = self.spec.name
        result.details["token"] = arguments["token"]
        return result
