from __future__ import annotations

import difflib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from pp_agent.domain import ToolSpec
from pp_agent.storage.approvals import PendingActionStore, create_approval_grant, classify_pending_action, is_active_pending_action
from pp_agent.subagents.worktree import PatchArtifact, WorktreeManager
from pp_agent.tools.base import BaseTool, ToolExecutionResult
from pp_agent.tools.effects import build_file_effect, build_shell_effect, content_digest
from pp_agent.tools.policy import PermissionDomain

SEARCH_BLOCK_RE = re.compile(
    r"<<<<<<< SEARCH\n(?P<old>.*?)\n=======\n(?P<new>.*?)\n>>>>>>> REPLACE",
    re.DOTALL,
)
UNIFIED_HUNK_RE = re.compile(r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@")


class ReadFileTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="read_file", description="Read the contents of a UTF-8 text file.", parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, permission_domain=PermissionDomain.READ)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        path = self.enforce_policy_for_path(PermissionDomain.READ, arguments["path"])
        content = path.read_text(encoding="utf-8")
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=content, details={"path": str(path), "size": len(content)})


class WriteFileTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="write_file", description="Stage a new file write for host-side approval.", parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}, "overwrite": {"type": "boolean"}}, "required": ["path", "content"]}, requires_confirmation=True, permission_domain=PermissionDomain.EDIT, sensitive=True)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        path = self.enforce_policy_for_path(PermissionDomain.EDIT, arguments["path"])
        overwrite = bool(arguments.get("overwrite", False))
        existed = path.exists()
        before = path.read_text(encoding="utf-8") if existed else ""
        if existed and not overwrite:
            raise ValueError("File already exists. Re-run with overwrite=true after confirming the diff.")
        after = arguments["content"]
        diff = self._diff(before, after, path)
        store = PendingActionStore(self.pending_root())
        effect = build_file_effect(
            workspace=self.workspace,
            tool_name=self.spec.name,
            permission_domain=PermissionDomain.EDIT,
            target_path=path,
            after=after,
            baseline={"kind": "absent"} if not existed else {"kind": "present", "content_digest": content_digest(before)},
            overwrite=overwrite,
        )
        payload = store.stage(
            action_type="write_file",
            target_path=path,
            before=before,
            after=after,
            details={"overwrite": overwrite, "diff": diff},
            effect=effect,
            origin={"source": "tool", "tool_name": self.spec.name, "kind": "file_write"},
        )
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=f"Write staged-only,Not write to disk yet.\n,Staged write for {path}.\n Approve with token {payload['token']}",
            details={"path": str(path), 
                     "token": payload["token"], 
                     "diff": diff, "staged": True, 
                     "workspace": self.workspace,
                     "path": str(path),
                     "effect": effect},
        )

    @staticmethod
    def _diff(before: str, after: str, path: Path) -> str:
        return "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(), fromfile=f"a/{path.name}", tofile=f"b/{path.name}", lineterm=""))


class EditFileTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="edit_file", description="Stage a safe diff-style edit using SEARCH/REPLACE blocks or a unified diff for host-side approval.", parameters={"type": "object", "properties": {"path": {"type": "string"}, "diff": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path"]}, requires_confirmation=True, permission_domain=PermissionDomain.EDIT, sensitive=True)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        path = self.enforce_policy_for_path(PermissionDomain.EDIT, arguments["path"])
        original = path.read_text(encoding="utf-8")
        try:
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
        except ValueError as exc:
            raise ValueError(self._edit_failure_message(path, original, arguments, str(exc))) from exc
        diff = "\n".join(difflib.unified_diff(original.splitlines(), updated.splitlines(), fromfile=f"a/{path.name}", tofile=f"b/{path.name}", lineterm=""))
        store = PendingActionStore(self.pending_root())
        effect = build_file_effect(
            workspace=self.workspace,
            tool_name=self.spec.name,
            permission_domain=PermissionDomain.EDIT,
            target_path=path,
            after=updated,
            baseline={"kind": "present", "content_digest": content_digest(original)},
        )
        payload = store.stage(
            action_type="edit_file",
            target_path=path,
            before=original,
            after=updated,
            details={"replacements": replacements, "diff": diff},
            effect=effect,
            origin={"source": "tool", "tool_name": self.spec.name, "kind": "file_edit"},
        )
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=f"Write staged-only,Not write to disk yet.\n,Staged edit for {path}. Approve with token {payload['token']}",
            details={"path": str(path), 
                     "replacements": replacements, 
                     "diff": diff, 
                     "workspace": self.workspace,
                     "path": str(path),
                     "token": payload["token"], 
                     "staged": True, 
                     "effect": effect},
        )

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
    def _edit_failure_message(path: Path, content: str, arguments: dict[str, Any], failure: str) -> str:
        anchor = ""
        if arguments.get("diff"):
            matches = list(SEARCH_BLOCK_RE.finditer(str(arguments.get("diff") or "")))
            if matches:
                anchor = matches[0].group("old").splitlines()[0] if matches[0].group("old").splitlines() else ""
        else:
            anchor = str(arguments.get("old_text") or "").splitlines()[0] if arguments.get("old_text") else ""
        excerpt = EditFileTool._context_excerpt(content, anchor=anchor)
        return (
            f"{failure}\n"
            f"Path: {path}\n"
            "Nearby current file context:\n"
            f"{excerpt}\n"
            "Retry advice: re-read or inspect the file, then prefer a unified diff or SEARCH/REPLACE block using the exact current context."
        )

