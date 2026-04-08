from __future__ import annotations

import difflib
import re
import subprocess
from pathlib import Path
from typing import Any

from pp_agent.domain import ToolSpec
from pp_agent.tools.base import BaseTool, ToolExecutionResult
from pp_agent.storage.approvals import PendingActionStore

SEARCH_BLOCK_RE = re.compile(
    r"<<<<<<< SEARCH\n(?P<old>.*?)\n=======\n(?P<new>.*?)\n>>>>>>> REPLACE",
    re.DOTALL,
)
UNIFIED_HUNK_RE = re.compile(r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@")


class ReadFileTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="read_file", description="Read the contents of a UTF-8 text file.", parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        path = self.resolve_path(arguments["path"])
        content = path.read_text(encoding="utf-8")
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=content, details={"path": str(path), "size": len(content)})


class WriteFileTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="write_file", description="Stage a new file write by default. Set apply=true to write immediately after confirmation.", parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}, "overwrite": {"type": "boolean"}, "apply": {"type": "boolean"}}, "required": ["path", "content"]}, requires_confirmation=True)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        path = self.resolve_path(arguments["path"])
        overwrite = bool(arguments.get("overwrite", False))
        apply_now = bool(arguments.get("apply", False))
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        if path.exists() and not overwrite:
            raise ValueError("File already exists. Re-run with overwrite=true after confirming the diff.")
        after = arguments["content"]
        diff = self._diff(before, after, path)
        if apply_now:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(after, encoding="utf-8")
            return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=f"Wrote {path}", details={"path": str(path), "bytes_written": len(after.encode('utf-8')), "created": not bool(before), "diff": diff})
        store = PendingActionStore(self.pending_root())
        payload = store.stage(action_type="write_file", target_path=path, before=before, after=after, details={"overwrite": overwrite, "diff": diff})
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=f"Staged write for {path}. Approve with token {payload['token']}", details={"path": str(path), "token": payload["token"], "diff": diff, "staged": True})

    @staticmethod
    def _diff(before: str, after: str, path: Path) -> str:
        return "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(), fromfile=f"a/{path.name}", tofile=f"b/{path.name}", lineterm=""))


class EditFileTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="edit_file", description="Stage a safe diff-style edit using SEARCH/REPLACE blocks or a unified diff. Set apply=true to apply immediately.", parameters={"type": "object", "properties": {"path": {"type": "string"}, "diff": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}, "apply": {"type": "boolean"}}, "required": ["path"]}, requires_confirmation=True)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        path = self.resolve_path(arguments["path"])
        original = path.read_text(encoding="utf-8")
        apply_now = bool(arguments.get("apply", False))
        if arguments.get("diff"):
            updated, replacements = self._apply_search_replace_diff(original, arguments["diff"])
        else:
            old_text = arguments.get("old_text")
            new_text = arguments.get("new_text")
            if old_text is None or new_text is None:
                raise ValueError("Provide either diff or old_text/new_text.")
            updated = original.replace(old_text, new_text, 1)
            if updated == original:
                raise ValueError("old_text was not found in file")
            replacements = 1
        diff = "\n".join(difflib.unified_diff(original.splitlines(), updated.splitlines(), fromfile=f"a/{path.name}", tofile=f"b/{path.name}", lineterm=""))
        if apply_now:
            path.write_text(updated, encoding="utf-8")
            return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=f"Edited {path}", details={"path": str(path), "replacements": replacements, "diff": diff, "staged": False})
        store = PendingActionStore(self.pending_root())
        payload = store.stage(action_type="edit_file", target_path=path, before=original, after=updated, details={"replacements": replacements, "diff": diff})
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=f"Staged edit for {path}. Approve with token {payload['token']}", details={"path": str(path), "replacements": replacements, "diff": diff, "token": payload["token"], "staged": True})

    @staticmethod
    def _apply_search_replace_diff(content: str, diff: str) -> tuple[str, int]:
        updated = content
        replacements = 0
        matches = list(SEARCH_BLOCK_RE.finditer(diff))
        if not matches:
            return EditFileTool._apply_unified_diff(content, diff)
        for match in matches:
            old = match.group("old")
            new = match.group("new")
            if old not in updated:
                raise ValueError(f"SEARCH block was not found exactly in file: {old[:80]}")
            updated = updated.replace(old, new, 1)
            replacements += 1
        return updated, replacements

    @staticmethod
    def _apply_unified_diff(content: str, diff: str) -> tuple[str, int]:
        diff_lines = diff.splitlines()
        original_lines = content.splitlines()
        updated_lines: list[str] = []
        cursor = 0
        replacements = 0
        line_index = 0
        saw_hunk = False

        while line_index < len(diff_lines):
            line = diff_lines[line_index]
            if line.startswith(("--- ", "+++ ", "diff --git ", "index ")):
                line_index += 1
                continue
            hunk_match = UNIFIED_HUNK_RE.match(line)
            if not hunk_match:
                line_index += 1
                continue

            saw_hunk = True
            old_start = int(hunk_match.group("old_start"))
            updated_lines.extend(original_lines[cursor : old_start - 1])
            cursor = old_start - 1
            line_index += 1
            changed = False

            while line_index < len(diff_lines):
                hunk_line = diff_lines[line_index]
                if UNIFIED_HUNK_RE.match(hunk_line):
                    break
                if hunk_line == r"\ No newline at end of file":
                    line_index += 1
                    continue
                if not hunk_line:
                    prefix = " "
                    text = ""
                else:
                    prefix = hunk_line[0]
                    text = hunk_line[1:]
                if prefix == " ":
                    if cursor >= len(original_lines) or original_lines[cursor] != text:
                        raise ValueError(f"Unified diff context did not match file near line {cursor + 1}")
                    updated_lines.append(text)
                    cursor += 1
                elif prefix == "-":
                    if cursor >= len(original_lines) or original_lines[cursor] != text:
                        raise ValueError(f"Unified diff deletion did not match file near line {cursor + 1}")
                    cursor += 1
                    changed = True
                elif prefix == "+":
                    updated_lines.append(text)
                    changed = True
                else:
                    raise ValueError(f"Unsupported unified diff line: {hunk_line}")
                line_index += 1

            if changed:
                replacements += 1

        if not saw_hunk:
            raise ValueError("diff must contain at least one SEARCH/REPLACE block or unified diff hunk")

        updated_lines.extend(original_lines[cursor:])
        updated = "\n".join(updated_lines)
        if content.endswith("\n"):
            updated += "\n"
        return updated, replacements


class PreviewPendingActionTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="preview_pending_action", description="Preview a staged action by token, including diff or command details.", parameters={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]})

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        store = PendingActionStore(self.pending_root())
        payload = store.load(arguments["token"])
        if payload["action_type"] == "run_shell":
            content = payload.get("command") or ""
        elif payload["action_type"] == "planner_approval":
            summary = payload.get("details", {}).get("summary", []) or []
            content = "\n".join(summary) or "Planner approval with no summary available."
        else:
            content = payload.get("details", {}).get("diff", "") or "No diff available."
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=content, details=payload)


class ApprovePendingActionTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="approve_pending_action", description="Approve and execute a previously staged file edit or shell command by token.", parameters={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]}, requires_confirmation=True)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        store = PendingActionStore(self.pending_root())
        payload = store.load(arguments["token"])
        action_type = payload["action_type"]
        if action_type in {"write_file", "edit_file"}:
            path = self.resolve_path(payload["target_path"])
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != payload["before"]:
                raise ValueError("File changed since the action was staged. Re-read the file and stage a new edit.")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload["after"], encoding="utf-8")
            store.remove(arguments["token"])
            return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=f"Applied staged {action_type} {arguments['token']} to {path}", details={"path": str(path), "token": arguments["token"], "diff": payload["details"].get("diff", "")})
        if action_type == "run_shell":
            timeout = int(payload.get("details", {}).get("timeout_seconds", 30))
            completed = subprocess.run(["powershell.exe", "-NoProfile", "-Command", payload["command"]], cwd=str(self.workspace), capture_output=True, text=True, timeout=timeout, check=False)
            output = (completed.stdout or "") + (("\n" + completed.stderr) if completed.stderr else "")
            if completed.returncode != 0:
                raise RuntimeError(f"PowerShell exited with code {completed.returncode}\n{output}".strip())
            store.remove(arguments["token"])
            return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=output.strip() or "[no output]", details={"token": arguments["token"], "command": payload["command"], "timeout_seconds": timeout, "returncode": completed.returncode})
        raise ValueError(f"Action type not supported by this tool: {action_type}")


class RejectPendingActionTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="reject_pending_action", description="Reject and remove a staged file edit or shell command by token.", parameters={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]}, requires_confirmation=True)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        store = PendingActionStore(self.pending_root())
        payload = store.load(arguments["token"])
        store.remove(arguments["token"])
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=f"Rejected pending action {arguments['token']}", details={"token": arguments["token"], "action_type": payload["action_type"]})


class ListPendingActionsTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="list_pending_actions", description="List staged actions waiting for approval.", parameters={"type": "object", "properties": {}})

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        store = PendingActionStore(self.pending_root())
        items = store.list()
        content = "\n".join(f"{item['token']} {item['action_type']} {item.get('target_path') or item.get('command') or ''}" for item in items) or "No pending actions."
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=content, details={"count": len(items), "items": items})


class ListFilesTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="list_files", description="List files and directories inside a path.", parameters={"type": "object", "properties": {"path": {"type": "string"}}})

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        raw_path = arguments.get("path", ".")
        path = self.resolve_path(raw_path)
        entries = sorted(p.name for p in path.iterdir())
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content="\n".join(entries), details={"path": str(path), "count": len(entries)})
