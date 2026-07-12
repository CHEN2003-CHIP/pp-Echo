from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from pp_agent.coding import (
    ValidationCommand,
    ValidationPlan,
    approve_staged_validation_cycle,
    reject_staged_validation_cycle,
    stage_validation_cycle,
)
from pp_agent.sandbox.base import SandboxRunRequest, SandboxRunResult
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.tools.registry import ToolRegistry
from pp_agent.tools.shell_tool import SHELL_OUTPUT_PREVIEW_MAX_CHARS


class RecordingSandboxExecutor:
    def __init__(self, result: SandboxRunResult | None = None, *, exc: Exception | None = None) -> None:
        self.result = result
        self.exc = exc
        self.requests: list[SandboxRunRequest] = []

    def run(self, request: SandboxRunRequest) -> SandboxRunResult:
        self.requests.append(request)
        if self.exc is not None:
            raise self.exc
        assert self.result is not None
        return self.result


def _plan(*commands: str) -> ValidationPlan:
    return ValidationPlan(commands=[ValidationCommand(command=command, reason=f"reason:{index}") for index, command in enumerate(commands)])


def _result(*, returncode: int = 0, stdout: str = "ok\n", stderr: str = "", timed_out: bool = False, tmp_path: Path) -> SandboxRunResult:
    return SandboxRunResult(
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        timed_out=timed_out,
        backend="fake",
        sandbox_mode="test",
        network_access=False,
        writable_roots=[str(tmp_path)],
    )


def _store(tmp_path: Path) -> PendingActionStore:
    return PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")


def test_stage_validation_cycle_stages_existing_stage_test_command_without_execution(tmp_path: Path) -> None:
    fake = RecordingSandboxExecutor(_result(tmp_path=tmp_path))
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)

    result = stage_validation_cycle(_plan("python -m pytest tests/coding -q"), registry)

    assert result.status == "approval_pending"
    assert result.outcome.final_status == "approval_pending"
    assert result.outcome.repair_attempted is False
    assert result.outcome.revalidation_attempted is False
    assert result.approval_token
    assert fake.requests == []
    pending = _store(tmp_path).load(result.approval_token)
    assert pending["action_type"] == "run_shell"
    assert pending["details"]["test_command_proposal"]["delegates_to"] == "run_shell"


def test_stage_validation_cycle_uses_first_eligible_command_only(tmp_path: Path) -> None:
    fake = RecordingSandboxExecutor(_result(tmp_path=tmp_path))
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)

    result = stage_validation_cycle(_plan("cd web && npm test", "python -m pytest tests/runtime -q", "python -m pytest tests/coding -q"), registry)

    assert result.selection.command == "python -m pytest tests/runtime -q"
    assert result.selection.command_index == 1
    assert _store(tmp_path).load(result.approval_token)["command"] == "python -m pytest tests/runtime -q"  # type: ignore[arg-type]


def test_stage_validation_cycle_no_eligible_command_does_not_stage_or_execute(tmp_path: Path) -> None:
    fake = RecordingSandboxExecutor(_result(tmp_path=tmp_path))
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)

    result = stage_validation_cycle(_plan("cd web && npm test"), registry)

    assert result.status == "not_run"
    assert result.outcome.final_status == "not_run"
    assert result.approval_token is None
    assert fake.requests == []
    assert _store(tmp_path).list() == []


def test_stage_validation_cycle_does_not_generate_fallback_pytest_command(tmp_path: Path) -> None:
    fake = RecordingSandboxExecutor(_result(tmp_path=tmp_path))
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)

    result = stage_validation_cycle(ValidationPlan(commands=[]), registry)

    assert result.status == "not_run"
    assert _store(tmp_path).list() == []
    assert fake.requests == []


def test_reject_staged_validation_cycle_blocks_without_running_shell(tmp_path: Path) -> None:
    fake = RecordingSandboxExecutor(_result(tmp_path=tmp_path))
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)
    staged = stage_validation_cycle(_plan("python -m pytest tests/coding -q"), registry)

    result = reject_staged_validation_cycle(staged.selection, registry, staged.approval_token or "")

    assert result.status == "blocked"
    assert result.outcome.final_status == "blocked"
    assert result.observation is not None
    assert result.observation.repair_eligible is False
    assert fake.requests == []


