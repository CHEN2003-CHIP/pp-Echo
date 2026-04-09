from __future__ import annotations

import subprocess
from typing import Any

from pp_agent.domain import ToolSpec
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.tools.base import BaseTool, ToolExecutionResult
from pp_agent.tools.effects import build_shell_effect
from pp_agent.tools.policy import PermissionDomain


class PowerShellTool(BaseTool):
    def __init__(self, workspace, policy_evaluator=None, default_timeout_seconds: int = 30) -> None:
        super().__init__(workspace, policy_evaluator=policy_evaluator)
        self.default_timeout_seconds = default_timeout_seconds

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
        payload = store.stage(action_type="run_shell", command=command, details={"timeout_seconds": timeout}, effect=effect)
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=f"Staged shell command. Approve with token {payload['token']}",
            details={"token": payload["token"], "command": command, "timeout_seconds": timeout, "staged": True, "effect": effect},
        )

    def _run(self, command: str, timeout: int) -> ToolExecutionResult:
        completed = subprocess.run([
                "powershell.exe",
                "-NoProfile",
                "-Command",
                command,
            ], cwd=str(self.workspace), capture_output=True, text=True, timeout=timeout, check=False)
        output = (completed.stdout or "") + (("\n" + completed.stderr) if completed.stderr else "")
        if completed.returncode != 0:
            raise RuntimeError(f"PowerShell exited with code {completed.returncode}\n{output}".strip())
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=output.strip() or "[no output]", details={"timeout_seconds": timeout, "returncode": completed.returncode, "command": command})


class ApprovePendingShellTool(BaseTool):
    def __init__(self, workspace, default_timeout_seconds: int = 30) -> None:
        super().__init__(workspace)
        self.default_timeout_seconds = default_timeout_seconds

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
        result = PowerShellTool(self.workspace, default_timeout_seconds=timeout)._run(payload["command"], timeout)
        store.remove(arguments["token"])
        result.tool_name = self.spec.name
        result.details["token"] = arguments["token"]
        return result
