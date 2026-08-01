from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.coding import (
    InitialValidationStagingResult,
    ValidationCommand,
    ValidationPlan,
    interpret_persisted_validation_result,
    reject_staged_validation_cycle,
    stage_initial_validation_workflow,
    stage_validation_cycle,
)
from pp_agent.coding.pytest_provenance import logical_command_digest, write_pytest_provenance_attestation
from pp_agent.coding.workflow_checkpoint import (
    CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2,
    CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3,
    CodingWorkflowCheckpoint,
    CodingWorkflowKind,
    CodingWorkflowPhase,
    PendingActionReference,
    PendingActionRole,
)
from pp_agent.coding.workflow_checkpoint_store import CheckpointNotFound, CheckpointStorageError, CodingWorkflowCheckpointStore
from pp_agent.llm import ModelConfig
from pp_agent.sandbox.base import SandboxRunRequest, SandboxRunResult
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.sessions import (
    SESSION_CORRELATION_KEY,
    SESSION_MESSAGE_ID_KEY,
    SessionEvidenceLookupStatus,
    SessionEvidenceReference,
    SessionStore,
    SessionValidationEvidence,
    build_external_tool_result_correlation,
    build_session_result_digest,
)
from pp_agent.tools.registry import ToolRegistry
from pp_agent.tools.shell_tool import SHELL_OUTPUT_PREVIEW_MAX_CHARS


class RecordingSandboxExecutor:
    def __init__(self, result: SandboxRunResult | None = None, *, exc: Exception | None = None, write_provenance: bool = True) -> None:
        self.result = result
        self.exc = exc
        self.write_provenance = write_provenance
        self.requests: list[SandboxRunRequest] = []

    def run(self, request: SandboxRunRequest) -> SandboxRunResult:
        self.requests.append(request)
        if self.exc is not None:
            raise self.exc
        assert self.result is not None
        if self.write_provenance:
            _write_provenance_from_request(request, self.result.returncode)
        return self.result


class MismatchedProvenanceSandboxExecutor(RecordingSandboxExecutor):
    def run(self, request: SandboxRunRequest) -> SandboxRunResult:
        self.requests.append(request)
        assert self.result is not None
        _write_provenance_from_request(request, self.result.returncode, logical_command_digest="b" * 64)
        return self.result


class CreateFailingCheckpointStore:
    def load_checkpoint(self, _workflow_id: str) -> CodingWorkflowCheckpoint:
        raise CheckpointNotFound("missing")

    def create_checkpoint(self, _checkpoint: CodingWorkflowCheckpoint) -> CodingWorkflowCheckpoint:
        raise CheckpointStorageError("boom")


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


def _checkpoint(
    *,
    workflow_id: str = "workflow-validation",
    session_id: str = "session-1",
    phase: CodingWorkflowPhase = CodingWorkflowPhase.PREPARED,
    revision: int = 0,
    schema_version: int = CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3,
    selected_digest: str | None = None,
    pending_ref: PendingActionReference | None = None,
) -> CodingWorkflowCheckpoint:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return CodingWorkflowCheckpoint(
        schema_version=schema_version,
        workflow_id=workflow_id,
        session_id=session_id,
        workflow_kind=CodingWorkflowKind.CONTROLLED_CODING,
        revision=revision,
        phase=phase,
        selected_validation_command_digest=selected_digest,
        selected_validation_command_digest_algorithm="sha256" if selected_digest is not None else None,
        validation_execution_count=0,
        repair_attempted=False,
        revalidation_attempted=False,
        pending_action_ref=pending_ref,
        created_at=now,
        updated_at=now,
    )


def _session_store_with_record(tmp_path: Path, session_id: str = "session-1") -> SessionStore:
    session_store = SessionStore(tmp_path / "sessions")
    record = session_store.create("system", ModelConfig())
    record.metadata.id = session_id
    session_store.save(record)
    return session_store


