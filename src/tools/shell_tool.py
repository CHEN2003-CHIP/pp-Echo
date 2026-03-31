from __future__ import annotations

import subprocess
from typing import Any

from agent_core.types import ToolSpec
from tools.base import BaseTool, ToolExecutionResult
from tools.pending_actions import PendingActionStore


class PowerShellTool(BaseTool):
    def __init__(self, workspace, default_timeout_seconds: int = 30) -> None:
        super().__init__(workspace)
        self.default_timeout_seconds = default_timeout_seconds

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="run_shell",
            description="Stage a PowerShell command for approval by default. Set apply=true to run immediately after confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                    "apply": {"type": "boolean"},
                },
                "required": ["command"],
            },
            requires_confirmation=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        timeout = int(arguments.get("timeout_seconds", self.default_timeout_seconds))
        apply_now = bool(arguments.get("apply", False))
        command = arguments["command"]
        if not apply_now:
            store = PendingActionStore(self.pending_root())
            payload = store.stage(action_type="run_shell", command=command, details={"timeout_seconds": timeout})
            return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=f"Staged shell command. Approve with token {payload['token']}", details={"token": payload["token"], "command": command, "timeout_seconds": timeout, "staged": True})
        return self._run(command, timeout)

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