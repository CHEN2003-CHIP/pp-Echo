from __future__ import annotations

import difflib
import json
import locale
import re
import time
from pathlib import Path
from typing import Any, Optional

from pp_agent.domain import ToolSpec
from pp_agent.attachments.importer import AttachmentWorkspaceImporter
from pp_agent.runtime.execution_context import (
    attach_runtime_context_to_patch_candidate_args,
    check_runtime_guardrails,
    increment_runtime_counter,
    runtime_counters_to_dict,
    runtime_guardrail_check_to_dict,
)
from pp_agent.runtime.scope_contract import check_structured_changes_against_write_scope, write_scope_check_to_dict, write_scope_from_dict
from pp_agent.sandbox.base import SandboxExecutor, SandboxRunRequest
from pp_agent.sandbox.changes import bytes_digest, normalize_structured_changes, structured_changes_digest as hash_structured_changes
from pp_agent.sandbox.preflight import DockerSandboxPreflightError
from pp_agent.storage.approvals import PendingActionStore, create_approval_grant, classify_pending_action, is_active_pending_action
from pp_agent.subagents.worktree import PatchArtifact, WorktreeManager
from pp_agent.tools.base import BaseTool, ToolExecutionResult
from pp_agent.tools.effects import build_file_effect, build_patch_candidate_effect, build_shell_effect, content_digest
from pp_agent.tools.policy import PermissionDomain
from pp_agent.tools.shell_tool import default_local_sandbox_executor, sandbox_result_details, sandbox_result_error, shell_output

SEARCH_BLOCK_RE = re.compile(
    r"<<<<<<< SEARCH\n(?P<old>.*?)\n=======\n(?P<new>.*?)\n>>>>>>> REPLACE",
    re.DOTALL,
)
UNIFIED_HUNK_RE = re.compile(r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@")
DEFAULT_READ_FILE_MAX_CHARS = 20_000
APPLY_PATCH_CANDIDATE_TOOL = "apply_patch_candidate"
MAX_EDIT_FILE_BYTES = 1024 * 1024
MAX_PATCH_SNAPSHOT_BYTES = 5 * 1024 * 1024
WorkspaceApplyLock = None
WorkspaceApplyLockError = None
WorkspaceApplyLockTimeout = None


def _workspace_lock_types():
    """Load workspace lock classes lazily to avoid tools<->runtime import cycles."""

    global WorkspaceApplyLock, WorkspaceApplyLockError, WorkspaceApplyLockTimeout
    from pp_agent.runtime.workspace_lock import (
        WorkspaceApplyLock as RuntimeWorkspaceApplyLock,
        WorkspaceApplyLockError as RuntimeWorkspaceApplyLockError,
        WorkspaceApplyLockTimeout as RuntimeWorkspaceApplyLockTimeout,
    )

    if WorkspaceApplyLock is None:
        WorkspaceApplyLock = RuntimeWorkspaceApplyLock
    if WorkspaceApplyLockError is None:
        WorkspaceApplyLockError = RuntimeWorkspaceApplyLockError
    if WorkspaceApplyLockTimeout is None:
        WorkspaceApplyLockTimeout = RuntimeWorkspaceApplyLockTimeout
    return WorkspaceApplyLock, WorkspaceApplyLockError, WorkspaceApplyLockTimeout


class ReadFileTool(BaseTool):
    def __init__(self, workspace: Path, policy_evaluator=None, *, current_session_id: Optional[str] = None) -> None:
        super().__init__(workspace, policy_evaluator)
        self.current_session_id = current_session_id

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="read_file",
            description="Read a text file safely with bounded preview support for long files.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer"},
                    "offset": {"type": "integer"},
                },
                "required": ["path"],
            },
            permission_domain=PermissionDomain.READ,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        raw_path = str(arguments["path"])
        max_chars = max(1, int(arguments.get("max_chars") or DEFAULT_READ_FILE_MAX_CHARS))
        offset = max(0, int(arguments.get("offset") or 0))
        try:
            path = self.enforce_policy_for_path(PermissionDomain.READ, raw_path)
            raw = path.read_bytes()
        except (FileNotFoundError, PermissionError):
            attachment_result = self._read_matching_attachment(raw_path, max_chars=max_chars, offset=offset)
            if attachment_result is not None:
                return attachment_result
            raise
        text, encoding = _decode_text_bytes(raw)
        content, truncated = _slice_file_preview(text, offset=offset, max_chars=max_chars)
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=content,
            details={
                "path": str(path),
                "size": len(raw),
                "encoding": encoding,
                "text_length": len(text),
                "truncated": truncated,
                "offset": offset,
                "max_chars": max_chars,
            },
        )

    def _read_matching_attachment(self, raw_path: str, *, max_chars: int, offset: int) -> ToolExecutionResult | None:
        """当模型误把上传附件当 workspace 文件读取时，按同名附件做受限读取兜底。"""

        if not self.current_session_id:
            return None
        from pp_agent.attachments.service import AttachmentService

        requested_name = Path(raw_path).name
        if not requested_name:
            return None
        service = AttachmentService(self.workspace)
        for record in service.list(self.current_session_id):
            if requested_name not in {record.original_filename, record.stored_filename}:
                continue
            payload = service.read_range(self.current_session_id, record.attachment_id, 1, 1_000_000, max_chars=max_chars)
            text = str(payload.get("text") or "")
            if offset:
                text, truncated = _slice_file_preview(text, offset=offset, max_chars=max_chars)
            else:
                truncated = bool(payload.get("truncated"))
            content = (
                f"[read_file fallback: `{requested_name}` is an uploaded session attachment, not a workspace file. "
                "Use inspect_attachment/search_attachment/read_attachment_range for follow-up reads.]\n\n"
                f"{text}"
            )
            return ToolExecutionResult(
                tool_call_id="",
                tool_name=self.spec.name,
                content=content,
                details={
                    "path": raw_path,
                    "attachment_fallback": True,
                    "attachment_id": record.attachment_id,
                    "filename": record.stored_filename,
                    "source_ref": f"{record.stored_filename}:L{payload.get('line_start')}-L{payload.get('line_end')}",
                    "text_length": len(text),
                    "truncated": truncated,
                    "offset": offset,
                    "max_chars": max_chars,
                },
            )
        return None