def _record_external_result(
    session_store: SessionStore,
    session_id: str,
    *,
    action_id: str,
    result_digest: str,
    logical_digest: str,
    returncode: int = 0,
    stdout: str = "ok\n",
    stderr: str = "",
    timed_out: bool = False,
    nonce: str = "a" * 32,
    artifact_relative_path: str = ".pp-agent/validation-provenance/a.json",
    include_provenance_request: bool = True,
) -> SessionEvidenceReference:
    record = session_store.load(session_id)
    result_details: dict[str, object] = {
        "exit_code": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_chars": len(stdout),
        "stderr_chars": len(stderr),
        "stdout_truncated": False,
        "stderr_truncated": False,
        "timed_out": timed_out,
        "logical_command_digest": logical_digest,
        "backend": "fake",
    }
    if include_provenance_request:
        result_details["pytest_provenance_request"] = {
            "schema_version": 1,
            "plugin_id": "pp_agent.coding.pytest_provenance_plugin",
            "plugin_version": "1",
            "nonce": nonce,
            "logical_command_digest": logical_digest,
            "artifact_relative_path": artifact_relative_path,
        }
    message = ChatMessage(
        role="tool",
        tool_call_id="call-validation-result",
        tool_name="approve_pending_action",
        content=[TextPart(text="ok")],
        metadata={SESSION_MESSAGE_ID_KEY: "msg-validation-result"},
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
        "success": not timed_out,
        "lifecycle": {"state": "grant_consumed"},
        "result_details": result_details,
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
    lookup = session_store.lookup_external_tool_result_evidence(session_id, action_id=action_id, result_digest=result_digest)
    assert lookup.status == SessionEvidenceLookupStatus.FOUND
    assert lookup.evidence is not None
    return lookup.evidence


def _write_provenance_from_request(request: SandboxRunRequest, exit_status: int, *, logical_command_digest: str | None = None) -> None:
    parts = request.command.split()
    if "--pp-echo-pytest-provenance-file" not in parts:
        return
    artifact = parts[parts.index("--pp-echo-pytest-provenance-file") + 1]
    nonce = parts[parts.index("--pp-echo-pytest-provenance-nonce") + 1]
    digest = logical_command_digest or parts[parts.index("--pp-echo-pytest-logical-command-digest") + 1]
    write_pytest_provenance_attestation(
        artifact_path=request.cwd / artifact,
        nonce=nonce,
        logical_command_digest=digest,
        pytest_exit_status=exit_status,
    )


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
    assert _store(tmp_path).load(result.approval_token)["command"].startswith("python -m pytest tests/runtime -q")  # type: ignore[union-attr]
    assert result.selection.normalized_command == "python -m pytest tests/runtime -q"


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


def test_stage_initial_validation_workflow_creates_v3_awaiting_checkpoint(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingSandboxExecutor(_result(tmp_path=tmp_path)))
    store = CodingWorkflowCheckpointStore(tmp_path)

    result = stage_initial_validation_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        session_id="session-1",
        validation_plan=_plan("python -m pytest tests/coding -q"),
        registry=registry,
        checkpoint_store=store,
    )
    checkpoint = store.load_checkpoint("workflow-validation")
    pending = _store(tmp_path).load(result.approval_token or "")
    expected_digest = logical_command_digest("python -m pytest tests/coding -q")

    assert result.status == "staged"
    assert result.awaiting_approval is True
    assert result.pending_action_ref is not None
    assert result.pending_action_ref.role == PendingActionRole.VALIDATION
    assert result.pending_action_ref.action_type == "run_shell"
    assert result.pending_action_ref.action_id == result.approval_token
    assert result.pending_action_ref.action_digest == pending["canonical_key"]
    assert checkpoint.schema_version == CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3
    assert checkpoint.phase == CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL
    assert checkpoint.selected_validation_command_digest == expected_digest
    assert checkpoint.selected_validation_command_digest_algorithm == "sha256"
    assert checkpoint.pending_action_ref == result.pending_action_ref
    assert checkpoint.validation_execution_count == 0
    assert checkpoint.repair_attempted is False
    assert checkpoint.revalidation_attempted is False
    assert checkpoint.final_outcome_summary is None
    assert checkpoint.terminal_outcome is None
    assert pending["details"]["pytest_provenance_request"]["logical_command_digest"] == expected_digest


def test_stage_initial_validation_no_command_does_not_stage_or_checkpoint(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingSandboxExecutor(_result(tmp_path=tmp_path)))
    store = CodingWorkflowCheckpointStore(tmp_path)

    result = stage_initial_validation_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        session_id="session-1",
        validation_plan=_plan("cd web && npm test"),
        registry=registry,
        checkpoint_store=store,
    )

    assert result.status == "blocked_no_command"
    assert _store(tmp_path).list() == []
    assert store.checkpoint_exists("workflow-validation") is False


