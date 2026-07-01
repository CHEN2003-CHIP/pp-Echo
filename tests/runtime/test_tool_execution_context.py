from __future__ import annotations

from pathlib import Path

from pp_agent.runtime.execution_context import (
    RuntimeExecutionContext,
    RuntimeExecutionCounters,
    RuntimeExecutionGuardrails,
)
from pp_agent.runtime.scope_contract import WriteScope, write_scope_to_dict
from pp_agent.runtime.tool_context import ToolExecutionContext, tool_execution_context_to_dict
from pp_agent.sandbox.base import SandboxRunRequest, SandboxRunResult
from pp_agent.sandbox.changes import bytes_digest, structured_changes_digest
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.tools.base import ToolExecutionResult
from pp_agent.tools.registry import ToolRegistry


class RecordingExecutor:
    """Sandbox executor test double that records whether shell execution happened."""

    def __init__(self, result: SandboxRunResult) -> None:
        self.result = result
        self.requests: list[SandboxRunRequest] = []

    def run(self, request: SandboxRunRequest) -> SandboxRunResult:
        self.requests.append(request)
        return self.result


def _guardrails(
    *,
    max_tool_calls: int = 5,
    max_shell_commands: int = 2,
    max_patch_candidates: int = 2,
) -> RuntimeExecutionGuardrails:
    return RuntimeExecutionGuardrails(
        max_tool_calls=max_tool_calls,
        max_shell_commands=max_shell_commands,
        max_patch_candidates=max_patch_candidates,
        stop_on_approval=True,
        stop_on_scope_block=True,
        stop_on_test_failure=True,
    )


def _context(
    *,
    guardrails: RuntimeExecutionGuardrails | None = None,
    counters: RuntimeExecutionCounters | None = None,
    write_scope: WriteScope | None = None,
) -> RuntimeExecutionContext:
    return RuntimeExecutionContext(
        session_id="exec-1",
        status="prepared",
        phase="prepared",
        write_scope=write_scope,
        guardrails=guardrails or _guardrails(),
        counters=counters or RuntimeExecutionCounters(),
        predicted_impact_not_actual=True,
        warnings=[],
    )


def _changed_result(path: str = "notes.txt") -> SandboxRunResult:
    structured = [
        {
            "path": path,
            "change_type": "added",
            "old_digest": None,
            "new_digest": bytes_digest(b"after\n"),
            "content_text": "after\n",
            "content_encoding": "utf-8",
            "binary": False,
            "truncated": False,
            "size_bytes": 6,
        }
    ]
    return SandboxRunResult(
        stdout="ok",
        stderr="",
        returncode=0,
        timed_out=False,
        backend="fake",
        sandbox_mode="test",
        network_access=False,
        writable_roots=[],
        changed_files=[{"path": path, "status": "added", "before_size": 0, "after_size": 6, "before_digest": "", "after_digest": "x", "truncated": False}],
        patch=f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1 @@\n+after\n",
        patch_summary="adds notes",
        structured_changes=structured,
        structured_changes_digest=structured_changes_digest(structured),
    )


def _stage_shell(registry: ToolRegistry) -> str:
    staged = registry.execute("run_shell", {"command": "Write-Output ok", "timeout_seconds": 5})
    return staged.details["token"]


def test_tool_execution_context_serializes() -> None:
    payload = tool_execution_context_to_dict(ToolExecutionContext(_context()))

    assert payload is not None
    assert payload["runtime_execution_context"]["session_id"] == "exec-1"


def test_tool_call_without_runtime_context_keeps_legacy_behavior(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)

    result = registry.execute("list_files", {"path": "."})

    assert result.is_error is False
    assert "runtime_guardrail_blocked" not in result.details