def test_approve_staged_validation_cycle_executes_exact_staged_action_once(tmp_path: Path) -> None:
    fake = RecordingSandboxExecutor(_result(stdout="passed\n", tmp_path=tmp_path))
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)
    staged = stage_validation_cycle(_plan("python -m pytest tests/coding -q"), registry)
    token = staged.approval_token or ""
    pending_before = _store(tmp_path).load(token)

    result = approve_staged_validation_cycle(staged.selection, registry, token)

    assert result.status == "executed"
    assert result.outcome.final_status == "passed"
    assert result.observation is not None
    assert result.observation.execution_status == "executed"
    assert result.observation.stdout == "passed\n"
    assert len(fake.requests) == 1
    assert fake.requests[0].command == pending_before["command"]
    assert fake.requests[0].timeout_seconds == pending_before["details"]["timeout_seconds"]


def test_approve_staged_validation_cycle_does_not_execute_twice_on_repeat(tmp_path: Path) -> None:
    fake = RecordingSandboxExecutor(_result(stdout="passed\n", tmp_path=tmp_path))
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)
    staged = stage_validation_cycle(_plan("python -m pytest tests/coding -q"), registry)
    token = staged.approval_token or ""

    first = approve_staged_validation_cycle(staged.selection, registry, token)
    second = approve_staged_validation_cycle(staged.selection, registry, token)

    assert first.status == "executed"
    assert second.status == "blocked"
    assert len(fake.requests) == 1


@pytest.mark.parametrize("returncode", [1, 2])
def test_nonzero_exit_remains_conservative_without_repair_eligibility(tmp_path: Path, returncode: int) -> None:
    fake = RecordingSandboxExecutor(_result(returncode=returncode, stdout="bounded failure\n", tmp_path=tmp_path))
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)
    staged = stage_validation_cycle(_plan("python -m pytest tests/coding -q"), registry)

    result = approve_staged_validation_cycle(staged.selection, registry, staged.approval_token or "")

    assert result.status == "executed"
    assert result.outcome.final_status == "validation_nonzero"
    assert result.observation is not None
    assert result.observation.validation_status == "validation_nonzero"
    assert result.observation.repair_eligible is False
    assert result.outcome.repair_attempted is False
    assert result.outcome.revalidation_attempted is False


def test_timeout_is_blocked_not_test_failure(tmp_path: Path) -> None:
    fake = RecordingSandboxExecutor(_result(returncode=0, stdout="partial\n", timed_out=True, tmp_path=tmp_path))
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)
    staged = stage_validation_cycle(_plan("python -m pytest tests/coding -q"), registry)

    result = approve_staged_validation_cycle(staged.selection, registry, staged.approval_token or "")

    assert result.status == "executed"
    assert result.outcome.final_status == "blocked"
    assert result.observation is not None
    assert result.observation.failure_kind == "timeout"
    assert result.observation.repair_eligible is False


def test_tool_exception_is_blocked_not_test_failure(tmp_path: Path) -> None:
    fake = RecordingSandboxExecutor(exc=RuntimeError("launch failed"))
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)
    staged = stage_validation_cycle(_plan("python -m pytest tests/coding -q"), registry)

    result = approve_staged_validation_cycle(staged.selection, registry, staged.approval_token or "")

    assert result.status == "blocked"
    assert result.outcome.final_status == "blocked"
    assert result.observation is not None
    assert result.observation.repair_eligible is False


def test_bounded_and_truncated_output_is_preserved_from_shell_result(tmp_path: Path) -> None:
    long_stdout = "x" * (SHELL_OUTPUT_PREVIEW_MAX_CHARS + 20)
    fake = RecordingSandboxExecutor(_result(returncode=1, stdout=long_stdout, stderr="err", tmp_path=tmp_path))
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)
    staged = stage_validation_cycle(_plan("python -m pytest tests/coding -q"), registry)

    result = approve_staged_validation_cycle(staged.selection, registry, staged.approval_token or "")

    assert result.observation is not None
    assert result.observation.stdout_chars == len(long_stdout)
    assert result.observation.stdout_truncated is True
    assert len(result.observation.stdout) > SHELL_OUTPUT_PREVIEW_MAX_CHARS
    assert result.observation.stderr == "err"


def test_validation_cycle_does_not_call_subprocess_pytest_model_or_revalidation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fail(*_args, **_kwargs):  # pragma: no cover - must never be called
        raise AssertionError("forbidden direct execution path")

    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(pytest, "main", fail)
    fake = RecordingSandboxExecutor(_result(tmp_path=tmp_path))
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)
    runtime_like = SimpleNamespace(prompt=fail, continue_=fail)

    staged = stage_validation_cycle(_plan("python -m pytest tests/coding -q"), registry)
    result = approve_staged_validation_cycle(staged.selection, registry, staged.approval_token or "")

    assert runtime_like.prompt
    assert result.outcome.repair_attempted is False
    assert result.outcome.revalidation_attempted is False
    assert len(fake.requests) == 1
