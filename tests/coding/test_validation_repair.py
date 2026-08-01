from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pp_agent.coding import (
    ValidationCommand,
    ValidationPlan,
    approve_staged_validation_cycle,
    build_validation_repair_prompt,
    complete_revalidation_after_approval,
    run_one_bounded_validation_repair_cycle,
    stage_validation_cycle,
    validation_repair_trigger_allowed,
)
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.coding.pytest_provenance import write_pytest_provenance_attestation
from pp_agent.sandbox.base import SandboxRunRequest, SandboxRunResult
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.sessions import (
    SESSION_CORRELATION_KEY,
    SESSION_MESSAGE_ID_KEY,
    SessionEvidenceLookupStatus,
    SessionEvidenceReference,
    SessionStore,
    build_external_tool_result_correlation,
    build_session_result_digest,
)
from pp_agent.tools.registry import ToolRegistry


class SequenceSandboxExecutor:
    def __init__(self, results: list[SandboxRunResult], *, write_provenance: bool = True) -> None:
        self.results = list(results)
        self.write_provenance = write_provenance
        self.requests: list[SandboxRunRequest] = []

    def run(self, request: SandboxRunRequest) -> SandboxRunResult:
        self.requests.append(request)
        if not self.results:
            raise AssertionError("unexpected validation execution")
        result = self.results.pop(0)
        if self.write_provenance:
            _write_provenance_from_request(request, result.returncode)
        return result


class RepairRuntime:
    def __init__(self, workspace: Path, *, pending: bool = False, error: Exception | None = None) -> None:
        self.tool_registry = ToolRegistry(workspace)
        self.prompts: list[str] = []
        self.error = error
        self.pending = pending

    def prompt(self, text: str):
        self.prompts.append(text)
        if self.error is not None:
            raise self.error
        if self.pending:
            self.tool_registry.execute("write_file", {"path": "repair.txt", "content": "fixed"})
        return [SimpleNamespace(details={"repair_turn": True}, is_error=False)]


def _plan(command: str = "python -m pytest tests/coding -q") -> ValidationPlan:
    return ValidationPlan(commands=[ValidationCommand(command=command, reason="focused")])


def _result(tmp_path: Path, *, returncode: int, stdout: str = "", stderr: str = "", timed_out: bool = False) -> SandboxRunResult:
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


def _initial_cycle(tmp_path: Path, *, returncode: int = 1, write_provenance: bool = True):
    fake = SequenceSandboxExecutor([_result(tmp_path, returncode=returncode, stdout="FAILED\n")], write_provenance=write_provenance)
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)
    staged = stage_validation_cycle(_plan(), registry)
    session_store, reference = _persisted_validation_result(
        tmp_path,
        staged.selection,
        action_id=staged.approval_token or "",
        returncode=returncode,
        stdout="FAILED\n",
        write_artifact=write_provenance,
    )
    approved = approve_staged_validation_cycle(
        staged.selection,
        evidence_reference=reference,
        session_store=session_store,
        workspace=tmp_path,
    )
    return registry, fake, approved


def _persisted_validation_result(
    tmp_path: Path,
    selection,
    *,
    action_id: str,
    returncode: int,
    stdout: str = "ok\n",
    write_artifact: bool = True,
) -> tuple[SessionStore, SessionEvidenceReference]:
    from pp_agent.coding.pytest_provenance import logical_command_digest
    from pp_agent.llm import ModelConfig

    session_store = SessionStore(tmp_path / "sessions")
    try:
        record = session_store.load("session-1")
    except FileNotFoundError:
        record = session_store.create("system", ModelConfig())
        record.metadata.id = "session-1"
    digest = logical_command_digest(selection.normalized_command or "")
    nonce = f"{abs(hash((action_id, returncode, stdout))) % (16**32):032x}"
    artifact = f".pp-agent/validation-provenance/{nonce}.json"
    result_digest = build_session_result_digest({"action_id": action_id, "returncode": returncode, "stdout": stdout})
    message = ChatMessage(
        role="tool",
        tool_call_id="call-validation-result",
        tool_name="approve_pending_action",
        content=[TextPart(text="ok")],
        metadata={SESSION_MESSAGE_ID_KEY: f"msg-{action_id[:20]}"},
        timestamp=1.0,
    )
    message.metadata[SESSION_CORRELATION_KEY] = build_external_tool_result_correlation(
        action_id=action_id,
        result_digest=result_digest,
        tool_name="approve_pending_action",
        completed_at=1.0,
    )
    message.metadata["tool_details"] = {
        "action_type": "run_shell",
        "success": True,
        "lifecycle": {"state": "grant_consumed"},
        "result_details": {
            "exit_code": returncode,
            "stdout": stdout,
            "stderr": "",
            "stdout_chars": len(stdout),
            "stderr_chars": 0,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "logical_command_digest": digest,
            "pytest_provenance_request": {
                "schema_version": 1,
                "plugin_id": "pp_agent.coding.pytest_provenance_plugin",
                "plugin_version": "1",
                "nonce": nonce,
                "logical_command_digest": digest,
                "artifact_relative_path": artifact,
            },
        },
    }
    branch_messages = session_store.branch_messages(record, record.active_head_id)
    record = session_store.sync_branch_state(
        record,
        base_head_id=record.active_head_id,
        branch_messages=[*branch_messages, message],
        pending_plan_token=record.pending_plan_token,
        pending_tool_calls=record.pending_tool_calls,
    )
    session_store.save(record)
    if write_artifact:
        write_pytest_provenance_attestation(
            artifact_path=tmp_path / artifact,
            nonce=nonce,
            logical_command_digest=digest,
            pytest_exit_status=returncode,
        )
    try:
        PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").set_lifecycle(action_id, "grant_consumed")
    except FileNotFoundError:
        pass
    lookup = session_store.lookup_external_tool_result_evidence("session-1", action_id=action_id, result_digest=result_digest)
    assert lookup.status == SessionEvidenceLookupStatus.FOUND
    assert lookup.evidence is not None
    return session_store, lookup.evidence


