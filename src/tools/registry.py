from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from agent_core.types import ToolCall, ToolSpec
from storage.settings import ToolPolicyConfig
from tools.base import BaseTool, ToolExecutionResult
from tools.file_tools import ApprovePendingActionTool, EditFileTool, ListFilesTool, ListPendingActionsTool, PreviewPendingActionTool, ReadFileTool, RejectPendingActionTool, WriteFileTool
from tools.repo_tools import GitDiffWorktreeTool, GitStatusTool, GrepCodeTool
from tools.search_tool import SearchTextTool
from tools.shell_tool import PowerShellTool


class ToolRegistry:
    def __init__(self, workspace: Path, policy: Optional[ToolPolicyConfig] = None) -> None:
        self.workspace = workspace.resolve()
        self.policy = policy or ToolPolicyConfig()
        self._tools: dict[str, BaseTool] = {}
        self._confirmation_overrides = {
            "write_file": self.policy.confirm_write_file,
            "edit_file": self.policy.confirm_edit_file,
            "approve_pending_action": True,
            "reject_pending_action": True,
            "run_shell": self.policy.confirm_run_shell,
        }

        tools = [
            ReadFileTool(self.workspace),
            WriteFileTool(self.workspace),
            EditFileTool(self.workspace),
            PreviewPendingActionTool(self.workspace),
            ApprovePendingActionTool(self.workspace),
            RejectPendingActionTool(self.workspace),
            ListPendingActionsTool(self.workspace),
            ListFilesTool(self.workspace),
            SearchTextTool(self.workspace),
            GrepCodeTool(self.workspace),
            GitStatusTool(self.workspace),
            GitDiffWorktreeTool(self.workspace),
            PowerShellTool(self.workspace, default_timeout_seconds=self.policy.shell_timeout_seconds),
        ]
        for tool in tools:
            self._tools[tool.spec.name] = tool

    def get_spec(self, name: str) -> ToolSpec:
        spec = self._tools[name].spec.model_copy(deep=True)
        if name in self._confirmation_overrides:
            spec.requires_confirmation = self._confirmation_overrides[name]
        return spec

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        result = self._tools[name].execute(arguments)
        result.tool_name = name
        return result

    def error_result(self, call: ToolCall, message: str) -> ToolExecutionResult:
        return self._tools[call.name].error_result(call, message)

    def openapi_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": self.get_spec(name).name,
                    "description": self.get_spec(name).description,
                    "parameters": self.get_spec(name).parameters,
                },
            }
            for name in self._tools
        ]