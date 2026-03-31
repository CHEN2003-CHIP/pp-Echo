from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from agent_core.types import ChatMessage, TextPart, ToolCall, ToolResult, ToolSpec


class ToolExecutionResult(ToolResult):
    def as_chat_message(self) -> ChatMessage:
        return ChatMessage(
            role="tool",
            tool_call_id=self.tool_call_id,
            tool_name=self.tool_name,
            content=[TextPart(text=self.content)],
            timestamp=time.time(),
        )


class BaseTool(ABC):
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

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
        if self.workspace not in [resolved, *resolved.parents]:
            raise PermissionError(f"Path is outside workspace: {resolved}")
        return resolved

    def pending_root(self) -> Path:
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