def _write_provenance_from_request(request: SandboxRunRequest, exit_status: int) -> None:
    parts = request.command.split()
    if "--pp-echo-pytest-provenance-file" not in parts:
        return
    artifact = parts[parts.index("--pp-echo-pytest-provenance-file") + 1]
    nonce = parts[parts.index("--pp-echo-pytest-provenance-nonce") + 1]
    digest = parts[parts.index("--pp-echo-pytest-logical-command-digest") + 1]
    write_pytest_provenance_attestation(
        artifact_path=request.cwd / artifact,
        nonce=nonce,
        logical_command_digest=digest,
        pytest_exit_status=exit_status,
    )


def test_trusted_tests_failed_triggers_one_repair_and_stages_same_command_revalidation(tmp_path: Path) -> None:
    registry, fake, initial = _initial_cycle(tmp_path, returncode=1)
    runtime = RepairRuntime(tmp_path)

    state = run_one_bounded_validation_repair_cycle(
        task="fix focused failure",
        runtime=runtime,
        registry=registry,
        initial_result=initial,
    )

    assert validation_repair_trigger_allowed(initial) is True
    assert len(runtime.prompts) == 1
    assert state.status == "revalidation_pending"
    assert state.repair_attempted is True
    assert state.revalidation_attempted is False
    assert state.revalidation_result is not None
    assert state.revalidation_result.selection is initial.selection
    assert state.revalidation_result.selection.normalized_command == initial.selection.normalized_command
    assert state.revalidation_result.approval_token
    assert len(fake.requests) == 0

    session_store, reference = _persisted_validation_result(
        tmp_path,
        state.selection,
        action_id=state.revalidation_result.approval_token or "",
        returncode=0,
        stdout="passed\n",
    )
    final = complete_revalidation_after_approval(
        state,
        evidence_reference=reference,
        session_store=session_store,
        workspace=tmp_path,
    )

    assert final.status == "completed"
    assert final.final_outcome is not None
    assert final.final_outcome.final_status == "passed"
    assert final.final_outcome.repair_attempted is True
    assert final.final_outcome.revalidation_attempted is True
    assert final.validation_executions == 2
    assert len(fake.requests) == 0


@pytest.mark.parametrize("returncode", [0, 2, 3, 4, 5])
def test_non_tests_failed_categories_do_not_call_repair(tmp_path: Path, returncode: int) -> None:
    registry, _fake, initial = _initial_cycle(tmp_path, returncode=returncode)
    runtime = RepairRuntime(tmp_path)

    state = run_one_bounded_validation_repair_cycle(
        task="do not repair",
        runtime=runtime,
        registry=registry,
        initial_result=initial,
    )

    assert state.status == "not_repairable"
    assert runtime.prompts == []


def test_raw_exit_one_without_attestation_does_not_call_repair_even_with_failed_stdout(tmp_path: Path) -> None:
    registry, _fake, initial = _initial_cycle(tmp_path, returncode=1, write_provenance=False)
    runtime = RepairRuntime(tmp_path)

    state = run_one_bounded_validation_repair_cycle(
        task="stdout says FAILED",
        runtime=runtime,
        registry=registry,
        initial_result=initial,
    )

    assert initial.observation is not None
    assert initial.observation.stdout == "FAILED"
    assert initial.observation.repair_eligible is False
    assert state.status == "not_repairable"
    assert runtime.prompts == []


