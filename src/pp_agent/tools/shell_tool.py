from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any
from importlib import import_module

from pp_agent.domain import ToolSpec
from pp_agent.sandbox.base import SandboxExecutor, SandboxRunRequest, SandboxRunResult
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.tools.base import BaseTool, ToolExecutionResult
from pp_agent.tools.effects import build_shell_effect
from pp_agent.tools.policy import PermissionDomain

SHELL_OUTPUT_PREVIEW_MAX_CHARS = 8 * 1024
TEST_TARGET_FORBIDDEN_CHARS_RE = re.compile(r"[;&|`$<>:\"'\s]")


def default_local_sandbox_executor() -> SandboxExecutor:
    """Resolve the compatibility local executor without importing backend modules at tools import time."""

    return import_module("pp_agent.sandbox.local").LocalSandboxExecutor()


def shell_output(result: SandboxRunResult) -> str:
    """Combine stdout and stderr the same way the legacy PowerShell tool did."""

    return (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")


def build_pytest_command(
    *,
    workspace: Path,
    target: str,
    quiet: bool = True,
    runner: str = "python",
    extra_args: list[str] | None = None,
) -> tuple[str, str]:
    """Return a safe workspace-relative pytest command and normalized target."""

    raw_target = str(target or "").strip()
    if not raw_target:
        raise ValueError("pytest target is required.")
    target_path = Path(raw_target)
    if target_path.is_absolute() or target_path.drive:
        raise ValueError("pytest target must be a workspace-relative path.")
    if TEST_TARGET_FORBIDDEN_CHARS_RE.search(raw_target) or "$(" in raw_target:
        raise ValueError("pytest target contains shell metacharacters.")
    if any(part in {"..", ""} for part in target_path.parts):
        raise ValueError("pytest target must not escape the workspace.")
    resolved = (workspace / target_path).resolve()
    workspace_root = workspace.resolve()
    if resolved != workspace_root and workspace_root not in resolved.parents:
        raise ValueError("pytest target must stay inside the workspace.")
    relative = resolved.relative_to(workspace_root).as_posix()
    normalized_runner = str(runner or "python").strip()
    if normalized_runner in {"python", "python3", "py"}:
        command = f"{normalized_runner} -m pytest {relative}"
    elif normalized_runner == "pytest":
        command = f"pytest {relative}"
    else:
        raise ValueError("Unsupported pytest runner.")
    if quiet:
        command += " -q"
    if extra_args:
        command += " " + " ".join(str(arg) for arg in extra_args)
    return command, relative


def _truncate_shell_stream(text: str, *, max_chars: int = SHELL_OUTPUT_PREVIEW_MAX_CHARS) -> tuple[str, bool, int]:
    value = str(text or "")
    chars = len(value)
    if chars <= max_chars:
        return value, False, chars
    omitted = chars - max_chars
    return f"{value[:max_chars]}\n[truncated {omitted} chars]", True, chars


def shell_execution_result_details(
    result: SandboxRunResult,
    *,
    duration_seconds: float | None = None,
    max_chars: int = SHELL_OUTPUT_PREVIEW_MAX_CHARS,
) -> dict[str, Any]:
    """Return the bounded, trace-safe command result contract for shell execution."""

    stdout, stdout_truncated, stdout_chars = _truncate_shell_stream(result.stdout or "", max_chars=max_chars)
    stderr, stderr_truncated, stderr_chars = _truncate_shell_stream(result.stderr or "", max_chars=max_chars)
    details: dict[str, Any] = {
        "returncode": result.returncode,
        "exit_code": result.returncode,
        "timed_out": bool(result.timed_out),
        "backend": result.backend,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_chars": stdout_chars,
        "stderr_chars": stderr_chars,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "stdout_preview_max_chars": max_chars,
        "stderr_preview_max_chars": max_chars,
    }
    if duration_seconds is not None:
        details["duration_seconds"] = max(float(duration_seconds), 0.0)
    details.update(sandbox_result_details(result))
    return details


def shell_output_from_result_details(details: dict[str, Any]) -> str:
    """Combine bounded stdout/stderr previews from shell result details."""

    stdout = str(details.get("stdout") or "")
    stderr = str(details.get("stderr") or "")
    return stdout + (("\n" + stderr) if stderr else "")


class ShellExecutionError(RuntimeError):
    """Process failure carrying bounded shell result details."""

    def __init__(self, message: str, *, result_details: dict[str, Any]) -> None:
        super().__init__(message)
        self.result_details = result_details


def sandbox_result_error(
    result: SandboxRunResult,
    *,
    stream_labels: bool = True,
    duration_seconds: float | None = None,
) -> Exception:
    """Render sandbox process failures in the existing shell failure format."""

    result_details = shell_execution_result_details(result, duration_seconds=duration_seconds)
    if result.timed_out:
        return ShellExecutionError(
            f"PowerShell timed out after sandbox execution with code {result.returncode}",
            result_details=result_details,
        )
    if not stream_labels:
        return ShellExecutionError(
            f"PowerShell exited with code {result.returncode}\n{shell_output_from_result_details(result_details)}".strip(),
            result_details=result_details,
        )
    return ShellExecutionError(
        "PowerShell exited with code "
        f"{result.returncode}\n"
        f"stdout:\n{result_details.get('stdout') or ''}\n"
        f"stderr:\n{result_details.get('stderr') or ''}".strip(),
        result_details=result_details,
    )


def sandbox_result_details(result: SandboxRunResult) -> dict[str, Any]:
    """Return optional sandbox metadata that is safe to expose in tool details."""

    details: dict[str, Any] = {
        "sandbox_backend": result.backend,
        "sandbox_mode": result.sandbox_mode,
        "network_access": result.network_access,
        "network_allowlist": result.network_allowlist or [],
        "network_policy_mode": result.network_policy_mode,
        "network_enforced": result.network_enforced,
        "writable_roots": result.writable_roots,
        "sandbox_isolation": "none-local-compat" if result.backend == "local" else result.sandbox_mode,
    }
    if result.changed_files is not None:
        details["changed_files"] = result.changed_files
    if result.patch_summary is not None:
        details["patch_summary"] = result.patch_summary
    if result.patch is not None:
        details["patch"] = result.patch
    if result.changed_files is not None or result.patch_summary is not None or result.patch is not None:
        details["patch_truncated"] = result.patch_truncated
    if result.structured_changes is not None:
        details["structured_changes"] = result.structured_changes
        details["structured_changes_count"] = len(result.structured_changes)
    if result.structured_changes_digest is not None:
        details["structured_changes_digest"] = result.structured_changes_digest
    if result.structured_changes is not None or result.structured_changes_digest is not None:
        details["structured_changes_truncated"] = result.structured_changes_truncated
    return details


def _stable_json_digest(payload: dict[str, Any]) -> str:
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _workspace_relative_cwd(workspace: Path, cwd: Path) -> str:
    try:
        relative = cwd.resolve().relative_to(workspace.resolve())
    except ValueError:
        return str(cwd.resolve())
    return "." if str(relative) == "." else relative.as_posix()


def command_proposal_digest(proposal: dict[str, Any]) -> str:
    stable = {key: value for key, value in proposal.items() if key != "proposal_digest"}
    return _stable_json_digest(stable)


def build_command_proposal(
    *,
    workspace: Path,
    command: str,
    timeout_seconds: int,
    effect: dict[str, Any],
    action_type: str = "run_shell",
    shell: str = "powershell",
    requires_approval: bool = True,
) -> dict[str, Any]:
    analysis = effect.get("analysis") or {}
    normalized_arguments = effect.get("normalized_arguments") or {}
    cwd = workspace.resolve()
    risk_class = str(analysis.get("risk_class") or normalized_arguments.get("risk_class") or "unknown")
    proposal = {
        "kind": "command_proposal",
        "version": 1,
        "action_type": action_type,
        "command": str(command),
        "normalized_command": str(normalized_arguments.get("normalized_command") or command),
        "command_head": str(normalized_arguments.get("command_head") or analysis.get("command_head") or ""),
        "cwd": str(cwd),
        "workspace_relative_cwd": _workspace_relative_cwd(workspace, cwd),
        "shell": shell,
        "timeout_seconds": int(timeout_seconds),
        "risk_class": risk_class,
        "risk_level": risk_class,
        "risk_summary": str(analysis.get("summary") or effect.get("summary") or ""),
        "flags": list(analysis.get("flags") or []),
        "requests_network": bool(analysis.get("requests_network", False)),
        "destructive_hint": bool(analysis.get("destructive_hint", False)),
        "touches_workspace": bool(analysis.get("touches_workspace", False)),
        "touches_external": bool(analysis.get("touches_external", False)),
        "requires_approval": bool(requires_approval),
        "effect_payload_digest": str(effect.get("payload_digest") or ""),
        "preview": {
            "warning_flags": list(analysis.get("flags") or []),
            "policy_notes": [],
        },
    }
    proposal["proposal_digest"] = command_proposal_digest(proposal)
    return proposal


def command_preview_from_command_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(proposal)
    normalized["proposal_digest"] = command_proposal_digest(normalized)
    preview = dict(normalized.get("preview") or {})
    return {
        "kind": "command_preview",
        "action_type": normalized.get("action_type"),
        "command": normalized.get("command"),
        "normalized_command": normalized.get("normalized_command"),
        "cwd": normalized.get("cwd"),
        "workspace_relative_cwd": normalized.get("workspace_relative_cwd"),
        "shell": normalized.get("shell"),
        "timeout_seconds": normalized.get("timeout_seconds"),
        "risk_class": normalized.get("risk_class"),
        "risk_level": normalized.get("risk_level"),
        "risk_summary": normalized.get("risk_summary"),
        "requires_approval": bool(normalized.get("requires_approval", True)),
        "proposal_digest": normalized["proposal_digest"],
        "effect_payload_digest": normalized.get("effect_payload_digest"),
        "warning_flags": list(preview.get("warning_flags") or normalized.get("flags") or []),
        "policy_notes": list(preview.get("policy_notes") or []),
        "requests_network": bool(normalized.get("requests_network", False)),
        "destructive_hint": bool(normalized.get("destructive_hint", False)),
        "touches_external": bool(normalized.get("touches_external", False)),
    }


class PowerShellTool(BaseTool):
    def __init__(
        self,
        workspace,
        policy_evaluator=None,
        default_timeout_seconds: int = 30,
        sandbox_executor: SandboxExecutor | None = None,
    ) -> None:
        super().__init__(workspace, policy_evaluator=policy_evaluator)
        self.default_timeout_seconds = default_timeout_seconds
        self.sandbox_executor = sandbox_executor or default_local_sandbox_executor()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="run_shell",
            description="Stage a PowerShell command for host-side approval.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                },
                "required": ["command"],
            },
            requires_confirmation=True,
            permission_domain=PermissionDomain.BASH,
            sensitive=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        timeout = int(arguments.get("timeout_seconds", self.default_timeout_seconds))
        command = arguments["command"]
        self.enforce_policy_for_command(PermissionDomain.BASH, command)
        store = PendingActionStore(self.pending_root())
        effect = build_shell_effect(
            tool_name=self.spec.name,
            permission_domain=PermissionDomain.BASH,
            command=command,
            timeout_seconds=timeout,
            workspace=self.workspace,
        )
        proposal = build_command_proposal(
            workspace=self.workspace,
            command=command,
            timeout_seconds=timeout,
            effect=effect,
        )
        payload = store.stage(
            action_type="run_shell",
            command=command,
            details={"timeout_seconds": timeout, "command_proposal": proposal},
            effect=effect,
            origin={"source": "tool", "tool_name": self.spec.name, "kind": "shell"},
        )
        payload_details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        stored_proposal = payload_details.get("command_proposal") if isinstance(payload_details, dict) else proposal
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=f"Staged shell command. Approve with token {payload['token']}",
            details={
                "token": payload["token"],
                "command": command,
                "timeout_seconds": timeout,
                "staged": True,
                "effect": effect,
                "command_proposal": stored_proposal,
                "proposal_digest": stored_proposal.get("proposal_digest") if isinstance(stored_proposal, dict) else None,
            },
        )

    def _run(self, command: str, timeout: int) -> ToolExecutionResult:
        completed = self.sandbox_executor.run(
            SandboxRunRequest(command=command, cwd=Path(self.workspace), timeout_seconds=timeout)
        )
        output = shell_output(completed)
        if completed.returncode != 0:
            raise sandbox_result_error(completed, stream_labels=False)
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=output.strip() or "[no output]",
            details={
                "timeout_seconds": timeout,
                "returncode": completed.returncode,
                "command": command,
                **sandbox_result_details(completed),
            },
        )


