from __future__ import annotations

from typing import Any

from agent_core.types import ToolSpec
from tools.base import BaseTool, ToolExecutionResult


class SearchTextTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="search_text",
            description="Search for text inside files under the workspace.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}, "path": {"type": "string"}},
                "required": ["query"],
            },
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        query = arguments["query"]
        root = self.resolve_path(arguments.get("path", "."))
        matches: list[str] = []
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            try:
                for line_number, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
                    if query in line:
                        matches.append(f"{file_path.relative_to(self.workspace)}:{line_number}: {line}")
            except UnicodeDecodeError:
                continue
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content="\n".join(matches) if matches else "No matches found.",
            details={"path": str(root), "matches": len(matches), "query": query},
        )