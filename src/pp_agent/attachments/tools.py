from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pp_agent.attachments.service import AttachmentService
from pp_agent.domain import ToolSpec
from pp_agent.tools.base import BaseTool, ToolExecutionResult
from pp_agent.tools.policy import PermissionDomain, ToolPolicyEvaluator


class AttachmentBaseTool(BaseTool):
    """附件工具基类，负责绑定 workspace、session_id 和 AttachmentService。"""

    tool_name = "attachment"
    description = ""
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(self, workspace: Path, policy_evaluator: ToolPolicyEvaluator | None = None, *, current_session_id: str | None = None, observability: Any | None = None) -> None:
        super().__init__(workspace, policy_evaluator)
        self.current_session_id = current_session_id
        self.service = AttachmentService(self.workspace, observability=observability)

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_name,
            description=self.description,
            parameters=self.parameters,
            permission_domain=PermissionDomain.READ,
        )

    def _session_id(self, arguments: dict[str, Any]) -> str:
        session_id = str(arguments.get("session_id") or self.current_session_id or "").strip()
        if not session_id:
            raise ValueError("session_id is required")
        return session_id

    def _result(self, payload: dict[str, Any]) -> ToolExecutionResult:
        return ToolExecutionResult(tool_call_id="", tool_name=self.tool_name, content=json.dumps(payload, ensure_ascii=False), details=payload)


class ListAttachmentsTool(AttachmentBaseTool):
    """列出当前 session 的附件摘要，供 Agent 决定下一步 inspect 或 search。"""

    tool_name = "list_attachments"
    description = "List uploaded attachments for the current session. Returns metadata and previews only, not full file contents."
    parameters = {
        "type": "object",
        "properties": {"session_id": {"type": "string", "description": "Optional session id; defaults to current session."}},
    }

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        session_id = self._session_id(arguments)
        attachments = [AttachmentService._public_record(record) for record in self.service.list(session_id)]
        return self._result({"attachments": attachments})


class InspectAttachmentTool(AttachmentBaseTool):
    """查看附件类型、状态、chunk 数、outline、表格 schema 或结构摘要。"""

    tool_name = "inspect_attachment"
    description = "Inspect one attachment summary, outline, schema, page count, or structure metadata before reading content."
    parameters = {
        "type": "object",
        "properties": {"session_id": {"type": "string"}, "attachment_id": {"type": "string"}},
        "required": ["attachment_id"],
    }

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        return self._result(self.service.inspect(self._session_id(arguments), str(arguments["attachment_id"])))


class SearchAttachmentTool(AttachmentBaseTool):
    """在 session 附件中做关键词检索，返回相关 chunk 和短片段。"""

    tool_name = "search_attachment"
    description = "Search one or all current-session attachments with lightweight keyword retrieval and return matching chunks."
    parameters = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "query": {"type": "string"},
            "attachment_id": {"type": "string"},
            "top_k": {"type": "integer"},
            "mode": {"type": "string", "enum": ["auto", "keyword", "hybrid"]},
        },
        "required": ["query"],
    }

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        payload = {
            "results": self.service.search(
                self._session_id(arguments),
                str(arguments["query"]),
                attachment_id=str(arguments.get("attachment_id") or "").strip() or None,
                top_k=int(arguments.get("top_k") or 5),
                mode=str(arguments.get("mode") or "auto"),
            )
        }
        return self._result(payload)


class ReadAttachmentChunkTool(AttachmentBaseTool):
    """读取指定 chunk 的完整文本，但仍按安全上限截断超长内容。"""

    tool_name = "read_attachment_chunk"
    description = "Read a specific attachment chunk by chunk_id. Use after search_attachment or inspect_attachment."
    parameters = {
        "type": "object",
        "properties": {"session_id": {"type": "string"}, "chunk_id": {"type": "string"}},
        "required": ["chunk_id"],
    }

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        return self._result(self.service.read_chunk(self._session_id(arguments), str(arguments["chunk_id"])))


class ReadAttachmentTextTool(AttachmentBaseTool):
    """Read extracted text from a PDF/DOCX/text-like attachment by offset."""

    tool_name = "read_attachment_text"
    description = "Read extracted attachment text by character offset. Use this for full-document PDF/DOCX/text questions; continue with next_offset until truncated is false."
    parameters = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "attachment_id": {"type": "string"},
            "offset": {"type": "integer"},
            "max_chars": {"type": "integer"},
        },
        "required": ["attachment_id"],
    }

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        return self._result(
            self.service.read_text(
                self._session_id(arguments),
                str(arguments["attachment_id"]),
                offset=int(arguments.get("offset") or 0),
                max_chars=int(arguments.get("max_chars") or 30000),
            )
        )


class ReadAttachmentRangeTool(AttachmentBaseTool):
    """按行读取代码、日志或文本附件，避免一次性读取完整文件。"""

    tool_name = "read_attachment_range"
    description = "Read a line range from a text, log, or code attachment. Prefer this for code files after inspecting outline."
    parameters = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "attachment_id": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        "required": ["attachment_id", "start_line", "end_line"],
    }

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        return self._result(
            self.service.read_range(
                self._session_id(arguments),
                str(arguments["attachment_id"]),
                int(arguments["start_line"]),
                int(arguments["end_line"]),
            )
        )


class SearchAttachmentSymbolsTool(AttachmentBaseTool):
    """搜索代码附件中的 class、function、method 等 symbol metadata。"""

    tool_name = "search_attachment_symbols"
    description = "Search code symbols in current-session code attachments by name, signature, parent, or docstring preview."
    parameters = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "query": {"type": "string"},
            "attachment_id": {"type": "string"},
            "top_k": {"type": "integer"},
        },
        "required": ["query"],
    }

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        return self._result(
            {
                "symbols": self.service.search_symbols(
                    self._session_id(arguments),
                    str(arguments["query"]),
                    attachment_id=str(arguments.get("attachment_id") or "").strip() or None,
                    top_k=int(arguments.get("top_k") or 10),
                )
            }
        )


class ReadAttachmentSymbolTool(AttachmentBaseTool):
    """按 symbol_id 读取局部代码，避免把完整代码附件塞进 prompt。"""

    tool_name = "read_attachment_symbol"
    description = "Read a code symbol by symbol_id after search_attachment_symbols or inspect_attachment."
    parameters = {
        "type": "object",
        "properties": {"session_id": {"type": "string"}, "attachment_id": {"type": "string"}, "symbol_id": {"type": "string"}},
        "required": ["attachment_id", "symbol_id"],
    }

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        return self._result(self.service.read_symbol(self._session_id(arguments), str(arguments["attachment_id"]), str(arguments["symbol_id"])))