def test_stage_initial_validation_existing_exact_checkpoint_is_idempotent(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingSandboxExecutor(_result(tmp_path=tmp_path)))
    store = CodingWorkflowCheckpointStore(tmp_path)
    first = stage_initial_validation_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        session_id="session-1",
        validation_plan=_plan("python -m pytest tests/coding -q"),
        registry=registry,
        checkpoint_store=store,
    )

    second = stage_initial_validation_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        session_id="session-1",
        validation_plan=_plan("python -m pytest tests/coding -q"),
        registry=registry,
        checkpoint_store=store,
    )

    assert first.status == "staged"
    assert second.status == "already_staged"
    assert second.pending_action_ref == first.pending_action_ref
    assert len(_store(tmp_path).list()) == 1
    assert store.load_checkpoint("workflow-validation").revision == 0


def test_stage_initial_validation_existing_prepared_checkpoint_uses_cas(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingSandboxExecutor(_result(tmp_path=tmp_path)))
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(_checkpoint())

    result = stage_initial_validation_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        session_id="session-1",
        validation_plan=_plan("python -m pytest tests/coding -q"),
        registry=registry,
        checkpoint_store=store,
        expected_revision=0,
    )

    checkpoint = store.load_checkpoint("workflow-validation")
    assert result.status == "staged"
    assert checkpoint.revision == 1
    assert checkpoint.phase == CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL


def test_stage_initial_validation_stale_revision_before_stage_does_not_create_action(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingSandboxExecutor(_result(tmp_path=tmp_path)))
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(_checkpoint())

    result = stage_initial_validation_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        session_id="session-1",
        validation_plan=_plan("python -m pytest tests/coding -q"),
        registry=registry,
        checkpoint_store=store,
        expected_revision=1,
    )

    assert result.status == "blocked_stale_revision"
    assert _store(tmp_path).list() == []
    assert store.load_checkpoint("workflow-validation").phase == CodingWorkflowPhase.PREPARED


def test_stage_initial_validation_checkpoint_write_failure_reports_orphan_risk(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingSandboxExecutor(_result(tmp_path=tmp_path)))

    result = stage_initial_validation_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        session_id="session-1",
        validation_plan=_plan("python -m pytest tests/coding -q"),
        registry=registry,
        checkpoint_store=CreateFailingCheckpointStore(),  # type: ignore[arg-type]
    )

    assert result.status == "blocked_orphan_risk"
    assert result.approval_token
    assert len(_store(tmp_path).list()) == 1


def test_stage_initial_validation_orphan_action_blocks_second_action(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingSandboxExecutor(_result(tmp_path=tmp_path)))
    first = stage_initial_validation_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        session_id="session-1",
        validation_plan=_plan("python -m pytest tests/coding -q"),
        registry=registry,
        checkpoint_store=CreateFailingCheckpointStore(),  # type: ignore[arg-type]
    )

    second = stage_initial_validation_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        session_id="session-1",
        validation_plan=_plan("python -m pytest tests/coding -q"),
        registry=registry,
        checkpoint_store=CreateFailingCheckpointStore(),  # type: ignore[arg-type]
    )

    assert first.status == "blocked_orphan_risk"
    assert second.status == "blocked_orphan_risk"
    assert second.approval_token == first.approval_token
    assert len(_store(tmp_path).list()) == 1


def test_stage_initial_validation_legacy_checkpoint_is_not_migrated(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path, sandbox_executor=RecordingSandboxExecutor(_result(tmp_path=tmp_path)))
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(_checkpoint(schema_version=CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2))

    result = stage_initial_validation_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        session_id="session-1",
        validation_plan=_plan("python -m pytest tests/coding -q"),
        registry=registry,
        checkpoint_store=store,
    )

    assert result.status == "blocked_unsupported_schema"
    assert _store(tmp_path).list() == []


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