class StageTestCommandTool(BaseTool):
    def __init__(
        self,
        workspace,
        policy_evaluator=None,
        default_timeout_seconds: int = 30,
        sandbox_executor: SandboxExecutor | None = None,
    ) -> None:
        super().__init__(workspace, policy_evaluator=policy_evaluator)
        self.default_timeout_seconds = default_timeout_seconds
        self.sandbox_executor = sandbox_executor or default_local_sandbox_executor()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="stage_test_command",
            description="Stage a focused pytest command for host-side approval. This only creates a run_shell pending action and never executes tests directly.",
            parameters={
                "type": "object",
                "properties": {
                    "framework": {"type": "string", "enum": ["pytest"]},
                    "target": {"type": "string"},
                    "reason": {"type": "string"},
                    "quiet": {"type": "boolean"},
                    "timeout_seconds": {"type": "integer"},
                },
                "required": ["framework", "target"],
            },
            requires_confirmation=True,
            permission_domain=PermissionDomain.BASH,
            sensitive=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        framework = str(arguments.get("framework") or "pytest").strip().lower()
        if framework != "pytest":
            raise ValueError("stage_test_command currently only supports pytest.")
        quiet = bool(arguments.get("quiet", True))
        internal = arguments.get("_internal")
        runner = "python"
        extra_args: list[str] = []
        provenance_details: dict[str, Any] | None = None
        if isinstance(internal, dict):
            runner = str(internal.get("runner") or "python").strip()
            provenance = internal.get("provenance")
            if isinstance(provenance, dict):
                artifact = str(provenance.get("artifact_relative_path") or "")
                nonce = str(provenance.get("nonce") or "")
                logical_digest = str(provenance.get("logical_command_digest") or "")
                if not artifact or not nonce or not logical_digest:
                    raise ValueError("pytest provenance arguments are incomplete.")
                extra_args = [
                    "-p",
                    "pp_agent.coding.pytest_provenance_plugin",
                    "--pp-echo-pytest-provenance-file",
                    artifact,
                    "--pp-echo-pytest-provenance-nonce",
                    nonce,
                    "--pp-echo-pytest-logical-command-digest",
                    logical_digest,
                ]
                provenance_details = {
                    "schema_version": provenance.get("schema_version"),
                    "plugin_id": provenance.get("plugin_id"),
                    "plugin_version": provenance.get("plugin_version"),
                    "nonce": nonce,
                    "logical_command_digest": logical_digest,
                    "artifact_relative_path": artifact,
                }
        command, normalized_target = build_pytest_command(
            workspace=self.workspace,
            target=str(arguments.get("target") or ""),
            quiet=quiet,
            runner=runner,
            extra_args=extra_args,
        )
        timeout = int(arguments.get("timeout_seconds", self.default_timeout_seconds))
        result = PowerShellTool(
            self.workspace,
            policy_evaluator=self.policy_evaluator,
            default_timeout_seconds=self.default_timeout_seconds,
            sandbox_executor=self.sandbox_executor,
        ).execute({"command": command, "timeout_seconds": timeout})
        details = dict(result.details or {})
        helper_proposal = {
            "kind": "test_command_recommendation",
            "version": 1,
            "intent": "pytest",
            "target": normalized_target,
            "reason": str(arguments.get("reason") or ""),
            "generated_command": command,
            "delegates_to": "run_shell",
            "requires_approval": True,
        }
        store = PendingActionStore(self.pending_root())
        payload = store.load(str(details["token"]))
        payload_details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        payload_details["test_command_proposal"] = helper_proposal
        if provenance_details is not None:
            payload_details["pytest_provenance_request"] = provenance_details
        payload["details"] = payload_details
        store.save(str(details["token"]), payload)
        details["test_command_proposal"] = helper_proposal
        if provenance_details is not None:
            details["pytest_provenance_request"] = provenance_details
        details["generated_command"] = command
        details["delegates_to"] = "run_shell"
        result.details = details
        result.content = (
            f"Staged pytest command via run_shell. Approve with token {details['token']}\n"
            f"Command: {command}"
        )
        return result


class ApprovePendingShellTool(BaseTool):
    def __init__(self, workspace, default_timeout_seconds: int = 30, sandbox_executor: SandboxExecutor | None = None) -> None:
        super().__init__(workspace)
        self.default_timeout_seconds = default_timeout_seconds
        self.sandbox_executor = sandbox_executor or default_local_sandbox_executor()

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
        result = PowerShellTool(self.workspace, default_timeout_seconds=timeout, sandbox_executor=self.sandbox_executor)._run(payload["command"], timeout)
        store.remove(arguments["token"])
        result.tool_name = self.spec.name
        result.details["token"] = arguments["token"]
        return result