def _decode_text_bytes(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    fallback = locale.getpreferredencoding(False) or "utf-8"
    try:
        return raw.decode(fallback), fallback
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def _slice_file_preview(text: str, *, offset: int, max_chars: int) -> tuple[str, bool]:
    start = min(max(0, offset), len(text))
    end = min(len(text), start + max_chars)
    preview = text[start:end]
    truncated = start > 0 or end < len(text)
    if truncated:
        remaining = max(0, len(text) - end)
        preview = (
            f"{preview}\n\n"
            f"[File preview truncated. offset={start}, max_chars={max_chars}, remaining_chars={remaining}. "
            "Read again with offset/max_chars to continue.]"
        )
    return preview, truncated


def validate_text_edit_target(path: Path, *, content: str | None = None, max_bytes: int = MAX_EDIT_FILE_BYTES) -> str:
    if path.is_symlink():
        raise PermissionError(f"Refusing to edit symlink path: {path}")
    if path.exists():
        if not path.is_file():
            raise ValueError(f"Refusing to edit non-file path: {path}")
        size = path.stat().st_size
        if size > max_bytes:
            raise ValueError(f"Refusing to edit large file: {path} ({size} bytes > {max_bytes} bytes)")
        raw = path.read_bytes()
        if b"\x00" in raw:
            raise ValueError(f"Refusing to edit binary file: {path}")
        try:
            before = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Refusing to edit non-UTF-8 text file: {path}") from exc
    else:
        before = ""
    if content is not None:
        raw_content = content.encode("utf-8")
        if len(raw_content) > max_bytes:
            raise ValueError(f"Refusing to write large content: {path} ({len(raw_content)} bytes > {max_bytes} bytes)")
        if "\x00" in content:
            raise ValueError(f"Refusing to write binary-like content: {path}")
    return before


def reject_symlink_edit_path(workspace: Path, raw_path: str) -> None:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    if candidate.is_symlink():
        raise PermissionError(f"Refusing to edit symlink path: {candidate}")


class WriteFileTool(BaseTool):
    def __init__(self, workspace: Path, policy_evaluator=None, *, current_session_id: str | None = None) -> None:
        super().__init__(workspace, policy_evaluator)
        self.current_session_id = current_session_id

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="write_file", description="Stage a new file write for host-side approval.", parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}, "overwrite": {"type": "boolean"}}, "required": ["path", "content"]}, requires_confirmation=True, permission_domain=PermissionDomain.EDIT, sensitive=True)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        reject_symlink_edit_path(self.workspace, str(arguments["path"]))
        path = self.enforce_policy_for_path(PermissionDomain.EDIT, arguments["path"])
        overwrite = bool(arguments.get("overwrite", False))
        existed = path.exists()
        after = str(arguments["content"])
        before = validate_text_edit_target(path, content=after)
        if existed and not overwrite:
            raise ValueError("File already exists. Re-run with overwrite=true after confirming the diff.")
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
            session_id=self.current_session_id,
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
    def __init__(self, workspace: Path, policy_evaluator=None, *, current_session_id: str | None = None) -> None:
        super().__init__(workspace, policy_evaluator)
        self.current_session_id = current_session_id

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="edit_file", description="Stage a safe diff-style edit using SEARCH/REPLACE blocks or a unified diff for host-side approval.", parameters={"type": "object", "properties": {"path": {"type": "string"}, "diff": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path"]}, requires_confirmation=True, permission_domain=PermissionDomain.EDIT, sensitive=True)

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        reject_symlink_edit_path(self.workspace, str(arguments["path"]))
        path = self.enforce_policy_for_path(PermissionDomain.EDIT, arguments["path"])
        original = validate_text_edit_target(path)
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
            session_id=self.current_session_id,
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
    def __init__(
        self,
        workspace: Path,
        policy_evaluator=None,
        *,
        tool_registry=None,
        sandbox_executor: SandboxExecutor | None = None,
    ) -> None:
        super().__init__(workspace, policy_evaluator)
        self.tool_registry = tool_registry
        self.sandbox_executor = sandbox_executor or default_local_sandbox_executor()

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
        action_type = payload["action_type"]
        if action_type == "run_shell":
            shell_guardrail = self._check_runtime_guardrail("shell_command")
            if shell_guardrail.allowed is False:
                return self._runtime_guardrail_block_result("shell_command", shell_guardrail, token=arguments["token"])
        payload = store.set_lifecycle(arguments["token"], "execution_in_progress")
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
                self._emit_sandbox_preflight_event(payload, token=arguments["token"])
                completed = self.sandbox_executor.run(
                    SandboxRunRequest(command=payload["command"], cwd=self.workspace, timeout_seconds=timeout)
                )
                if completed.returncode != 0:
                    raise sandbox_result_error(completed)
            except Exception as exc:
                return self._record_execution_failure(store, arguments["token"], effect, exc)
            shell_context = self._increment_runtime_counter("shell_command")
            patch_candidate = self._stage_patch_candidate(store, payload, completed)
            shell_content = shell_output(completed).strip() or "[no output]"
            if patch_candidate.get("staged"):
                shell_content += (
                    "\n\nSandbox patch candidate staged. "
                    f"Approve patch token {patch_candidate['token']} to apply changes to the real workspace."
                )
            elif patch_candidate.get("reason"):
                shell_content += f"\n\nSandbox patch candidate not staged: {patch_candidate['reason']}"
            return self._consume_success(
                store,
                token=arguments["token"],
                content=shell_content,
                effect=effect,
                details={
                    "token": arguments["token"],
                    "command": payload["command"],
                    "timeout_seconds": timeout,
                    "returncode": completed.returncode,
                    "effect": effect,
                    "patch_candidate": patch_candidate,
                    **self._runtime_result_details(shell_context, guardrail_check=shell_guardrail, action="shell_command"),
                    **sandbox_result_details(completed),
                },
            )
        if action_type == "apply_patch_candidate":
            try:
                apply_result = self._apply_patch_candidate_payload(payload)
            except Exception as exc:
                return self._record_execution_failure(store, arguments["token"], effect, exc)
            if not apply_result.get("applied"):
                return self._record_patch_apply_failure(store, arguments["token"], effect, apply_result)
            return self._consume_success(
                store,
                token=arguments["token"],
                content=f"Sandbox patch candidate applied successfully.\n{payload.get('details', {}).get('patch_summary', '')}",
                effect=effect,
                details={
                    "token": arguments["token"],
                    "applied": True,
                    "atomic": True,
                    "changed_files": apply_result["changed_files"],
                    "changed_paths": apply_result["changed_paths"],
                    "patch_digest": payload.get("details", {}).get("patch_digest"),
                    "sandbox_backend": payload.get("details", {}).get("sandbox_backend"),
                    "sandbox_mode": payload.get("details", {}).get("sandbox_mode"),
                    "source_shell_command_digest": payload.get("details", {}).get("source_shell_command_digest"),
                    "source_shell_action_token": payload.get("details", {}).get("source_shell_action_token"),
                    "apply_backend": apply_result.get("apply_backend", "internal_unified_diff"),
                    "structured_changes_digest": apply_result.get("structured_changes_digest"),
                    "rollback_attempted": False,
                    "post_apply_validated": True,
                    "lock_acquired": apply_result.get("lock_acquired"),
                    "lock_released": apply_result.get("lock_released"),
                    "lock_path": apply_result.get("lock_path"),
                    "lock_wait_ms": apply_result.get("lock_wait_ms"),
                    **({"scope_check": apply_result.get("scope_check")} if apply_result.get("scope_check") is not None else {}),
                    **(
                        {
                            "lock_release_error": apply_result.get("lock_release_error"),
                            "manual_cleanup_required": apply_result.get("manual_cleanup_required"),
                        }
                        if apply_result.get("lock_released") is False
                        else {}
                    ),
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
        if action_type == "attachment_import":
            try:
                importer = AttachmentWorkspaceImporter(self.workspace)
                result = importer.complete_import_after_approval(payload.get("details", {}))
            except Exception as exc:
                return self._record_execution_failure(store, arguments["token"], effect, exc)
            return self._consume_success(
                store,
                token=arguments["token"],
                content=f"Attachment imported successfully.\nSaved to: {result['path']}\nToken: {arguments['token']}",
                effect=effect,
                details={
                    **result,
                    "token": arguments["token"],
                    "attachment_id": payload.get("details", {}).get("attachment_id"),
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

    def _emit_sandbox_preflight_event(self, payload: dict[str, Any], *, token: str) -> None:
        """Emit a lightweight Web/runtime progress event before sandbox execution begins."""

        if self.tool_registry is None:
            return
        emitter = getattr(self.tool_registry, "_runtime_event_emitter", None)
        if not callable(emitter):
            return
        from pp_agent.runtime.state import AgentEvent

        backend = getattr(self.sandbox_executor, "backend", "local")
        sandbox_mode = getattr(self.sandbox_executor, "sandbox_mode", backend)
        emitter(
            AgentEvent(
                type="sandbox_preflight",
                session_id=str(payload.get("session_id") or payload.get("details", {}).get("session_id") or ""),
                tool_name="run_shell",
                message=(
                    "Checking Docker sandbox prerequisites."
                    if backend == "docker"
                    else "Using local compatibility executor; this is not secure isolation."
                ),
                details={
                    "token": token,
                    "command": payload.get("command"),
                    "sandbox_backend": backend,
                    "sandbox_mode": sandbox_mode,
                    "sandbox_isolation": "none-local-compat" if backend == "local" else sandbox_mode,
                    "phase": "preflight",
                },
            )
        )

    def _runtime_execution_context(self):
        if self.tool_registry is None:
            return None
        getter = getattr(self.tool_registry, "runtime_execution_context", None)
        if not callable(getter):
            return None
        return getter()

    def _set_runtime_execution_context(self, context: Any) -> None:
        if self.tool_registry is None:
            return
        setter = getattr(self.tool_registry, "_set_runtime_execution_context", None)
        if callable(setter):
            setter(context)

    def _check_runtime_guardrail(self, action: str):
        return check_runtime_guardrails(self._runtime_execution_context(), action)

    def _increment_runtime_counter(self, action: str):
        context = self._runtime_execution_context()
        if context is None:
            return None
        updated = increment_runtime_counter(context, action)
        self._set_runtime_execution_context(updated)
        return updated

    def _runtime_result_details(self, context: Any, *, guardrail_check: Any | None = None, action: str | None = None) -> dict[str, Any]:
        current = context or self._runtime_execution_context()
        details: dict[str, Any] = {"runtime_execution_context_present": current is not None}
        if current is not None:
            details["execution_session_id"] = current.session_id
            details["runtime_counters"] = runtime_counters_to_dict(current.counters)
        if guardrail_check is not None:
            key = f"{action}_guardrail_check" if action else "guardrail_check"
            details[key] = runtime_guardrail_check_to_dict(guardrail_check)
        return details

    def _runtime_guardrail_block_result(self, action: str, check: Any, *, token: str) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=f"Runtime guardrail blocked {action}: {check.reason}",
            is_error=True,
            details={
                "token": token,
                "runtime_guardrail_blocked": True,
                "guardrail_check": runtime_guardrail_check_to_dict(check),
                **self._runtime_result_details(None),
            },
        )

    def _stage_patch_candidate(self, store: PendingActionStore, shell_payload: dict[str, Any], completed: Any) -> dict[str, Any]:
        """Stage a separate approval action for a Docker sandbox patch candidate."""

        has_patch_metadata = completed.changed_files is not None or completed.patch_summary is not None or completed.patch is not None
        changed_files = completed.changed_files or []
        patch = completed.patch or ""
        structured_changes = normalize_structured_changes(completed.structured_changes)
        structured_digest = completed.structured_changes_digest or hash_structured_changes(structured_changes)
        if not changed_files:
            if not has_patch_metadata:
                return {"staged": False}
            return {"staged": False, "reason": "no changed files"}
        if completed.structured_changes_truncated:
            return {"staged": False, "reason": "structured changes truncated", "structured_changes_truncated": True}
        if completed.patch_truncated:
            return {"staged": False, "reason": "patch truncated", "patch_truncated": True}
        if not structured_changes and not patch.strip():
            return {"staged": False, "reason": "empty patch"}
        patch_guardrail = self._check_runtime_guardrail("patch_candidate")
        if patch_guardrail.allowed is False:
            return {
                "staged": False,
                "reason": patch_guardrail.reason,
                "patch_candidate_blocked": True,
                "runtime_guardrail_blocked": True,
                "guardrail_check": runtime_guardrail_check_to_dict(patch_guardrail),
                **self._runtime_result_details(None),
            }
        patch_digest = content_digest(patch)
        source_digest = content_digest(str(shell_payload.get("command") or ""))
        candidate_args = {
            "patch": patch,
            "changed_files": changed_files,
            "patch_summary": completed.patch_summary or "",
            "patch_digest": patch_digest,
            "source_shell_command_digest": source_digest,
            "source_shell_action_token": shell_payload.get("token"),
            "sandbox_backend": completed.backend,
            "sandbox_mode": completed.sandbox_mode,
            "patch_truncated": completed.patch_truncated,
            "structured_changes": structured_changes,
            "structured_changes_digest": structured_digest,
            "structured_changes_truncated": completed.structured_changes_truncated,
            **(
                {"write_scope": shell_payload.get("details", {}).get("write_scope")}
                if isinstance(shell_payload.get("details"), dict) and isinstance(shell_payload.get("details", {}).get("write_scope"), dict)
                else {}
            ),
        }
        candidate_args = attach_runtime_context_to_patch_candidate_args(candidate_args, self._runtime_execution_context())
        effect = build_patch_candidate_effect(
            tool_name=APPLY_PATCH_CANDIDATE_TOOL,
            permission_domain=PermissionDomain.EDIT,
            patch=candidate_args["patch"],
            changed_files=candidate_args["changed_files"],
            patch_summary=candidate_args["patch_summary"],
            source_shell_command_digest=candidate_args["source_shell_command_digest"],
            sandbox_backend=candidate_args["sandbox_backend"],
            sandbox_mode=candidate_args["sandbox_mode"],
            patch_truncated=candidate_args["patch_truncated"],
            structured_changes=candidate_args["structured_changes"],
            structured_changes_digest=candidate_args["structured_changes_digest"],
            structured_changes_truncated=candidate_args["structured_changes_truncated"],
            write_scope=candidate_args.get("write_scope") if isinstance(candidate_args.get("write_scope"), dict) else None,
        )
        payload = store.stage(
            action_type="apply_patch_candidate",
            details=candidate_args,
            effect=effect,
            origin={"source": "sandbox", "tool_name": APPLY_PATCH_CANDIDATE_TOOL, "kind": "patch_candidate"},
        )
        patch_context = self._increment_runtime_counter("patch_candidate")
        return {
            "staged": True,
            "token": payload["token"],
            "patch_digest": patch_digest,
            "patch_summary": completed.patch_summary or "",
            "changed_files": changed_files,
            "structured_changes_count": len(structured_changes),
            "structured_changes_digest": structured_digest,
            "structured_changes_truncated": completed.structured_changes_truncated,
            **self._runtime_result_details(patch_context, guardrail_check=patch_guardrail, action="patch_candidate"),
        }

    def _apply_patch_candidate_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate and atomically apply a staged sandbox patch candidate."""

        details = payload.get("details", {}) if isinstance(payload.get("details"), dict) else {}
        structured_changes = normalize_structured_changes(details.get("structured_changes"))
        scope_result = self._check_patch_candidate_write_scope(details, structured_changes)
        if scope_result.get("scope_blocked"):
            return scope_result
        if structured_changes:
            result = self._apply_structured_patch_candidate_payload(details, structured_changes)
        else:
            result = self._apply_unified_diff_patch_candidate_payload(details)
        if scope_result.get("scope_check") is not None:
            result["scope_check"] = scope_result["scope_check"]
        return result

    def _check_patch_candidate_write_scope(self, details: dict[str, Any], structured_changes: list[dict[str, Any]]) -> dict[str, Any]:
        """Check optional write_scope before acquiring locks or writing patch candidate changes."""

        raw_scope = details.get("write_scope")
        if raw_scope is None:
            return {
                "scope_check": write_scope_check_to_dict(check_structured_changes_against_write_scope(None, structured_changes)),
            }
        scope = write_scope_from_dict(raw_scope if isinstance(raw_scope, dict) else None)
        check = check_structured_changes_against_write_scope(scope, structured_changes)
        payload = write_scope_check_to_dict(check)
        if check.allowed is False:
            return {
                "applied": False,
                "atomic": True,
                "rollback_attempted": False,
                "rollback_succeeded": None,
                "partial_state_possible": False,
                "post_apply_validated": False,
                "lock_acquired": False,
                "lock_released": None,
                "scope_blocked": True,
                "scope_check": payload,
                "reason": check.reason,
                "apply_backend": "structured_changes" if structured_changes else "internal_unified_diff",
                "structured_changes_digest": details.get("structured_changes_digest"),
            }
        return {"scope_check": payload}

    def _apply_unified_diff_patch_candidate_payload(self, details: dict[str, Any]) -> dict[str, Any]:
        """Apply a legacy unified-diff patch candidate when structured changes are absent."""

        patch = str(details.get("patch") or "")
        patch_digest = str(details.get("patch_digest") or "")
        if not patch or not patch_digest:
            raise ValueError("Patch candidate is missing patch content or patch_digest.")
        if content_digest(patch) != patch_digest:
            raise ValueError("Patch candidate digest mismatch.")
        if bool(details.get("patch_truncated")):
            raise ValueError("Patch candidate is truncated and cannot be applied automatically.")
        files = self._parse_patch_files(patch)
        if not files:
            raise ValueError("Patch candidate contains no supported file changes.")
        statuses = {
            str(item.get("path")): str(item.get("status"))
            for item in details.get("changed_files", [])
            if isinstance(item, dict)
        }
        changed_files = list(details.get("changed_files") or [])
        snapshot: dict[str, dict[str, Any]] = {}
        changed_paths: list[str] = []
        lock_handle = None
        lock_details: dict[str, Any] = {}
        Lock, LockError, LockTimeout = _workspace_lock_types()
        try:
            self._validate_patch_targets(files, changed_files)
        except Exception as exc:
            return self._rollback_patch_apply_failure(snapshot, str(exc), post_apply_validated=False)
        try:
            lock_handle = Lock(self.workspace).acquire()
            lock_details = {
                "lock_acquired": True,
                "lock_released": None,
                "lock_path": str(Lock.RELATIVE_LOCK_PATH).replace("\\", "/"),
                "lock_wait_ms": lock_handle.wait_ms,
            }
        except LockTimeout as exc:
            return {
                "applied": False,
                "atomic": True,
                "rollback_attempted": False,
                "rollback_succeeded": None,
                "partial_state_possible": False,
                "post_apply_validated": False,
                "lock_acquired": False,
                "lock_released": None,
                "lock_timeout": True,
                "reason": str(exc) or "workspace apply lock timeout",
            }
        except LockError as exc:
            return {
                "applied": False,
                "atomic": True,
                "rollback_attempted": False,
                "rollback_succeeded": None,
                "partial_state_possible": False,
                "post_apply_validated": False,
                "lock_acquired": False,
                "lock_released": None,
                "lock_timeout": False,
                "reason": str(exc),
            }
        try:
            snapshot = self._snapshot_patch_targets(files)
            for item in files:
                target = self._validate_patch_path(item["path"])
                before = target.read_text(encoding="utf-8") if target.exists() else ""
                after = self._apply_candidate_file_patch(before, item["patch"])
                target.parent.mkdir(parents=True, exist_ok=True)
                if statuses.get(item["path"]) == "deleted":
                    if target.exists():
                        target.unlink()
                elif after == "" and target.exists() and self._patch_deletes_file(item["patch"]):
                    target.unlink()
                else:
                    target.write_text(after, encoding="utf-8")
                changed_paths.append(item["path"])
            self._validate_post_apply_changes(files, changed_files, changed_paths)
        except Exception as exc:
            result = self._rollback_patch_apply_failure(snapshot, str(exc), post_apply_validated=False)
            result.update(lock_details)
            return self._release_apply_lock(lock_handle, result)
        result = {
            "applied": True,
            "atomic": True,
            "changed_files": changed_files,
            "changed_paths": changed_paths,
            "apply_backend": "internal_unified_diff",
            "rollback_attempted": False,
            "post_apply_validated": True,
        }
        result.update(lock_details)
        return self._release_apply_lock(lock_handle, result)

    def _apply_structured_patch_candidate_payload(
        self,
        details: dict[str, Any],
        structured_changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply structured sandbox file changes with digest checks before writes."""

        expected_digest = str(details.get("structured_changes_digest") or "")
        actual_digest = hash_structured_changes(structured_changes)
        if not expected_digest:
            raise ValueError("Patch candidate is missing structured_changes_digest.")
        if actual_digest != expected_digest:
            raise ValueError("Structured changes digest mismatch.")
        if bool(details.get("structured_changes_truncated")):
            raise ValueError("Structured changes are truncated and cannot be applied automatically.")
        changed_files = list(details.get("changed_files") or [])
        files = [{"path": change["path"]} for change in structured_changes]
        snapshot: dict[str, dict[str, Any]] = {}
        changed_paths: list[str] = []
        lock_handle = None
        lock_details: dict[str, Any] = {}
        Lock, LockError, LockTimeout = _workspace_lock_types()
        try:
            self._validate_structured_changes(structured_changes, changed_files)
        except Exception as exc:
            result = self._rollback_patch_apply_failure(snapshot, str(exc), post_apply_validated=False)
            result["apply_backend"] = "structured_changes"
            result["structured_changes_digest"] = expected_digest
            return result
        try:
            lock_handle = Lock(self.workspace).acquire()
            lock_details = {
                "lock_acquired": True,
                "lock_released": None,
                "lock_path": str(Lock.RELATIVE_LOCK_PATH).replace("\\", "/"),
                "lock_wait_ms": lock_handle.wait_ms,
            }
        except LockTimeout as exc:
            return {
                "applied": False,
                "atomic": True,
                "rollback_attempted": False,
                "rollback_succeeded": None,
                "partial_state_possible": False,
                "post_apply_validated": False,
                "lock_acquired": False,
                "lock_released": None,
                "lock_timeout": True,
                "reason": str(exc) or "workspace apply lock timeout",
                "apply_backend": "structured_changes",
                "structured_changes_digest": expected_digest,
            }
        except LockError as exc:
            return {
                "applied": False,
                "atomic": True,
                "rollback_attempted": False,
                "rollback_succeeded": None,
                "partial_state_possible": False,
                "post_apply_validated": False,
                "lock_acquired": False,
                "lock_released": None,
                "lock_timeout": False,
                "reason": str(exc),
                "apply_backend": "structured_changes",
                "structured_changes_digest": expected_digest,
            }
        try:
            snapshot = self._snapshot_patch_targets(files)
            for change in structured_changes:
                target = self._validate_patch_path(str(change["path"]))
                self._apply_one_structured_change(target, change)
                changed_paths.append(str(change["path"]))
            self._validate_post_apply_changes(files, changed_files, changed_paths)
        except Exception as exc:
            result = self._rollback_patch_apply_failure(snapshot, str(exc), post_apply_validated=False)
            result.update(lock_details)
            result["apply_backend"] = "structured_changes"
            result["structured_changes_digest"] = expected_digest
            return self._release_apply_lock(lock_handle, result)
        result = {
            "applied": True,
            "atomic": True,
            "changed_files": changed_files,
            "changed_paths": changed_paths,
            "apply_backend": "structured_changes",
            "structured_changes_digest": expected_digest,
            "rollback_attempted": False,
            "post_apply_validated": True,
        }
        result.update(lock_details)
        return self._release_apply_lock(lock_handle, result)

    def _validate_structured_changes(self, structured_changes: list[dict[str, Any]], changed_files: list[Any]) -> None:
        """Validate structured change metadata before taking the apply lock."""

        self._validate_patch_targets([{"path": change["path"]} for change in structured_changes], changed_files)
        for change in structured_changes:
            change_type = str(change.get("change_type") or "")
            if change_type not in {"added", "modified", "deleted"}:
                raise ValueError(f"Unsupported structured change type: {change_type}")
            if change.get("binary") or change.get("truncated"):
                raise ValueError("structured change is binary or truncated and cannot be auto-applied")
            if change_type in {"added", "modified"} and change.get("content_text") is None:
                raise ValueError(f"Structured change is missing content_text: {change.get('path')}")
            if change_type == "added" and change.get("old_digest") is not None:
                raise ValueError(f"Added structured change must not include old_digest: {change.get('path')}")
            if change_type == "modified" and (not change.get("old_digest") or not change.get("new_digest")):
                raise ValueError(f"Modified structured change must include old_digest and new_digest: {change.get('path')}")
            if change_type == "deleted" and change.get("new_digest") is not None:
                raise ValueError(f"Deleted structured change must not include new_digest: {change.get('path')}")

    def _apply_one_structured_change(self, target: Path, change: dict[str, Any]) -> None:
        """Apply one structured file change and verify old/new byte digests."""

        change_type = str(change.get("change_type") or "")
        path_label = str(change.get("path") or "")
        old_digest = change.get("old_digest")
        new_digest = change.get("new_digest")
        existed = target.exists()
        current_digest = bytes_digest(target.read_bytes()) if existed else None
        if change_type == "added":
            if existed:
                raise ValueError(f"Structured add target already exists: {path_label}")
            content = self._structured_change_content_bytes(change)
            if bytes_digest(content) != new_digest:
                raise ValueError(f"Structured change new_digest mismatch before write: {path_label}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        elif change_type == "modified":
            if not existed:
                raise ValueError(f"Structured modify target does not exist: {path_label}")
            if current_digest != old_digest:
                raise ValueError(f"Structured change old_digest mismatch: {path_label}")
            content = self._structured_change_content_bytes(change)
            if bytes_digest(content) != new_digest:
                raise ValueError(f"Structured change new_digest mismatch before write: {path_label}")
            target.write_bytes(content)
        elif change_type == "deleted":
            if not existed:
                raise ValueError(f"Structured delete target does not exist: {path_label}")
            if current_digest != old_digest:
                raise ValueError(f"Structured change old_digest mismatch: {path_label}")
            target.unlink()
            return
        else:
            raise ValueError(f"Unsupported structured change type: {change_type}")
        if bytes_digest(target.read_bytes()) != new_digest:
            raise ValueError(f"Structured change new_digest mismatch after write: {path_label}")

    @staticmethod
    def _structured_change_content_bytes(change: dict[str, Any]) -> bytes:
        """Encode structured change content with its declared text encoding."""

        encoding = str(change.get("content_encoding") or "utf-8")
        content_text = change.get("content_text")
        if not isinstance(content_text, str):
            raise ValueError(f"Structured change content_text must be text: {change.get('path')}")
        return content_text.encode(encoding)

    @staticmethod
    def _release_apply_lock(lock_handle: Any, result: dict[str, Any]) -> dict[str, Any]:
        """Release a workspace apply lock and record cleanup details in the result."""

        if lock_handle is None:
            return result
        try:
            lock_handle.release()
        except Exception as exc:  # noqa: BLE001
            result["lock_released"] = False
            result["lock_release_error"] = str(exc)
            result["manual_cleanup_required"] = True
            return result
        result["lock_released"] = True
        return result

    def _validate_patch_targets(self, files: list[dict[str, str]], changed_files: list[Any]) -> None:
        """Validate all approved patch targets before any workspace write occurs."""

        patch_paths = set()
        for item in files:
            self._validate_patch_path(item["path"])
            patch_paths.add(self._normalize_patch_path_label(item["path"]))
        if not patch_paths:
            raise ValueError("Patch candidate contains no target paths.")
        changed_paths = set()
        for item in changed_files:
            if not isinstance(item, dict):
                raise ValueError("Patch candidate changed_files must contain objects.")
            raw_path = str(item.get("path") or "")
            self._validate_patch_path(raw_path)
            changed_paths.add(self._normalize_patch_path_label(raw_path))
        if changed_paths and not patch_paths.issubset(changed_paths):
            unexpected = sorted(patch_paths - changed_paths)
            raise ValueError(f"Patch modifies paths outside approved changed_files: {', '.join(unexpected)}")

    def _snapshot_patch_targets(self, files: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
        """Capture pre-apply file state for the patch target set only."""

        snapshot: dict[str, dict[str, Any]] = {}
        for item in files:
            raw_path = self._normalize_patch_path_label(item["path"])
            target = self._validate_patch_path(raw_path)
            if raw_path in snapshot:
                continue
            existed = target.exists()
            is_symlink = target.is_symlink() if existed else False
            content = b""
            mode = None
            if existed:
                stat_result = target.lstat()
                if stat_result.st_size > MAX_PATCH_SNAPSHOT_BYTES:
                    raise ValueError(
                        f"Patch target is too large to snapshot safely: {raw_path} "
                        f"({stat_result.st_size} bytes > {MAX_PATCH_SNAPSHOT_BYTES} bytes)"
                    )
                if is_symlink:
                    raise ValueError(f"Patch target is a symlink and cannot be snapshotted safely: {raw_path}")
                if target.is_dir():
                    raise ValueError(f"Patch target is a directory and cannot be patched: {raw_path}")
                content = target.read_bytes()
                mode = stat_result.st_mode
            snapshot[raw_path] = {
                "path": raw_path,
                "target": target,
                "existed": existed,
                "content": content,
                "mode": mode,
                "is_symlink": is_symlink,
            }
        return snapshot

    def _restore_snapshot(self, snapshot: dict[str, dict[str, Any]]) -> None:
        """Restore files captured by _snapshot_patch_targets after a failed apply."""

        for item in snapshot.values():
            target = item["target"]
            if item["existed"]:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(item["content"])
                mode = item.get("mode")
                if mode is not None:
                    try:
                        target.chmod(mode)
                    except OSError:
                        pass
            elif target.exists():
                if target.is_dir():
                    raise ValueError(f"Rollback cannot remove directory created at patch target: {item['path']}")
                target.unlink()

    def _rollback_patch_apply_failure(
        self,
        snapshot: dict[str, dict[str, Any]],
        reason: str,
        *,
        post_apply_validated: bool,
    ) -> dict[str, Any]:
        """Build a patch-apply failure result and restore pre-apply state when needed."""

        if not snapshot:
            return {
                "applied": False,
                "atomic": True,
                "rollback_attempted": False,
                "rollback_succeeded": None,
                "partial_state_possible": False,
                "post_apply_validated": post_apply_validated,
                "reason": reason,
            }
        try:
            self._restore_snapshot(snapshot)
        except Exception as rollback_exc:
            return {
                "applied": False,
                "atomic": False,
                "rollback_attempted": True,
                "rollback_succeeded": False,
                "partial_state_possible": True,
                "post_apply_validated": post_apply_validated,
                "reason": reason,
                "rollback_error": str(rollback_exc),
            }
        return {
            "applied": False,
            "atomic": True,
            "rollback_attempted": True,
            "rollback_succeeded": True,
            "partial_state_possible": False,
            "post_apply_validated": post_apply_validated,
            "reason": reason,
        }

    def _validate_post_apply_changes(
        self,
        files: list[dict[str, str]],
        changed_files: list[Any],
        changed_paths: list[str],
    ) -> None:
        """Re-check the applied path set after writes but before consuming approval."""

        expected = {
            self._normalize_patch_path_label(str(item.get("path") or ""))
            for item in changed_files
            if isinstance(item, dict)
        }
        actual = {self._normalize_patch_path_label(path) for path in changed_paths}
        patch_paths = {self._normalize_patch_path_label(item["path"]) for item in files}
        for raw_path in actual | patch_paths | expected:
            self._validate_patch_path(raw_path)
        if expected and not actual.issubset(expected):
            unexpected = sorted(actual - expected)
            raise ValueError(f"Patch applied unexpected paths: {', '.join(unexpected)}")
        if actual != patch_paths:
            missing = sorted(patch_paths - actual)
            extra = sorted(actual - patch_paths)
            raise ValueError(f"Post-apply path validation failed; missing={missing}, extra={extra}")

    def _validate_patch_path(self, raw_path: str) -> Path:
        """Normalize and validate one patch path before writing the workspace."""

        normalized = raw_path.replace("\\", "/").strip()
        if not normalized:
            raise ValueError("Patch path is empty.")
        if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized) or normalized.startswith("//"):
            raise ValueError(f"Patch path must be relative: {raw_path}")
        parts: list[str] = []
        for part in normalized.split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                raise ValueError(f"Patch path traversal is not allowed: {raw_path}")
            parts.append(part)
        if not parts:
            raise ValueError(f"Patch path is invalid: {raw_path}")
        relative = Path(*parts)
        target = (self.workspace / relative).resolve()
        workspace = self.workspace.resolve()
        if target != workspace and workspace not in target.parents:
            raise ValueError(f"Patch path escapes workspace: {raw_path}")
        if self.policy_evaluator.is_protected(target):
            raise ValueError(f"Patch path is protected: {raw_path}")
        probe = target
        while probe != workspace:
            if probe.exists() and probe.is_symlink():
                raise ValueError(f"Patch path crosses a symlink: {raw_path}")
            probe = probe.parent
        return target

    @staticmethod
    def _normalize_patch_path_label(raw_path: str) -> str:
        """Return a stable relative patch path label using POSIX separators."""

        normalized = raw_path.replace("\\", "/").strip()
        parts: list[str] = []
        for part in normalized.split("/"):
            if part in {"", "."}:
                continue
            parts.append(part)
        return Path(*parts).as_posix() if parts else normalized

    def _parse_patch_files(self, patch: str) -> list[dict[str, str]]:
        """Parse the limited unified-diff format produced by DockerSandboxExecutor."""

        lines = patch.splitlines()
        files: list[dict[str, str]] = []
        index = 0
        while index < len(lines):
            if not lines[index].startswith("--- "):
                index += 1
                continue
            before_header = lines[index][4:].strip()
            if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
                raise ValueError("Patch file header is incomplete.")
            after_header = lines[index + 1][4:].strip()
            file_start = index
            index += 2
            while index < len(lines) and not lines[index].startswith("--- "):
                index += 1
            file_patch = "\n".join(lines[file_start:index]) + "\n"
            path = self._patch_header_path(after_header if after_header != "/dev/null" else before_header)
            self._validate_patch_path(path)
            files.append({"path": path, "patch": file_patch})
        return files

    @staticmethod
    def _apply_candidate_file_patch(before: str, patch: str) -> str:
        """Apply one bounded unified diff file patch produced by the sandbox executor."""

        original_lines = before.splitlines()
        output: list[str] = []
        cursor = 0
        lines = patch.splitlines()
        index = 0
        saw_hunk = False
        while index < len(lines):
            line = lines[index]
            hunk_match = UNIFIED_HUNK_RE.match(line)
            if not hunk_match:
                index += 1
                continue
            saw_hunk = True
            old_start = int(hunk_match.group("old_start"))
            hunk_cursor = max(old_start - 1, 0)
            output.extend(original_lines[cursor:hunk_cursor])
            cursor = hunk_cursor
            index += 1
            while index < len(lines):
                hunk_line = lines[index]
                if UNIFIED_HUNK_RE.match(hunk_line):
                    break
                if hunk_line == r"\ No newline at end of file":
                    index += 1
                    continue
                prefix = hunk_line[:1]
                text = hunk_line[1:] if hunk_line else ""
                if prefix == " ":
                    if cursor >= len(original_lines) or original_lines[cursor] != text:
                        raise ValueError(f"Patch context did not match file near line {cursor + 1}.")
                    output.append(text)
                    cursor += 1
                elif prefix == "-":
                    if cursor >= len(original_lines) or original_lines[cursor] != text:
                        raise ValueError(f"Patch deletion did not match file near line {cursor + 1}.")
                    cursor += 1
                elif prefix == "+":
                    output.append(text)
                else:
                    raise ValueError(f"Unsupported patch line: {hunk_line}")
                index += 1
        if not saw_hunk:
            raise ValueError("Patch candidate must contain at least one unified diff hunk.")
        output.extend(original_lines[cursor:])
        text = "\n".join(output)
        if output:
            text += "\n"
        return text

    @staticmethod
    def _patch_header_path(header: str) -> str:
        """Normalize a unified diff file header path."""

        path = header.strip().replace("\\", "/")
        if path.startswith("a/") or path.startswith("b/"):
            return path[2:]
        return path

    @staticmethod
    def _patch_deletes_file(patch: str) -> bool:
        """Return whether every changed line in a file patch is a deletion."""

        has_deletion = False
        has_addition = False
        for line in patch.splitlines():
            if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("@@"):
                continue
            if line.startswith("-"):
                has_deletion = True
            elif line.startswith("+"):
                has_addition = True
        return has_deletion and not has_addition

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
            if isinstance(error, DockerSandboxPreflightError):
                details.update(error.details)
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

    def _record_patch_apply_failure(
        self,
        store: PendingActionStore,
        token: str,
        effect: dict[str, Any],
        apply_result: dict[str, Any],
    ) -> ToolExecutionResult:
        """Record a failed patch candidate apply with rollback/atomicity details."""

        reason = str(apply_result.get("reason") or "Patch candidate apply failed.")
        updated = store.load(token)
        updated["lifecycle"] = self._lifecycle("execution_failed", "patch_apply_failed", reason)
        store.save(token, updated)
        audit = store.write_audit_record(
            token,
            lifecycle_state="execution_failed",
            failure_reason_code="patch_apply_failed",
            failure_reason_detail=reason,
        )
        payload_details = updated.get("details") if isinstance(updated.get("details"), dict) else {}
        details = {
            **apply_result,
            "token": token,
            "effect": effect,
            "approval_grant": updated.get("approval_grant"),
            "lifecycle": updated["lifecycle"],
            "latest_audit": audit,
            "failure_kind": "execution_failed",
            "patch_digest": payload_details.get("patch_digest"),
            "sandbox_backend": payload_details.get("sandbox_backend"),
            "sandbox_mode": payload_details.get("sandbox_mode"),
            "source_shell_command_digest": payload_details.get("source_shell_command_digest"),
            "source_shell_action_token": payload_details.get("source_shell_action_token"),
            "apply_backend": apply_result.get("apply_backend", "internal_unified_diff"),
            "structured_changes_digest": apply_result.get("structured_changes_digest") or payload_details.get("structured_changes_digest"),
        }
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=f"Patch candidate apply failed: {reason}",
            is_error=True,
            details=details,
        )

    @staticmethod
    def _shell_failure_details(failure_detail: str) -> dict[str, Any]:
        code_match = re.search(r"PowerShell exited with code (?P<code>-?\d+)", failure_detail)
        if not code_match:
            return {"command_failed": True}
        code = int(code_match.group("code"))
        match = re.search(
            r"PowerShell exited with code (?P<code>-?\d+)\nstdout:\n(?P<stdout>.*?)(?:\nstderr:\n(?P<stderr>.*))?\Z",
            failure_detail,
            flags=re.DOTALL,
        )
        if not match:
            return {"command_failed": True, "exit_code": code, "returncode": code}
        stdout = (match.group("stdout") or "").strip()
        stderr = (match.group("stderr") or "").strip()
        return {
            "command_failed": True,
            "exit_code": code,
            "returncode": code,
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
        if action_type == "apply_patch_candidate":
            details = payload.get("details", {})
            if not isinstance(details, dict):
                raise ValueError("Approval invalidated: patch candidate details are missing.")
            patch = str(details.get("patch") or "")
            changed_files = details.get("changed_files") or []
            effect = build_patch_candidate_effect(
                tool_name=stored_effect["tool_name"],
                permission_domain=stored_effect["permission_domain"],
                patch=patch,
                changed_files=changed_files,
                patch_summary=str(details.get("patch_summary") or ""),
                source_shell_command_digest=str(details.get("source_shell_command_digest") or ""),
                sandbox_backend=str(details.get("sandbox_backend") or ""),
                sandbox_mode=str(details.get("sandbox_mode") or ""),
                patch_truncated=bool(details.get("patch_truncated")),
                structured_changes=normalize_structured_changes(details.get("structured_changes")),
                structured_changes_digest=str(details.get("structured_changes_digest") or ""),
                structured_changes_truncated=bool(details.get("structured_changes_truncated")),
                write_scope=details.get("write_scope") if isinstance(details.get("write_scope"), dict) else None,
                effect_id=stored_effect["effect_id"],
                created_at=stored_effect["created_at"],
            )
            if str(details.get("patch_digest") or "") != effect["normalized_arguments"]["patch_digest"]:
                raise ValueError("Approval invalidated: patch digest changed after approval.")
            if "structured_changes_digest" in details and str(details.get("structured_changes_digest") or "") != effect["normalized_arguments"]["structured_changes_digest"]:
                raise ValueError("Approval invalidated: structured changes digest changed after approval.")
            stored_write_scope = stored_effect.get("normalized_arguments", {}).get("write_scope")
            current_write_scope = effect["normalized_arguments"].get("write_scope")
            if stored_write_scope != current_write_scope:
                raise ValueError("Approval invalidated: write scope changed after approval.")
            return effect
        if action_type == "attachment_import":
            details = payload.get("details", {})
            attachment_id = str(details.get("attachment_id") or "")
            session_id = str(details.get("session_id") or "")
            target_path = str(details.get("target_path") or "")
            if not attachment_id or not session_id or not target_path:
                raise ValueError("Approval invalidated: attachment import details are incomplete.")
            from pp_agent.attachments.service import AttachmentService

            record = AttachmentService(self.workspace)._require_active(session_id, attachment_id)
            return AttachmentWorkspaceImporter(self.workspace).build_import_effect(
                record,
                Path(target_path),
                overwrite=bool(details.get("overwrite", False)),
                effect_id=stored_effect["effect_id"],
                created_at=stored_effect["created_at"],
            )
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