def _staged_with_persisted_result(
    tmp_path: Path,
    *,
    returncode: int = 0,
    stdout: str = "ok\n",
    write_artifact: bool = True,
    artifact_digest: str | None = None,
    result_digest: str | None = None,
    include_provenance_request: bool = True,
) -> tuple[SessionStore, object, SessionEvidenceReference, RecordingSandboxExecutor]:
    fake = RecordingSandboxExecutor(_result(stdout="unused\n", tmp_path=tmp_path))
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)
    session_store = _session_store_with_record(tmp_path)
    staged = stage_validation_cycle(_plan("python -m pytest tests/coding -q"), registry)
    action_id = staged.approval_token or "action-validation"
    logical_digest = logical_command_digest(staged.selection.normalized_command or "")
    nonce = "a" * 32
    artifact = ".pp-agent/validation-provenance/a.json"
    digest = result_digest or build_session_result_digest({"result": "validation", "action_id": action_id, "returncode": returncode})
    reference = _record_external_result(
        session_store,
        "session-1",
        action_id=action_id,
        result_digest=digest,
        logical_digest=logical_digest,
        returncode=returncode,
        stdout=stdout,
        nonce=nonce,
        artifact_relative_path=artifact,
        include_provenance_request=include_provenance_request,
    )
    if write_artifact:
        write_pytest_provenance_attestation(
            artifact_path=tmp_path / artifact,
            nonce=nonce,
            logical_command_digest=artifact_digest or logical_digest,
            pytest_exit_status=returncode,
        )
    return session_store, staged, reference, fake


def test_interpret_persisted_validation_result_does_not_execute_or_consume_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args, **_kwargs):  # pragma: no cover - must never be called
        raise AssertionError("forbidden direct execution path")

    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(pytest, "main", fail)
    session_store, staged, reference, fake = _staged_with_persisted_result(tmp_path)
    runtime_like = SimpleNamespace(prompt=fail, continue_=fail)

    result = interpret_persisted_validation_result(
        selection=staged.selection,
        evidence_reference=reference,
        session_store=session_store,
        workspace=tmp_path,
    )

    assert runtime_like.prompt
    assert result.status == "executed"
    assert result.outcome.final_status == "passed"
    assert result.outcome.repair_attempted is False
    assert result.outcome.revalidation_attempted is False
    assert fake.requests == []


def test_interpret_persisted_validation_result_records_trusted_tests_failed_evidence(tmp_path: Path) -> None:
    session_store, staged, reference, _fake = _staged_with_persisted_result(tmp_path, returncode=1, stdout="FAILED from pytest\n")

    result = interpret_persisted_validation_result(
        selection=staged.selection,
        evidence_reference=reference,
        session_store=session_store,
        workspace=tmp_path,
    )

    assert result.status == "executed"
    assert result.outcome.final_status == "failed"
    assert result.observation is not None
    assert result.observation.repair_eligible is True
    assert result.observation.pytest_completion_category == "tests_failed"
    lookup = session_store.lookup_validation_evidence(
        reference.session_id,
        action_id=reference.action_id or "",
        external_result_digest=reference.result_digest or "",
        logical_command_digest=logical_command_digest(staged.selection.normalized_command or ""),
    )
    assert lookup.status == SessionEvidenceLookupStatus.FOUND
    assert lookup.evidence is not None
    assert lookup.evidence.pytest_provenance_status == "valid"


def test_interpret_persisted_validation_result_missing_artifact_fails_closed(tmp_path: Path) -> None:
    session_store, staged, reference, _fake = _staged_with_persisted_result(tmp_path, returncode=1, stdout="FAILED\n", write_artifact=False)

    result = interpret_persisted_validation_result(
        selection=staged.selection,
        evidence_reference=reference,
        session_store=session_store,
        workspace=tmp_path,
    )

    assert result.status == "blocked"
    assert result.observation is not None
    assert result.observation.repair_eligible is False
    assert result.observation.failure_kind == "artifact_missing"


def test_interpret_persisted_validation_result_invalid_provenance_is_not_repairable(tmp_path: Path) -> None:
    session_store, staged, reference, _fake = _staged_with_persisted_result(tmp_path, returncode=1, artifact_digest="b" * 64)

    result = interpret_persisted_validation_result(
        selection=staged.selection,
        evidence_reference=reference,
        session_store=session_store,
        workspace=tmp_path,
    )

    assert result.status == "executed"
    assert result.observation is not None
    assert result.observation.validation_status == "validation_nonzero"
    assert result.observation.repair_eligible is False
    assert result.observation.pytest_provenance_status == "invalid"
    assert result.observation.failure_kind == "logical_command_digest_mismatch"


@pytest.mark.parametrize(
    "reference_update",
    [
        {"session_id": "missing-session"},
        {"action_id": "action-other"},
        {"message_id": "msg-other"},
        {"result_digest": build_session_result_digest({"result": "different"})},
    ],
)
def test_interpret_persisted_validation_result_identity_mismatch_fails_closed(
    tmp_path: Path,
    reference_update: dict[str, object],
) -> None:
    session_store, staged, reference, _fake = _staged_with_persisted_result(tmp_path)

    result = interpret_persisted_validation_result(
        selection=staged.selection,
        evidence_reference=reference.model_copy(update=reference_update),
        session_store=session_store,
        workspace=tmp_path,
    )

    assert result.status == "blocked"
    assert result.observation is not None
    assert result.observation.repair_eligible is False


