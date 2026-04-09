from __future__ import annotations

import subprocess
from typing import Any

from pp_agent.domain import ToolSpec
from pp_agent.tools.base import BaseTool, ToolExecutionResult
from pp_agent.tools.policy import PermissionDomain


class GrepCodeTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="grep_code",
            description="Search code text under the workspace, optimized for coding tasks.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}, "path": {"type": "string"}},
                "required": ["query"],
            },
            permission_domain=PermissionDomain.READ,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        query = arguments["query"]
        root = self.enforce_policy_for_path(PermissionDomain.READ, arguments.get("path", "."))
        matches: list[str] = []
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            resolved = file_path.resolve()
            if not self.policy_evaluator.is_within_workspace(resolved) or self.policy_evaluator.is_protected(resolved):
                continue
            try:
                for line_number, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
                    if query in line:
                        matches.append(f"{file_path.relative_to(self.workspace)}:{line_number}: {line}")
            except UnicodeDecodeError:
                continue
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content="\n".join(matches) if matches else "No matches found.", details={"path": str(root), "matches": len(matches), "query": query})


class GitStatusTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="git_status", description="Show git worktree status for the current workspace.", parameters={"type": "object", "properties": {}}, permission_domain=PermissionDomain.REPO)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        return self._run_git(["git", "status", "--short", "--branch"])

    def _run_git(self, cmd: list[str]) -> ToolExecutionResult:
        completed = subprocess.run(cmd, cwd=str(self.workspace), capture_output=True, text=True, check=False)
        output = (completed.stdout or "") + (("\n" + completed.stderr) if completed.stderr else "")
        if completed.returncode != 0:
            return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content="Not a git repository or git is unavailable.", details={"returncode": completed.returncode, "error": output.strip()})
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=output.strip() or "Clean worktree.", details={"returncode": completed.returncode})


class GitDiffWorktreeTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="git_diff_worktree",
            description="Show git diff for the current worktree or a single path.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            permission_domain=PermissionDomain.REPO,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        cmd = ["git", "diff", "--"]
        path = arguments.get("path")
        if path:
            resolved = self.enforce_policy_for_path(PermissionDomain.READ, path)
            cmd.append(str(resolved.relative_to(self.workspace)))
        completed = subprocess.run(cmd, cwd=str(self.workspace), capture_output=True, text=True, check=False)
        output = (completed.stdout or "") + (("\n" + completed.stderr) if completed.stderr else "")
        if completed.returncode != 0:
            return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content="Not a git repository or git diff failed.", details={"returncode": completed.returncode, "error": output.strip()})
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=output.strip() or "No diff.", details={"returncode": completed.returncode, "path": path or "."})