    @staticmethod
    def _context_excerpt(content: str, *, anchor: str = "", radius: int = 4) -> str:
        lines = content.splitlines()
        if not lines:
            return "[empty file]"
        index = 0
        stripped_anchor = anchor.strip()
        if stripped_anchor:
            for candidate_index, line in enumerate(lines):
                if stripped_anchor in line:
                    index = candidate_index
                    break
        start = max(0, index - radius)
        end = min(len(lines), index + radius + 1)
        return "\n".join(f"{line_no}: {lines[line_no - 1]}" for line_no in range(start + 1, end + 1))

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
    def __init__(self, workspace: Path, policy_evaluator=None, *, tool_registry=None) -> None:
        super().__init__(workspace, policy_evaluator)
        self.tool_registry = tool_registry

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="preview_pending_action", description="Preview a staged action by token, including diff or command details.", parameters={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]}, permission_domain=PermissionDomain.APPROVAL, model_callable=False)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        store = PendingActionStore(self.pending_root())
        payload = store.load(arguments["token"])
        if payload["action_type"] == "run_shell":
            content = payload.get("command") or ""
        elif payload["action_type"] == "apply_patch_artifact":
            artifact_payload = payload.get("details", {}).get("artifact", {})
            changed_paths = payload.get("details", {}).get("changed_paths", [])
            check = "unknown"
            try:
                artifact = PatchArtifact(**artifact_payload)
                completed = WorktreeManager(self.workspace).apply_check(artifact)
                check = "ok" if completed.returncode == 0 else (completed.stderr or completed.stdout or "failed").strip()
            except Exception as exc:  # noqa: BLE001
                check = str(exc)
            content = "\n".join(
                [
                    f"Patch artifact: {artifact_payload.get('artifact_id', 'unknown')}",
                    f"Patch path: {artifact_payload.get('patch_path', payload.get('details', {}).get('patch_path', 'unknown'))}",
                    f"Worktree: {artifact_payload.get('worktree_path', 'unknown')}",
                    f"Changed paths: {', '.join(changed_paths) if changed_paths else 'none'}",
                    f"Apply check: {check}",
                ]
            )
        elif payload["action_type"] in {"run_extension_tool", "run_mcp_tool"}:
            content = "No preview available."
        elif payload["action_type"] == "planner_approval":
            summary = payload.get("details", {}).get("summary", []) or []
            content = "\n".join(summary) or "Planner approval with no summary available."
        else:
            content = payload.get("details", {}).get("diff", "") or "No diff available."
        effect = payload.get("effect")
        if effect is not None:
            analysis = effect.get("analysis", {})
            lifecycle = payload.get("lifecycle") or {}
            grant = payload.get("approval_grant") or {}
            lines = [
                f"Summary: {analysis.get('summary', effect['summary'])}",
                f"Digest: {effect['payload_digest']}",
                f"Family: {analysis.get('family', 'unknown')}",
                f"Risk class: {analysis.get('risk_class', 'unknown')}",
                f"Confidence: {analysis.get('confidence_band', 'unknown')}",
                f"Lifecycle state: {lifecycle.get('state', 'unknown')}",
                f"Grant status: {grant.get('status', 'not_attached')}",
                f"Grant id: {grant.get('grant_id', 'none')}",
                f"Touches workspace: {analysis.get('touches_workspace', False)}",
                f"Touches external: {analysis.get('touches_external', False)}",
                f"Requests network: {analysis.get('requests_network', False)}",
                f"Destructive hint: {analysis.get('destructive_hint', False)}",
                f"Protected path hint: {analysis.get('protected_path_hint', False)}",
            ]
            if lifecycle.get("failure_reason_code"):
                lines.append(f"Failure reason code: {lifecycle.get('failure_reason_code')}")
            if lifecycle.get("failure_reason_detail"):
                lines.append(f"Failure detail: {lifecycle.get('failure_reason_detail')}")
            if payload["action_type"] == "run_shell":
                lines.append(f"Command head: {analysis.get('command_head', 'unknown')}")
                lines.append(f"Normalized command: {effect['normalized_arguments'].get('normalized_command', payload.get('command', ''))}")
                if payload.get("command") != effect["normalized_arguments"].get("normalized_command"):
                    lines.append(f"Original command: {payload.get('command', '')}")
                flags = analysis.get("flags", [])
                if flags:
                    lines.append(f"Flags: {', '.join(flags)}")
                content = "\n".join(lines).strip()
            elif payload["action_type"] in {"run_extension_tool", "run_mcp_tool"}:
                lines.append(f"Tool name: {payload.get('details', {}).get('tool_name', effect.get('tool_name', 'unknown'))}")
                arguments_preview = payload.get("details", {}).get("arguments", effect["normalized_arguments"].get("arguments", {}))
                lines.append(f"Arguments: {json.dumps(arguments_preview, ensure_ascii=False, sort_keys=True)}")
                content = "\n".join(lines).strip()
            else:
                content = ("\n".join(lines) + f"\n\n{content}").strip()
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=content, details=payload)