def test_repair_prompt_is_bounded_and_excludes_provenance_internals(tmp_path: Path) -> None:
    _registry, _fake, initial = _initial_cycle(tmp_path, returncode=1)
    assert initial.observation is not None
    observation = initial.observation.__class__(
        **{**initial.observation.to_dict(), "stdout": "x" * 5000, "stderr": "err", "stdout_truncated": True}
    )

    prompt = build_validation_repair_prompt(task="fix", selection=initial.selection, observation=observation)

    assert "This is the only allowed repair attempt" in prompt
    assert "Do not change the validation command" in prompt
    assert "Do not skip, xfail, delete, or weaken tests" in prompt
    assert "python -m pytest tests/coding -q" in prompt
    assert "[repair context truncated" in prompt
    assert ".pp-agent/validation-provenance" not in prompt
    assert "--pp-echo-pytest-provenance-nonce" not in prompt
    assert "nonce" not in prompt.lower()
    assert "approval token" not in prompt.lower()


def test_repair_pending_does_not_stage_revalidation_or_call_model_twice(tmp_path: Path) -> None:
    registry, fake, initial = _initial_cycle(tmp_path, returncode=1)
    runtime = RepairRuntime(tmp_path, pending=True)

    state = run_one_bounded_validation_repair_cycle(
        task="repair needs edit approval",
        runtime=runtime,
        registry=registry,
        initial_result=initial,
    )

    assert state.status == "repair_pending"
    assert len(runtime.prompts) == 1
    assert state.revalidation_result is None
    assert len(fake.requests) == 0
    assert state.final_outcome is not None
    assert state.final_outcome.final_status == "approval_pending"
    assert state.final_outcome.repair_attempted is True
    assert state.final_outcome.revalidation_attempted is False


def test_repair_model_failure_blocks_without_revalidation(tmp_path: Path) -> None:
    registry, fake, initial = _initial_cycle(tmp_path, returncode=1)
    runtime = RepairRuntime(tmp_path, error=RuntimeError("model down"))

    state = run_one_bounded_validation_repair_cycle(
        task="repair fails",
        runtime=runtime,
        registry=registry,
        initial_result=initial,
    )

    assert state.status == "repair_blocked"
    assert len(runtime.prompts) == 1
    assert state.revalidation_result is None
    assert len(fake.requests) == 0
    assert state.final_outcome is not None
    assert state.final_outcome.final_status == "blocked"


def test_repeated_revalidation_completion_is_idempotent_and_does_not_execute_third_time(tmp_path: Path) -> None:
    registry, fake, initial = _initial_cycle(tmp_path, returncode=1)
    runtime = RepairRuntime(tmp_path)
    state = run_one_bounded_validation_repair_cycle(
        task="fix focused failure",
        runtime=runtime,
        registry=registry,
        initial_result=initial,
    )

    session_store, reference = _persisted_validation_result(
        tmp_path,
        state.selection,
        action_id=state.revalidation_result.approval_token or "",  # type: ignore[union-attr]
        returncode=1,
        stdout="still failing\n",
    )
    first = complete_revalidation_after_approval(
        state,
        evidence_reference=reference,
        session_store=session_store,
        workspace=tmp_path,
    )
    second = complete_revalidation_after_approval(
        first,
        evidence_reference=reference,
        session_store=session_store,
        workspace=tmp_path,
    )

    assert first.final_outcome is not None
    assert first.final_outcome.final_status == "failed"
    assert first.final_outcome.repair_attempted is True
    assert first.final_outcome.revalidation_attempted is True
    assert second.details["idempotent"] is True
    assert len(runtime.prompts) == 1
    assert len(fake.requests) == 0


def test_revalidation_uses_new_nonce_and_approval_but_same_logical_command(tmp_path: Path) -> None:
    registry, fake, initial = _initial_cycle(tmp_path, returncode=1)
    runtime = RepairRuntime(tmp_path)
    state = run_one_bounded_validation_repair_cycle(
        task="fix focused failure",
        runtime=runtime,
        registry=registry,
        initial_result=initial,
    )

    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")

    assert state.revalidation_result is not None
    assert state.revalidation_result.approval_token
    consumed = [item for item in store.list() if (item.get("lifecycle") or {}).get("state") == "grant_consumed"]
    assert consumed
    initial_command = consumed[0]["command"]
    revalidation_command = store.load(state.revalidation_result.approval_token)["command"]
    assert "python -m pytest tests/coding -q" in revalidation_command
    assert initial.selection.normalized_command == state.revalidation_result.selection.normalized_command
    assert _arg_value(initial_command, "--pp-echo-pytest-provenance-nonce") != _arg_value(
        revalidation_command,
        "--pp-echo-pytest-provenance-nonce",
    )
    assert _arg_value(initial_command, "--pp-echo-pytest-provenance-file") != _arg_value(
        revalidation_command,
        "--pp-echo-pytest-provenance-file",
    )


def _arg_value(command: str, name: str) -> str:
    parts = command.split()
    return parts[parts.index(name) + 1]