def test_tool_call_with_runtime_context_allows_below_limit(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    registry.set_runtime_execution_context(_context())

    result = registry.execute("list_files", {"path": "."})

    assert result.is_error is False
    assert result.details["runtime_execution_context_present"] is True
    assert registry.runtime_execution_context().counters.tool_calls == 1


def test_tool_call_with_runtime_context_blocks_at_tool_call_limit(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    registry.set_runtime_execution_context(_context(guardrails=_guardrails(max_tool_calls=1), counters=RuntimeExecutionCounters(tool_calls=1)))

    result = registry.execute("list_files", {"path": "."})

    assert result.is_error is True
    assert result.details["runtime_guardrail_blocked"] is True
    assert result.details["guardrail_check"]["matched_limit"] == "max_tool_calls"


def test_tool_call_guardrail_block_does_not_execute_tool(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    seen: list[str] = []
    registry.register_function_tool(
        name="demo_guarded",
        description="demo",
        parameters={"type": "object", "properties": {}},
        executor=lambda workspace, arguments: seen.append("called") or "ok",
        category="extension",
        permission_domain="read",
        exact_effect_mode="none",
    )
    registry.set_runtime_execution_context(_context(guardrails=_guardrails(max_tool_calls=0)))

    result = registry.execute("demo_guarded", {})

    assert result.is_error is True
    assert seen == []


def test_tool_call_counter_increments_after_execution(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    registry.set_runtime_execution_context(_context())

    registry.execute("list_files", {"path": "."})
    registry.execute("list_files", {"path": "."})

    assert registry.runtime_execution_context().counters.tool_calls == 2


def test_run_shell_without_runtime_context_keeps_legacy_behavior(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingExecutor(_changed_result()))

    staged = registry.execute("run_shell", {"command": "Write-Output ok", "timeout_seconds": 5})

    assert staged.details["staged"] is True
    assert registry.runtime_execution_context() is None


def test_run_shell_with_runtime_context_allows_below_shell_limit(tmp_path: Path) -> None:
    executor = RecordingExecutor(_changed_result())
    registry = ToolRegistry(tmp_path, sandbox_executor=executor)
    registry.set_runtime_execution_context(_context())
    token = _stage_shell(registry)

    result = registry.host_execute("approve_pending_action", {"token": token})

    assert result.is_error is False
    assert result.details["shell_command_guardrail_check"]["allowed"] is True
    assert registry.runtime_execution_context().counters.shell_commands == 1


def test_run_shell_with_runtime_context_blocks_at_shell_limit(tmp_path: Path) -> None:
    executor = RecordingExecutor(_changed_result())
    registry = ToolRegistry(tmp_path, sandbox_executor=executor)
    registry.set_runtime_execution_context(_context(guardrails=_guardrails(max_shell_commands=1), counters=RuntimeExecutionCounters(shell_commands=1)))
    token = _stage_shell(registry)

    result = registry.host_execute("approve_pending_action", {"token": token})

    assert result.is_error is True
    assert result.details["guardrail_check"]["matched_limit"] == "max_shell_commands"


def test_run_shell_guardrail_block_does_not_call_executor(tmp_path: Path) -> None:
    executor = RecordingExecutor(_changed_result())
    registry = ToolRegistry(tmp_path, sandbox_executor=executor)
    registry.set_runtime_execution_context(_context(guardrails=_guardrails(max_shell_commands=0)))
    token = _stage_shell(registry)

    result = registry.host_execute("approve_pending_action", {"token": token})

    assert result.is_error is True
    assert executor.requests == []


def test_run_shell_counter_increments_after_real_execution(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingExecutor(_changed_result()))
    registry.set_runtime_execution_context(_context())
    token = _stage_shell(registry)

    registry.host_execute("approve_pending_action", {"token": token})

    assert registry.runtime_execution_context().counters.shell_commands == 1


def test_patch_candidate_without_runtime_context_keeps_legacy_behavior(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingExecutor(_changed_result()))
    token = _stage_shell(registry)

    result = registry.host_execute("approve_pending_action", {"token": token})

    candidate = result.details["patch_candidate"]
    assert candidate["staged"] is True
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").load(candidate["token"])
    assert "execution_context" not in pending["details"]


def test_patch_candidate_with_runtime_context_attaches_write_scope_before_pending_action(tmp_path: Path) -> None:
    scope = WriteScope(allowed_paths=["notes.txt"], source="task_scope")
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingExecutor(_changed_result()))
    registry.set_runtime_execution_context(_context(write_scope=scope))
    token = _stage_shell(registry)

    result = registry.host_execute("approve_pending_action", {"token": token})

    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").load(result.details["patch_candidate"]["token"])
    assert pending["details"]["write_scope"] == write_scope_to_dict(scope)
    assert pending["effect"]["normalized_arguments"]["write_scope"] == write_scope_to_dict(scope)


def test_patch_candidate_with_runtime_context_attaches_execution_metadata(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingExecutor(_changed_result()))
    registry.set_runtime_execution_context(_context())
    token = _stage_shell(registry)

    result = registry.host_execute("approve_pending_action", {"token": token})

    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").load(result.details["patch_candidate"]["token"])
    assert pending["details"]["execution_context"] == {
        "session_id": "exec-1",
        "phase": "prepared",
        "predicted_impact_not_actual": True,
    }


def test_patch_candidate_with_runtime_context_blocks_at_patch_candidate_limit(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingExecutor(_changed_result()))
    registry.set_runtime_execution_context(_context(guardrails=_guardrails(max_patch_candidates=1), counters=RuntimeExecutionCounters(patch_candidates=1)))
    token = _stage_shell(registry)

    result = registry.host_execute("approve_pending_action", {"token": token})

    candidate = result.details["patch_candidate"]
    assert candidate["patch_candidate_blocked"] is True
    assert candidate["guardrail_check"]["matched_limit"] == "max_patch_candidates"


def test_patch_candidate_guardrail_block_does_not_create_pending_action(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingExecutor(_changed_result()))
    registry.set_runtime_execution_context(_context(guardrails=_guardrails(max_patch_candidates=0)))
    token = _stage_shell(registry)

    registry.host_execute("approve_pending_action", {"token": token})

    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert not any(item["action_type"] == "apply_patch_candidate" for item in pending)


def test_patch_candidate_counter_increments_after_pending_action_created(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingExecutor(_changed_result()))
    registry.set_runtime_execution_context(_context())
    token = _stage_shell(registry)

    registry.host_execute("approve_pending_action", {"token": token})

    assert registry.runtime_execution_context().counters.patch_candidates == 1


def test_legacy_apply_patch_candidate_without_write_scope_still_works(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingExecutor(_changed_result()))
    token = _stage_shell(registry)
    shell_result = registry.host_execute("approve_pending_action", {"token": token})

    apply_result = registry.host_execute("approve_pending_action", {"token": shell_result.details["patch_candidate"]["token"]})

    assert apply_result.is_error is False
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "after\n"


def test_apply_patch_candidate_with_write_scope_still_enforces_scope(tmp_path: Path) -> None:
    scope = WriteScope(allowed_paths=["src/**"], source="task_scope")
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingExecutor(_changed_result("notes.txt")))
    registry.set_runtime_execution_context(_context(write_scope=scope))
    token = _stage_shell(registry)
    shell_result = registry.host_execute("approve_pending_action", {"token": token})

    apply_result = registry.host_execute("approve_pending_action", {"token": shell_result.details["patch_candidate"]["token"]})

    assert apply_result.is_error is True
    assert apply_result.details["scope_blocked"] is True
    assert not (tmp_path / "notes.txt").exists()