class ApprovePendingActionTool(BaseTool):
    def __init__(self, workspace: Path, policy_evaluator=None, *, tool_registry=None) -> None:
        super().__init__(workspace, policy_evaluator)
        self.tool_registry = tool_registry

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="approve_pending_action", description="Approve and execute a previously staged file edit or shell command by token.", parameters={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]}, requires_confirmation=True, permission_domain=PermissionDomain.APPROVAL, sensitive=True, model_callable=False)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        store = PendingActionStore(self.pending_root())
        payload = store.load(arguments["token"])
        effect = payload.get("effect")
        if effect is None:
            raise ValueError("Pending action is missing an effect record.")
        lifecycle = payload.get("lifecycle") or {}
        state = lifecycle.get("state")
        if classify_pending_action(payload) == "expired":
            store.set_lifecycle(arguments["token"], "expired", failure_reason_code="approval_expired")
            raise ValueError("Pending action cannot be approved because it has expired.")
        if state == "grant_consumed":
            return ToolExecutionResult(
                tool_call_id="",
                tool_name=self.spec.name,
                content=f"Pending action {arguments['token']} was already approved and consumed.",
                details={
                    "token": arguments["token"],
                    "action_type": payload["action_type"],
                    "success": True,
                    "idempotent": True,
                    "lifecycle": lifecycle,
                    "effect": effect,
                    "approval_grant": payload.get("approval_grant"),
                },
            )
        if state in {"execution_in_progress", "grant_invalidated", "rejected", "denied", "quarantined", "orphaned", "expired"}:
            raise ValueError(f"Pending action cannot be approved from lifecycle state {lifecycle.get('state')}.")
        grant = payload.get("approval_grant")
        if grant is None:
            payload["approval_grant"] = create_approval_grant(effect)
            payload["lifecycle"] = self._lifecycle("grant_attached")
            store.save(arguments["token"], payload)
            payload = store.load(arguments["token"])
        try:
            self._validate_grant(payload)
        except ValueError as exc:
            updated = store.load(arguments["token"])
            grant = updated.get("approval_grant")
            if grant is not None:
                grant["status"] = "invalidated"
                grant["invalidated_at"] = time.time()
            updated["lifecycle"] = self._lifecycle("grant_invalidated", "payload_digest_mismatch", str(exc))
            store.save(arguments["token"], updated)
            store.write_audit_record(
                arguments["token"],
                lifecycle_state="grant_invalidated",
                failure_reason_code="payload_digest_mismatch",
                failure_reason_detail=str(exc),
            )
            raise
        payload = store.set_lifecycle(arguments["token"], "execution_in_progress")
        action_type = payload["action_type"]
        if action_type in {"write_file", "edit_file"}:
            try:
                path = self.enforce_policy_for_path(PermissionDomain.EDIT, payload["target_path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(payload["after"], encoding="utf-8")
            except Exception as exc:
                return self._record_execution_failure(store, arguments["token"], effect, exc)
            return self._consume_success(
                store,
                token=arguments["token"],
                content=(
                    f"Write applied successfully.\n"
                    f"Saved to: {path}\n"
                    f"Token: {arguments['token']}"
                ),
                effect=effect,
                details={
                    "path": str(path),
                    "absolute_path": str(path),
                    "workspace_root": str(self.workspace),
                    "token": arguments["token"],
                    "diff": payload["details"].get("diff", ""),
                    "persisted": True,
                    "lifecycle": {"state": "grant_consumed"},
                    "effect": effect,
                },
            )
        if action_type == "run_shell":
            timeout = int(payload.get("details", {}).get("timeout_seconds", 30))
            try:
                self.enforce_policy_for_command(PermissionDomain.BASH, payload["command"])
                completed = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command", payload["command"]],
                    cwd=str(self.workspace),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
                if completed.returncode != 0:
                    raise RuntimeError(
                        "PowerShell exited with code "
                        f"{completed.returncode}\n"
                        f"stdout:\n{completed.stdout or ''}\n"
                        f"stderr:\n{completed.stderr or ''}".strip()
                    )
            except Exception as exc:
                return self._record_execution_failure(store, arguments["token"], effect, exc)
            return self._consume_success(
                store,
                token=arguments["token"],
                content=((completed.stdout or "") + (("\n" + completed.stderr) if completed.stderr else "")).strip() or "[no output]",
                effect=effect,
                details={
                    "token": arguments["token"],
                    "command": payload["command"],
                    "timeout_seconds": timeout,
                    "returncode": completed.returncode,
                    "effect": effect,
                },
            )
        if action_type == "apply_patch_artifact":
            try:
                artifact = PatchArtifact(**payload.get("details", {}).get("artifact", {}))
                manager = WorktreeManager(self.workspace)
                check = manager.apply_check(artifact)
                if check.returncode != 0:
                    raise RuntimeError((check.stderr or check.stdout or "git apply --check failed").strip())
                applied = manager.apply(artifact)
                if applied.returncode != 0:
                    raise RuntimeError((applied.stderr or applied.stdout or "git apply failed").strip())
            except Exception as exc:
                return self._record_execution_failure(store, arguments["token"], effect, exc)
            return self._consume_success(
                store,
                token=arguments["token"],
                content=f"Patch artifact applied successfully.\nArtifact: {artifact.artifact_id}",
                effect=effect,
                details={
                    "token": arguments["token"],
                    "artifact": artifact.model_dump(mode="python"),
                    "changed_paths": list(artifact.changed_paths),
                    "effect": effect,
                },
            )
        if action_type in {"run_extension_tool", "run_mcp_tool"}:
            if self.tool_registry is None:
                raise ValueError("Dynamic approvals require tool registry access.")
            tool_name = payload.get("details", {}).get("tool_name")
            arguments_payload = payload.get("details", {}).get("arguments")
            if not isinstance(tool_name, str) or not isinstance(arguments_payload, dict):
                raise ValueError("Pending dynamic action is missing tool_name or arguments.")
            try:
                result = self.tool_registry.host_execute_dynamic_approved(tool_name, arguments_payload)
            except Exception as exc:
                return self._record_execution_failure(store, arguments["token"], effect, exc)
            if result.is_error:
                error = RuntimeError(result.content or "Dynamic executor returned an error result.")
                return self._record_execution_failure(store, arguments["token"], effect, error, base_result=result)
            success = self._consume_success(
                store,
                token=arguments["token"],
                content=result.content,
                effect=effect,
                details={
                    **(result.details or {}),
                    "token": arguments["token"],
                    "tool_name": tool_name,
                    "arguments": arguments_payload,
                    "effect": effect,
                },
            )
            success.tool_name = result.tool_name or self.spec.name
            return success
        raise ValueError(f"Action type not supported by this tool: {action_type}")

    def _validate_grant(self, payload: dict[str, Any]) -> None:
        effect = payload["effect"]
        grant = payload["approval_grant"]
        if grant.get("status") != "active":
            raise ValueError("Approval grant is no longer active.")
        if grant.get("effect_id") != effect.get("effect_id"):
            raise ValueError("Approval invalidated: approval grant does not match the current effect.")
        if grant.get("payload_digest") != effect.get("payload_digest"):
            raise ValueError("Approval invalidated: payload digest no longer matches the approved effect.")
        current_effect = self._current_effect(payload, effect)
        if current_effect["payload_digest"] != effect["payload_digest"]:
            raise ValueError("Approval invalidated: payload digest changed after approval.")
        if current_effect["summary"] != effect["summary"]:
            raise ValueError("Approval invalidated: effect summary changed after approval.")

    @staticmethod
    def _lifecycle(state: str, failure_reason_code: str | None = None, failure_reason_detail: str | None = None) -> dict[str, Any]:
        return {
            "state": state,
            "updated_at": time.time(),
            "failure_reason_code": failure_reason_code,
            "failure_reason_detail": failure_reason_detail,
        }

    def _record_execution_failure(
        self,
        store: PendingActionStore,
        token: str,
        effect: dict[str, Any],
        error: Exception,
        *,
        base_result: ToolExecutionResult | None = None,
    ) -> ToolExecutionResult:
        failure_detail = str(error)
        updated = store.load(token)
        updated["lifecycle"] = self._lifecycle("execution_failed", "executor_error", failure_detail)
        store.save(token, updated)
        audit = store.write_audit_record(
            token,
            lifecycle_state="execution_failed",
            failure_reason_code="executor_error",
            failure_reason_detail=failure_detail,
        )
        details = {
            "token": token,
            "effect": effect,
            "approval_grant": updated.get("approval_grant"),
            "lifecycle": updated["lifecycle"],
            "latest_audit": audit,
            "failure_kind": "execution_failed",
        }
        action_type = str(updated.get("action_type") or "").strip()
        if action_type == "run_shell":
            shell_failure = self._shell_failure_details(failure_detail)
            details.update(shell_failure)
        if action_type in {"edit_file", "apply_patch_artifact"}:
            payload_details = updated.get("details") if isinstance(updated.get("details"), dict) else {}
            details.update(
                {
                    "patch_failed": True,
                    "action_type": action_type,
                    "retry_hint": "Inspect the current target file/diff context, regenerate the patch against the current workspace, and rerun approval.",
                }
            )
            if action_type == "apply_patch_artifact":
                artifact = payload_details.get("artifact") if isinstance(payload_details, dict) else {}
                details["changed_paths"] = payload_details.get("changed_paths", [])
                if isinstance(artifact, dict):
                    details["artifact_id"] = artifact.get("artifact_id")
                    details["patch_path"] = artifact.get("patch_path")
        content = f"Executor failed after approval: {failure_detail}"
        retry_hint = details.get("retry_hint")
        if retry_hint:
            content += f"\nRetry advice: {retry_hint}"
        if action_type == "apply_patch_artifact":
            changed_paths = details.get("changed_paths") or []
            if changed_paths:
                content += f"\nChanged paths: {', '.join(str(path) for path in changed_paths)}"
            artifact_id = details.get("artifact_id")
            if artifact_id:
                content += f"\nArtifact: {artifact_id}"
        if base_result is not None:
            base_result.is_error = True
            base_result.details = {**(base_result.details or {}), **details}
            base_result.content = content
            return base_result
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=content,
            is_error=True,
            details=details,
        )

    @staticmethod
    def _shell_failure_details(failure_detail: str) -> dict[str, Any]:
        match = re.search(
            r"PowerShell exited with code (?P<code>-?\d+)\nstdout:\n(?P<stdout>.*?)(?:\nstderr:\n(?P<stderr>.*))?\Z",
            failure_detail,
            flags=re.DOTALL,
        )
        if not match:
            return {"command_failed": True}
        stdout = (match.group("stdout") or "").strip()
        stderr = (match.group("stderr") or "").strip()
        return {
            "command_failed": True,
            "exit_code": int(match.group("code")),
            "returncode": int(match.group("code")),
            "stdout": stdout,
            "stderr": stderr,
        }

    def _consume_success(
        self,
        store: PendingActionStore,
        *,
        token: str,
        content: str,
        effect: dict[str, Any],
        details: dict[str, Any],
    ) -> ToolExecutionResult:
        updated = store.load(token)
        updated["lifecycle"] = self._lifecycle("execution_succeeded")
        grant = updated.get("approval_grant")
        if grant is not None:
            grant["status"] = "consumed"
            grant["consumed_at"] = time.time()
        updated["lifecycle"] = self._lifecycle("grant_consumed")
        store.save(token, updated)
        audit = store.write_audit_record(token, lifecycle_state="grant_consumed")
        result_details = {
            **details,
            "approval_grant": updated.get("approval_grant"),
            "lifecycle": updated["lifecycle"],
            "latest_audit": audit,
        }
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=content, details=result_details)

    def _current_effect(self, payload: dict[str, Any], stored_effect: dict[str, Any]) -> dict[str, Any]:
        action_type = payload["action_type"]
        if action_type in {"write_file", "edit_file"}:
            path = self.enforce_policy_for_path(PermissionDomain.EDIT, payload["target_path"])
            baseline = stored_effect["baseline"]
            if baseline["kind"] == "absent":
                if path.exists():
                    raise ValueError("Approval invalidated: file baseline changed from absent to present.")
            else:
                if not path.exists():
                    raise ValueError("Approval invalidated: file baseline changed from present to absent.")
                current = path.read_text(encoding="utf-8")
                if content_digest(current) != baseline["content_digest"]:
                    raise ValueError("Approval invalidated: file baseline content changed.")
            return build_file_effect(
                workspace=self.workspace,
                tool_name=stored_effect["tool_name"],
                permission_domain=stored_effect["permission_domain"],
                target_path=path,
                after=payload["after"],
                baseline=baseline,
                overwrite=bool(payload.get("details", {}).get("overwrite", False)),
                effect_id=stored_effect["effect_id"],
                created_at=stored_effect["created_at"],
            )
        if action_type == "run_shell":
            timeout = int(payload.get("details", {}).get("timeout_seconds", 30))
            return build_shell_effect(
                tool_name=stored_effect["tool_name"],
                permission_domain=stored_effect["permission_domain"],
                command=payload["command"],
                timeout_seconds=timeout,
                workspace=self.workspace,
                effect_id=stored_effect["effect_id"],
                created_at=stored_effect["created_at"],
            )
        if action_type == "apply_patch_artifact":
            artifact_payload = payload.get("details", {}).get("artifact", {})
            artifact = PatchArtifact(**artifact_payload)
            return WorktreeManager(self.workspace).build_effect(
                artifact.model_copy(update={"status": artifact.status})
            ) | {"effect_id": stored_effect["effect_id"], "created_at": stored_effect["created_at"]}
        if action_type in {"run_extension_tool", "run_mcp_tool"}:
            if self.tool_registry is None:
                raise ValueError("Dynamic approvals require tool registry access.")
            details = payload.get("details", {})
            tool_name = details.get("tool_name")
            arguments_payload = details.get("arguments")
            if not isinstance(tool_name, str):
                raise ValueError("Approval invalidated: pending dynamic tool name is missing.")
            if not isinstance(arguments_payload, dict):
                raise ValueError("Approval invalidated: pending dynamic arguments are missing.")
            registration = self.tool_registry.metadata().get(tool_name)
            if registration is None:
                raise ValueError("Approval invalidated: dynamic tool is no longer registered.")
            if registration.tool_family != stored_effect["analysis"].get("family"):
                raise ValueError("Approval invalidated: dynamic tool family changed.")
            if registration.exact_effect_mode == "none":
                raise ValueError("Approval invalidated: dynamic tool no longer supports exact-effect staging.")
            return self.tool_registry.build_dynamic_effect(
                tool_name,
                arguments_payload,
                analysis=None,
                effect_id=stored_effect["effect_id"],
                created_at=stored_effect["created_at"],
            )
        raise ValueError(f"Action type not supported by this tool: {action_type}")


class RejectPendingActionTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="reject_pending_action", description="Reject and archive a staged file edit or shell command by token.", parameters={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]}, requires_confirmation=True, permission_domain=PermissionDomain.APPROVAL, sensitive=True, model_callable=False)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        store = PendingActionStore(self.pending_root())
        payload = store.load(arguments["token"])
        lifecycle = payload.get("lifecycle") or {}
        if lifecycle.get("state") != "rejected":
            grant = payload.get("approval_grant")
            if isinstance(grant, dict) and grant.get("status") == "active":
                grant["status"] = "invalidated"
                grant["invalidated_at"] = time.time()
            payload["lifecycle"] = {
                "state": "rejected",
                "updated_at": time.time(),
                "failure_reason_code": None,
                "failure_reason_detail": None,
            }
            store.save(arguments["token"], payload)
            store.write_audit_record(arguments["token"], lifecycle_state="rejected")
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=f"Rejected pending action {arguments['token']}",
            details={
                "token": arguments["token"],
                "action_type": payload["action_type"],
                "idempotent": lifecycle.get("state") == "rejected",
                "lifecycle": (store.load(arguments["token"]).get("lifecycle") or {}),
            },
        )


class ListPendingActionsTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="list_pending_actions", description="List staged actions waiting for approval.", parameters={"type": "object", "properties": {}}, permission_domain=PermissionDomain.APPROVAL, model_callable=False)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        store = PendingActionStore(self.pending_root())
        items = [item for item in store.list() if is_active_pending_action(item)]
        content = "\n".join(
            f"{item['token']} {item['action_type']} [{(item.get('lifecycle') or {}).get('state', 'unknown')}] {item.get('target_path') or item.get('command') or ''}"
            for item in items
        ) or "No pending actions."
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=content, details={"count": len(items), "items": items})


class ListFilesTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="list_files", description="List files and directories inside a path.", parameters={"type": "object", "properties": {"path": {"type": "string"}}}, permission_domain=PermissionDomain.READ)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        raw_path = arguments.get("path", ".")
        path = self.enforce_policy_for_path(PermissionDomain.READ, raw_path)
        entries = sorted(
            p.name
            for p in path.iterdir()
            if self.policy_evaluator.is_within_workspace(p.resolve()) and not self.policy_evaluator.is_protected(p.resolve())
        )
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content="\n".join(entries), details={"path": str(path), "count": len(entries)})
