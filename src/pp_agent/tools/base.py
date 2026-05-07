from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pp_agent.domain import ChatMessage, TextPart, ToolCall, ToolResult, ToolSpec
from pp_agent.tools.effects import analyze_file_call, build_shell_effect
from pp_agent.tools.policy import ALLOW, ToolPolicyEvaluator


class ToolExecutionResult(ToolResult):
    """工具执行结果"""
    def as_chat_message(self) -> ChatMessage:
        return ChatMessage(
            role="tool",
            tool_call_id=self.tool_call_id,
            tool_name=self.tool_name,
            content=[TextPart(text=self.content)],
            metadata={"tool_details": dict(self.details), "is_error": self.is_error},
            timestamp=time.time(),
        )


class BaseTool(ABC):
    """工具接口定义"""
    def __init__(self, workspace: Path, policy_evaluator: ToolPolicyEvaluator | None = None) -> None:
        self.workspace = workspace.resolve()
        self.policy_evaluator = policy_evaluator or ToolPolicyEvaluator(self.workspace)

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        raise NotImplementedError

    @abstractmethod
    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        raise NotImplementedError

    def resolve_path(self, raw_path: str) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.workspace / path
        resolved = path.resolve()
        return resolved

    def enforce_policy_for_path(self, permission_domain: str, raw_path: str) -> Path:
        resolved = self.resolve_path(raw_path)
        analysis = analyze_file_call(
            workspace=self.workspace,
            tool_name=self.spec.name,
            permission_domain=permission_domain,
            target_path=resolved,
        )
        decision = self.policy_evaluator.evaluate(permission_domain=permission_domain, target_path=resolved, analysis=analysis)
        if decision.action != ALLOW and permission_domain == "read":
            raise PermissionError(decision.reason)
        if decision.action == "deny":
            raise PermissionError(decision.reason)
        return resolved

    def enforce_policy_for_command(self, permission_domain: str, command: str) -> None:
        shell_effect = build_shell_effect(
            tool_name="run_shell",
            permission_domain=permission_domain,
            command=command,
            timeout_seconds=30,
            workspace=self.workspace,
        )
        decision = self.policy_evaluator.evaluate(permission_domain=permission_domain, command=command, analysis=shell_effect["analysis"])
        if decision.action == "deny":
            raise PermissionError(decision.reason)

    def pending_root(self) -> Path:
        """获取待处理文件的根目录"""
        root = self.workspace / ".pp-agent" / "pending-edits"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def error_result(self, call: ToolCall, message: str) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_call_id=call.id,
            tool_name=call.name,
            content=message,
            is_error=True,
            details={"error": message},
        )