def test_interpret_persisted_validation_result_command_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    fake = RecordingSandboxExecutor(_result(stdout="unused\n", tmp_path=tmp_path))
    registry = ToolRegistry(tmp_path, sandbox_executor=fake)
    session_store = _session_store_with_record(tmp_path)
    staged = stage_validation_cycle(_plan("python -m pytest tests/coding -q"), registry)
    digest = build_session_result_digest({"result": "validation", "action_id": staged.approval_token})
    reference = _record_external_result(
        session_store,
        "session-1",
        action_id=staged.approval_token or "",
        result_digest=digest,
        logical_digest="b" * 64,
    )

    result = interpret_persisted_validation_result(
        selection=staged.selection,
        evidence_reference=reference,
        session_store=session_store,
        workspace=tmp_path,
    )

    assert result.status == "blocked"
    assert result.observation is not None
    assert result.observation.failure_kind == "logical_command_digest_mismatch"


def test_existing_validation_evidence_is_idempotent_without_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_store, staged, reference, _fake = _staged_with_persisted_result(tmp_path, returncode=1)
    digest = logical_command_digest(staged.selection.normalized_command or "")
    evidence = SessionValidationEvidence(
        session_id=reference.session_id,
        action_id=reference.action_id or "",
        external_result_digest=reference.result_digest or "",
        logical_command_digest=digest,
        execution_status="executed",
        validation_status="failed",
        pytest_provenance_status="valid",
        pytest_completion_category="tests_failed",
        pytest_exit_status=1,
        failure_reason_code="pytest_tests_failed",
        completed_at=2.0,
        evidence_message_id="validation-evidence-existing",
    )
    session_store.append_validation_evidence(evidence)
    (tmp_path / ".pp-agent/validation-provenance/a.json").unlink()

    def fail(*_args, **_kwargs):  # pragma: no cover - must never be called
        raise AssertionError("verifier must not rerun when validation evidence exists")

    monkeypatch.setattr("pp_agent.coding.validation_execution.verify_pytest_provenance_attestation", fail)

    result = interpret_persisted_validation_result(
        selection=staged.selection,
        evidence_reference=reference,
        session_store=session_store,
        workspace=tmp_path,
    )

    assert result.status == "executed"
    assert result.observation is not None
    assert result.observation.repair_eligible is True
    assert result.details["validation_evidence"] == "found"


def test_artifact_deleted_without_validation_evidence_blocks_interpretation(tmp_path: Path) -> None:
    session_store, staged, reference, _fake = _staged_with_persisted_result(tmp_path, returncode=1)
    (tmp_path / ".pp-agent/validation-provenance/a.json").unlink()

    result = interpret_persisted_validation_result(
        selection=staged.selection,
        evidence_reference=reference,
        session_store=session_store,
        workspace=tmp_path,
    )

    assert result.status == "blocked"
    assert result.observation is not None
    assert result.observation.failure_kind == "artifact_missing"


def test_interpret_persisted_validation_result_append_failure_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_store, staged, reference, _fake = _staged_with_persisted_result(tmp_path)

    def fail_append(_evidence):
        raise RuntimeError("disk full")

    monkeypatch.setattr(session_store, "append_validation_evidence", fail_append)

    result = interpret_persisted_validation_result(
        selection=staged.selection,
        evidence_reference=reference,
        session_store=session_store,
        workspace=tmp_path,
    )

    assert result.status == "blocked"
    assert result.observation is not None
    assert result.observation.failure_kind == "validation_evidence_persistence_failed"


def test_stdout_text_does_not_create_trusted_test_failure_without_valid_provenance(tmp_path: Path) -> None:
    session_store, staged, reference, _fake = _staged_with_persisted_result(
        tmp_path,
        returncode=1,
        stdout="FAILED tests_failed everything is broken\n",
        artifact_digest="b" * 64,
    )

    result = interpret_persisted_validation_result(
        selection=staged.selection,
        evidence_reference=reference,
        session_store=session_store,
        workspace=tmp_path,
    )

    assert result.observation is not None
    assert result.observation.pytest_provenance_status == "invalid"
    assert result.observation.pytest_completion_category is None
    assert result.observation.repair_eligible is False
