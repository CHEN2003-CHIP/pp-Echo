from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import pp_agent.coding.workflow_recovery as workflow_recovery_module
from pp_agent.coding.workflow_checkpoint import (
    CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2,
    CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3,
    CodingWorkflowCheckpoint,
    CodingWorkflowCompletion,
    CodingWorkflowKind,
    CodingWorkflowPhase,
    CodingWorkflowTerminalKind,
    CodingWorkflowTerminalOutcome,
    ModelContinuationIntent,
    ModelContinuationState,
    PendingActionReference,
    PendingActionRole,
    SessionCompletionEvidenceReference,
    ValidationFinalStatus,
)
from pp_agent.coding.pytest_provenance import logical_command_digest, write_pytest_provenance_attestation
from pp_agent.coding.validation_execution import stage_validation_cycle
from pp_agent.coding.workflow_checkpoint_store import CodingWorkflowCheckpointStore, CheckpointStaleRevision
from pp_agent.coding.workflow_recovery import (
    CodingWorkflowBlockReason,
    CodingWorkflowDecision,
    inspect_coding_workflow,
    resume_coding_workflow,
)
from pp_agent.coding.testing import ValidationCommand, ValidationPlan
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.llm import ModelConfig
from pp_agent.runtime.runtime import AgentRuntime
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
from pp_agent.sandbox.base import SandboxRunResult
from pp_agent.tools.registry import ToolRegistry


class ScriptedLLMClient:
    def __init__(self, calls: list[dict[str, object]]) -> None:
        self.model = ModelConfig()
        self.calls = list(calls)
        self.call_count = 0
        self.seen_messages: list[list[ChatMessage]] = []

    def stream_chat(self, messages, tools=None) -> Iterator[dict[str, object]]:
        self.call_count += 1
        self.seen_messages.append(list(messages))
        if self.calls:
            yield self.calls.pop(0)
            return
        yield {"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class SpyCheckpointStore:
    def __init__(self, inner: CodingWorkflowCheckpointStore) -> None:
        self.inner = inner
        self.load_count = 0
        self.write_count = 0

    def load_checkpoint(self, workflow_id: str) -> CodingWorkflowCheckpoint:
        self.load_count += 1
        return self.inner.load_checkpoint(workflow_id)

    def create_checkpoint(self, checkpoint: CodingWorkflowCheckpoint) -> CodingWorkflowCheckpoint:
        self.write_count += 1
        raise AssertionError("inspection must not create checkpoints")

    def replace_checkpoint(self, checkpoint: CodingWorkflowCheckpoint, *, expected_revision: int) -> CodingWorkflowCheckpoint:
        self.write_count += 1
        raise AssertionError("inspection must not replace checkpoints")


class SpyPendingActionStore:
    def __init__(self, inner: PendingActionStore) -> None:
        self.inner = inner
        self.load_count = 0
        self.list_count = 0
        self.write_count = 0

    def load(self, token: str) -> dict[str, object]:
        self.load_count += 1
        return self.inner.load(token)

    def list(self) -> list[dict[str, object]]:
        self.list_count += 1
        return self.inner.list()

    def set_lifecycle(self, *_args: object, **_kwargs: object) -> None:
        self.write_count += 1
        raise AssertionError("inspection must not write pending action lifecycle")

    def stage(self, *_args: object, **_kwargs: object) -> None:
        self.write_count += 1
        raise AssertionError("inspection must not stage pending actions")


class SpySessionEvidenceStore:
    def __init__(self, inner: SessionStore) -> None:
        self.inner = inner
        self.lookup_count = 0
        self.write_count = 0

    def lookup_external_tool_result_evidence(self, session_id: str, *, action_id: str, result_digest: str | None = None):
        self.lookup_count += 1
        return self.inner.lookup_external_tool_result_evidence(session_id, action_id=action_id, result_digest=result_digest)

    def lookup_model_continuation_completion_evidence(self, session_id: str, *, continuation_id: str):
        self.lookup_count += 1
        return self.inner.lookup_model_continuation_completion_evidence(session_id, continuation_id=continuation_id)

    def lookup_external_result_details(self, evidence_reference: SessionEvidenceReference):
        self.lookup_count += 1
        return self.inner.lookup_external_result_details(evidence_reference)

    def lookup_pytest_provenance_request(self, evidence_reference: SessionEvidenceReference):
        self.lookup_count += 1
        return self.inner.lookup_pytest_provenance_request(evidence_reference)

    def lookup_validation_evidence(self, session_id: str, *, action_id: str, external_result_digest: str, logical_command_digest: str):
        self.lookup_count += 1
        return self.inner.lookup_validation_evidence(
            session_id,
            action_id=action_id,
            external_result_digest=external_result_digest,
            logical_command_digest=logical_command_digest,
        )

    def append_validation_evidence(self, *_args: object, **_kwargs: object):
        self.write_count += 1
        return self.inner.append_validation_evidence(*_args, **_kwargs)

    def save(self, *_args: object, **_kwargs: object) -> None:
        self.write_count += 1
        raise AssertionError("inspection must not write session state")


def _runtime(tmp_path: Path, llm: ScriptedLLMClient) -> AgentRuntime:
    session_store = SessionStore(tmp_path / "sessions")
    record = session_store.create("system", ModelConfig())
    runtime = AgentRuntime(
        llm_client=llm,
        tool_registry=ToolRegistry(tmp_path),
        session_store=session_store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        require_plan_approval=False,
    )
    runtime.restore_session_record(record)
    session_store.save(record)
    return runtime


def _checkpoint(
    *,
    workflow_id: str,
    session_id: str,
    ref: PendingActionReference | None = None,
    phase: CodingWorkflowPhase = CodingWorkflowPhase.TOOL_COMPLETED,
    schema_version: int = CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3,
    model_continuation_intent: ModelContinuationIntent | None = None,
) -> CodingWorkflowCheckpoint:
    now = datetime.now(timezone.utc)
    return CodingWorkflowCheckpoint(
        schema_version=schema_version,
        workflow_id=workflow_id,
        session_id=session_id,
        workflow_kind=CodingWorkflowKind.CONTROLLED_CODING,
        revision=0,
        phase=phase,
        validation_execution_count=0,
        repair_attempted=False,
        revalidation_attempted=False,
        pending_action_ref=ref if phase == CodingWorkflowPhase.AWAITING_TOOL_APPROVAL else None,
        last_completed_action_ref=ref if phase == CodingWorkflowPhase.TOOL_COMPLETED else None,
        model_continuation_intent=model_continuation_intent,
        created_at=now,
        updated_at=now,
    )


def _validation_checkpoint(
    *,
    workflow_id: str,
    session_id: str,
    phase: CodingWorkflowPhase,
    selected_digest: str = "a" * 64,
    pending_ref: PendingActionReference | None = None,
    completed_ref: PendingActionReference | None = None,
    validation_execution_count: int = 0,
    repair_attempted: bool = False,
    revalidation_attempted: bool = False,
    revision: int = 0,
    model_continuation_intent: ModelContinuationIntent | None = None,
) -> CodingWorkflowCheckpoint:
    now = datetime.now(timezone.utc)
    return CodingWorkflowCheckpoint(
        schema_version=CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3,
        workflow_id=workflow_id,
        session_id=session_id,
        workflow_kind=CodingWorkflowKind.CONTROLLED_CODING,
        revision=revision,
        phase=phase,
        selected_validation_command_digest=selected_digest,
        selected_validation_command_digest_algorithm="sha256",
        validation_execution_count=validation_execution_count,
        repair_attempted=repair_attempted,
        revalidation_attempted=revalidation_attempted,
        pending_action_ref=pending_ref,
        last_completed_action_ref=completed_ref,
        model_continuation_intent=model_continuation_intent,
        created_at=now,
        updated_at=now,
    )


def _validation_action(
    tmp_path: Path,
    runtime: AgentRuntime,
    *,
    role: PendingActionRole = PendingActionRole.VALIDATION,
    logical_digest: str = "a" * 64,
    lifecycle_state: str = "staged_not_granted",
    record_evidence: bool = False,
) -> PendingActionReference:
    result_payload = {
        "result": "ok",
        "details": {"logical_command_digest": logical_digest, "bounded": True},
        "success": True,
        "approval_action": "approve",
        "action_type": "stage_test_command",
        "source_tool_name": "approve_pending_action",
    }
    digest = build_session_result_digest(result_payload)
    checkpoint_digest = digest.removeprefix("sha256:")
    pending_store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    staged = pending_store.stage(
        action_type="stage_test_command",
        details={"session_id": runtime.session_id, "logical_command_digest": logical_digest},
        effect={
            "effect_id": f"effect-{role.value}",
            "payload_digest": checkpoint_digest,
            "tool_name": "stage_test_command",
            "analysis": {},
        },
        session_id=runtime.session_id,
    )
    pending_store.set_lifecycle(staged["token"], lifecycle_state)
    if record_evidence:
        runtime.record_external_approval_result(
            {
                "session_id": runtime.session_id,
                "token": staged["token"],
                "action_type": "stage_test_command",
                "source_tool_name": "approve_pending_action",
                "tool_call_id": "call-validation",
                "success": True,
                "approval_action": "approve",
                "approved": True,
                "result": result_payload["result"],
                "details": result_payload["details"],
            }
        )
    return PendingActionReference(
        action_id=staged["token"],
        role=role,
        action_digest=checkpoint_digest,
        action_type="stage_test_command",
    )


def _consumed_action_with_evidence(tmp_path: Path, runtime: AgentRuntime) -> PendingActionReference:
    digest = build_session_result_digest(
        {
            "result": "ok",
            "details": {"safe": True},
            "success": True,
            "approval_action": "approve",
            "action_type": "write_file",
            "source_tool_name": "approve_pending_action",
        }
    )
    checkpoint_digest = digest.removeprefix("sha256:")
    pending_store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    staged = pending_store.stage(
        action_type="write_file",
        details={"session_id": runtime.session_id},
        effect={"effect_id": "effect-1", "payload_digest": checkpoint_digest, "tool_name": "write_file", "analysis": {}},
        session_id=runtime.session_id,
    )
    pending_store.set_lifecycle(staged["token"], "grant_consumed")
    runtime.record_external_approval_result(
        {
            "session_id": runtime.session_id,
            "token": staged["token"],
            "action_type": "write_file",
            "source_tool_name": "approve_pending_action",
            "tool_call_id": "call-write",
            "success": True,
            "approval_action": "approve",
            "approved": True,
            "result": "ok",
            "details": {"safe": True},
        }
    )
    return PendingActionReference(
        action_id=staged["token"],
        role=PendingActionRole.TOOL,
        action_digest=checkpoint_digest,
        action_type="write_file",
    )


def _session_committed_intent(
    *,
    runtime: AgentRuntime,
    ref: PendingActionReference,
    continuation_id: str,
    committed_turn_id: str,
) -> ModelContinuationIntent:
    evidence = SessionCompletionEvidenceReference(
        session_id=runtime.session_id,
        continuation_id=continuation_id,
        source_action_id=ref.action_id,
        source_result_digest=ref.action_digest or "",
        committed_turn_id=committed_turn_id,
    )
    return ModelContinuationIntent(
        continuation_id=continuation_id,
        source_action_ref=ref,
        source_result_digest=ref.action_digest or "",
        pre_call_session_id=runtime.session_id,
        pre_call_turn_id="turn-before",
        state=ModelContinuationState.SESSION_COMMITTED,
        created_at=datetime.now(timezone.utc),
        completed_session_evidence_ref=evidence,
    )


def _repair_intent(session_id: str, ref: PendingActionReference) -> ModelContinuationIntent:
    return ModelContinuationIntent(
        continuation_id="repair-continuation",
        source_action_ref=ref,
        source_result_digest=ref.action_digest or "a" * 64,
        pre_call_session_id=session_id,
        pre_call_turn_id="turn-before",
        state=ModelContinuationState.INTENT_COMMITTED,
        created_at=datetime.now(timezone.utc),
    )


def _ordinary_completed_checkpoint(*, workflow_id: str, session_id: str, ref: PendingActionReference) -> CodingWorkflowCheckpoint:
    now = datetime.now(timezone.utc)
    evidence = SessionCompletionEvidenceReference(
        session_id=session_id,
        continuation_id="ordinary-continuation",
        source_action_id=ref.action_id,
        source_result_digest=ref.action_digest or "a" * 64,
        committed_turn_id="message-ordinary",
    )
    return CodingWorkflowCheckpoint(
        schema_version=CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3,
        workflow_id=workflow_id,
        session_id=session_id,
        workflow_kind=CodingWorkflowKind.CONTROLLED_CODING,
        revision=0,
        phase=CodingWorkflowPhase.COMPLETED,
        validation_execution_count=0,
        repair_attempted=False,
        revalidation_attempted=False,
        completion_marker=CodingWorkflowCompletion(completed_at=now),
        terminal_outcome=CodingWorkflowTerminalOutcome(
            terminal_kind=CodingWorkflowTerminalKind.ORDINARY_COMPLETION,
            completed_at=now,
            reason_code="ordinary_model_stop",
            session_completion_evidence_ref=evidence,
        ),
        created_at=now,
        updated_at=now,
    )


def _validation_plan(command: str = "python -m pytest tests/coding -q") -> ValidationPlan:
    return ValidationPlan(commands=[ValidationCommand(command=command, reason="resume validation")])


def _stage_consumed_validation_result(
    tmp_path: Path,
    runtime: AgentRuntime,
    *,
    returncode: int = 0,
    stdout: str = "ok\n",
    write_artifact: bool = True,
    artifact_digest: str | None = None,
    include_provenance_request: bool = True,
    mutate_pending_details: dict[str, object] | None = None,
) -> tuple[PendingActionReference, str, SessionEvidenceReference]:
    staged = stage_validation_cycle(_validation_plan(), ToolRegistry(tmp_path))
    action_id = staged.approval_token or ""
    digest = logical_command_digest(staged.selection.normalized_command or "")
    result_payload = {"result": "validation", "action_id": action_id, "returncode": returncode}
    result_digest = build_session_result_digest(result_payload)
    checkpoint_digest = result_digest.removeprefix("sha256:")
    pending_store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    payload = pending_store.load(action_id)
    payload["canonical_key"] = checkpoint_digest
    effect = payload.get("effect") if isinstance(payload.get("effect"), dict) else {}
    effect["payload_digest"] = checkpoint_digest
    payload["effect"] = effect
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    if mutate_pending_details:
        details.update(mutate_pending_details)
    payload["details"] = details
    pending_store.save(action_id, payload)
    pending_store.set_lifecycle(action_id, "grant_consumed")
    reference = _record_validation_external_result(
        runtime.session_store,
        runtime.session_id,
        action_id=action_id,
        result_digest=result_digest,
        logical_digest=digest,
        returncode=returncode,
        stdout=stdout,
        pending_details=details,
        include_provenance_request=include_provenance_request,
    )
    provenance = details.get("pytest_provenance_request") if isinstance(details, dict) else {}
    if write_artifact and isinstance(provenance, dict):
        write_pytest_provenance_attestation(
            artifact_path=tmp_path / str(provenance.get("artifact_relative_path") or ""),
            nonce=str(provenance.get("nonce") or ""),
            logical_command_digest=artifact_digest or digest,
            pytest_exit_status=returncode,
        )
    return (
        PendingActionReference(
            action_id=action_id,
            role=PendingActionRole.VALIDATION,
            action_digest=checkpoint_digest,
            action_type="run_shell",
        ),
        digest,
        reference,
    )


def _record_validation_external_result(
    session_store: SessionStore,
    session_id: str,
    *,
    action_id: str,
    result_digest: str,
    logical_digest: str,
    returncode: int,
    stdout: str,
    pending_details: dict[str, object],
    include_provenance_request: bool,
) -> SessionEvidenceReference:
    record = session_store.load(session_id)
    result_details: dict[str, object] = {
        "exit_code": returncode,
        "stdout": stdout,
        "stderr": "",
        "stdout_chars": len(stdout),
        "stderr_chars": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "timed_out": False,
        "logical_command_digest": logical_digest,
        "backend": "fake",
    }
    if isinstance(pending_details.get("test_command_proposal"), dict):
        result_details["test_command_proposal"] = dict(pending_details["test_command_proposal"])  # type: ignore[index]
    if include_provenance_request and isinstance(pending_details.get("pytest_provenance_request"), dict):
        result_details["pytest_provenance_request"] = dict(pending_details["pytest_provenance_request"])  # type: ignore[index]
    message = ChatMessage(
        role="tool",
        tool_call_id=f"call-{action_id}",
        tool_name="approve_pending_action",
        content=[TextPart(text="bounded validation result")],
        metadata={SESSION_MESSAGE_ID_KEY: f"msg-{action_id}"},
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


def _append_duplicate_last_session_message(session_store: SessionStore, session_id: str) -> None:
    record = session_store.load(session_id)
    branch_messages = session_store.branch_messages(record, record.active_head_id)
    duplicate = branch_messages[-1].model_copy(deep=True)
    session_store.save(
        session_store.sync_branch_state(
            record,
            base_head_id=record.active_head_id,
            branch_messages=[*branch_messages, duplicate],
            pending_plan_token=record.pending_plan_token,
            pending_tool_calls=record.pending_tool_calls,
        )
    )


@pytest.mark.parametrize(
    ("case", "expected_decision"),
    [
        ("awaiting_validation", CodingWorkflowDecision.AWAITING_VALIDATION_APPROVAL),
        ("consumed_with_evidence", CodingWorkflowDecision.VALIDATION_RESULT_READY),
        ("consumed_missing_evidence", CodingWorkflowDecision.VALIDATION_RESULT_MISSING),
        ("command_mismatch", CodingWorkflowDecision.CORRUPT_INCONSISTENT),
        ("failed", CodingWorkflowDecision.EXECUTION_FAILED),
        ("rejected", CodingWorkflowDecision.REJECTED),
        ("expired", CodingWorkflowDecision.EXPIRED),
        ("awaiting_revalidation", CodingWorkflowDecision.AWAITING_REVALIDATION_APPROVAL),
        ("completed", CodingWorkflowDecision.ORDINARY_COMPLETED),
        ("repair_uncertain", CodingWorkflowDecision.REPAIR_CONTINUATION_UNCERTAIN),
    ],
)
def test_mission_07_inspection_has_zero_side_effects(tmp_path: Path, case: str, expected_decision: CodingWorkflowDecision) -> None:
    llm = ScriptedLLMClient([])
    runtime = _runtime(tmp_path, llm)
    pending_store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    store = CodingWorkflowCheckpointStore(tmp_path)
    workflow_id = f"workflow-{case}"
    if case == "awaiting_validation":
        ref = _validation_action(tmp_path, runtime)
        checkpoint = _validation_checkpoint(
            workflow_id=workflow_id,
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            pending_ref=ref,
        )
    elif case == "consumed_with_evidence":
        ref = _validation_action(tmp_path, runtime, lifecycle_state="grant_consumed", record_evidence=True)
        checkpoint = _validation_checkpoint(
            workflow_id=workflow_id,
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            pending_ref=ref,
        )
    elif case == "consumed_missing_evidence":
        ref = _validation_action(tmp_path, runtime, lifecycle_state="grant_consumed")
        checkpoint = _validation_checkpoint(
            workflow_id=workflow_id,
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            pending_ref=ref,
        )
    elif case == "command_mismatch":
        ref = _validation_action(tmp_path, runtime, logical_digest="b" * 64, lifecycle_state="grant_consumed", record_evidence=True)
        checkpoint = _validation_checkpoint(
            workflow_id=workflow_id,
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            pending_ref=ref,
            selected_digest="a" * 64,
        )
    elif case in {"failed", "rejected", "expired"}:
        state = {"failed": "execution_failed", "rejected": "rejected", "expired": "expired"}[case]
        ref = _validation_action(tmp_path, runtime, lifecycle_state=state)
        checkpoint = _validation_checkpoint(
            workflow_id=workflow_id,
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            pending_ref=ref,
        )
    elif case == "awaiting_revalidation":
        ref = _validation_action(tmp_path, runtime, role=PendingActionRole.REVALIDATION)
        checkpoint = _validation_checkpoint(
            workflow_id=workflow_id,
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL,
            pending_ref=ref,
            validation_execution_count=1,
            repair_attempted=True,
            revalidation_attempted=True,
        )
    elif case == "completed":
        ref = _validation_action(tmp_path, runtime, lifecycle_state="grant_consumed", record_evidence=True)
        checkpoint = _ordinary_completed_checkpoint(workflow_id=workflow_id, session_id=runtime.session_id, ref=ref)
    else:
        ref = _validation_action(tmp_path, runtime, lifecycle_state="grant_consumed", record_evidence=True)
        checkpoint = _validation_checkpoint(
            workflow_id=workflow_id,
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.REPAIR_STARTED,
            completed_ref=ref,
            validation_execution_count=1,
            repair_attempted=True,
            model_continuation_intent=_repair_intent(runtime.session_id, ref),
        )
    store.create_checkpoint(checkpoint)
    checkpoint_spy = SpyCheckpointStore(store)
    pending_spy = SpyPendingActionStore(pending_store)
    session_spy = SpySessionEvidenceStore(runtime.session_store)

    inspection = inspect_coding_workflow(
        workspace=tmp_path,
        workflow_id=workflow_id,
        session_store=session_spy,
        pending_action_store=pending_spy,
        checkpoint_store=checkpoint_spy,
    )

    assert inspection.decision == expected_decision
    assert checkpoint_spy.write_count == 0
    assert pending_spy.write_count == 0
    assert session_spy.write_count == 0
    assert llm.call_count == 0


def test_inspect_exact_consumed_result_is_read_only_and_ready(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ScriptedLLMClient([]))
    ref = _consumed_action_with_evidence(tmp_path, runtime)
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(_checkpoint(workflow_id="workflow-1", session_id=runtime.session_id, ref=ref))

    before = store.load_checkpoint("workflow-1")
    inspection = inspect_coding_workflow(workspace=tmp_path, workflow_id="workflow-1", session_store=runtime.session_store)
    after = store.load_checkpoint("workflow-1")

    assert inspection.decision == CodingWorkflowDecision.READY_FOR_CONTINUATION_INTENT
    assert before == after
    assert runtime.llm_client.call_count == 0


def test_validation_consumed_result_discovery_does_not_require_action_digest_to_equal_result_digest(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ScriptedLLMClient([]))
    ref = _validation_action(tmp_path, runtime, lifecycle_state="grant_consumed", record_evidence=True)
    action_digest = "b" * 64
    pending_store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    payload = pending_store.load(ref.action_id)
    payload["canonical_key"] = action_digest
    effect = payload.get("effect") if isinstance(payload.get("effect"), dict) else {}
    effect["payload_digest"] = action_digest
    payload["effect"] = effect
    pending_store.save(ref.action_id, payload)
    ref = PendingActionReference(
        action_id=ref.action_id,
        role=PendingActionRole.VALIDATION,
        action_digest=action_digest,
        action_type=ref.action_type,
    )
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _validation_checkpoint(
            workflow_id="workflow-validation",
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            pending_ref=ref,
        )
    )

    inspection = inspect_coding_workflow(workspace=tmp_path, workflow_id="workflow-validation", session_store=runtime.session_store)

    assert inspection.decision == CodingWorkflowDecision.VALIDATION_RESULT_READY
    assert inspection.reason == CodingWorkflowBlockReason.NONE
    assert inspection.action_id == ref.action_id
    assert inspection.result_message_id is not None
    assert store.load_checkpoint("workflow-validation").pending_action_ref == ref


def test_v2_checkpoint_is_not_resumed_or_migrated(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ScriptedLLMClient([]))
    ref = _consumed_action_with_evidence(tmp_path, runtime)
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _checkpoint(
            workflow_id="workflow-1",
            session_id=runtime.session_id,
            ref=ref,
            schema_version=CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2,
        )
    )

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert result.inspection.decision == CodingWorkflowDecision.LEGACY_CHECKPOINT_NOT_RESUMABLE
    assert store.load_checkpoint("workflow-1").schema_version == CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2
    assert runtime.llm_client.call_count == 0


def test_validation_completed_without_action_ref_fails_closed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ScriptedLLMClient([]))
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _validation_checkpoint(
            workflow_id="workflow-1",
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.VALIDATION_COMPLETED,
            validation_execution_count=1,
        )
    )

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert result.inspection.decision == CodingWorkflowDecision.CORRUPT_INCONSISTENT
    assert result.inspection.reason == CodingWorkflowBlockReason.ACTION_MISSING
    assert runtime.llm_client.call_count == 0


def test_validation_pending_missing_action_fails_closed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ScriptedLLMClient([]))
    ref = PendingActionReference(
        action_id="missing-action",
        role=PendingActionRole.VALIDATION,
        action_digest="b" * 64,
        action_type="stage_test_command",
    )
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _validation_checkpoint(
            workflow_id="workflow-1",
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            pending_ref=ref,
        )
    )

    inspection = inspect_coding_workflow(workspace=tmp_path, workflow_id="workflow-1", session_store=runtime.session_store)

    assert inspection.decision == CodingWorkflowDecision.CORRUPT_INCONSISTENT
    assert inspection.reason == CodingWorkflowBlockReason.ACTION_MISSING


def test_validation_result_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ScriptedLLMClient([]))
    ref = _validation_action(tmp_path, runtime, lifecycle_state="grant_consumed", record_evidence=True)
    mismatched = PendingActionReference(
        action_id=ref.action_id,
        role=ref.role,
        action_digest="c" * 64,
        action_type=ref.action_type,
    )
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _validation_checkpoint(
            workflow_id="workflow-1",
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            pending_ref=mismatched,
        )
    )

    inspection = inspect_coding_workflow(workspace=tmp_path, workflow_id="workflow-1", session_store=runtime.session_store)

    assert inspection.decision == CodingWorkflowDecision.CORRUPT_INCONSISTENT
    assert inspection.reason == CodingWorkflowBlockReason.ACTION_IDENTITY_MISMATCH


def test_active_pending_action_conflicts_with_completed_validation_ref(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ScriptedLLMClient([]))
    completed = _validation_action(tmp_path, runtime, lifecycle_state="grant_consumed", record_evidence=True)
    _validation_action(tmp_path, runtime, lifecycle_state="staged_not_granted")
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _validation_checkpoint(
            workflow_id="workflow-1",
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.VALIDATION_COMPLETED,
            completed_ref=completed,
            validation_execution_count=1,
        )
    )

    inspection = inspect_coding_workflow(workspace=tmp_path, workflow_id="workflow-1", session_store=runtime.session_store)

    assert inspection.decision == CodingWorkflowDecision.CORRUPT_INCONSISTENT
    assert inspection.reason == CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN


def test_resume_commits_intent_before_single_model_continuation(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "ordinary completion", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    ref = _consumed_action_with_evidence(tmp_path, runtime)
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(_checkpoint(workflow_id="workflow-1", session_id=runtime.session_id, ref=ref))

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    checkpoint = store.load_checkpoint("workflow-1")

    assert result.model_continuation_attempted is True
    assert result.external_effect_count == 1
    assert llm.call_count == 1
    assert checkpoint.revision == 2
    assert checkpoint.phase == CodingWorkflowPhase.COMPLETED
    assert checkpoint.model_continuation_intent is not None
    assert checkpoint.model_continuation_intent.state == "session_committed"
    assert checkpoint.terminal_outcome is not None
    assert result.inspection.decision == CodingWorkflowDecision.ORDINARY_COMPLETED

    repeated = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=2,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    assert repeated.model_continuation_attempted is False
    assert repeated.external_effect_count == 0
    assert repeated.inspection.decision == CodingWorkflowDecision.ORDINARY_COMPLETED
    assert llm.call_count == 1


def test_session_committed_exact_evidence_finalizes_v3_completed_without_model_call(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "already committed", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    ref = _consumed_action_with_evidence(tmp_path, runtime)
    runtime.continue_(continuation_id="cont-existing", stop_after_model_boundary=True)
    completion = runtime.session_store.lookup_model_continuation_completion_evidence(runtime.session_id, continuation_id="cont-existing")
    assert completion.evidence is not None
    assert llm.call_count == 1

    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _checkpoint(
            workflow_id="workflow-1",
            session_id=runtime.session_id,
            ref=ref,
            model_continuation_intent=_session_committed_intent(
                runtime=runtime,
                ref=ref,
                continuation_id="cont-existing",
                committed_turn_id=completion.evidence.message_id,
            ),
        )
    )

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    checkpoint = store.load_checkpoint("workflow-1")

    assert result.model_continuation_attempted is False
    assert result.external_effect_count == 0
    assert llm.call_count == 1
    assert checkpoint.revision == 1
    assert checkpoint.phase == CodingWorkflowPhase.COMPLETED
    assert checkpoint.terminal_outcome is not None
    assert result.inspection.decision == CodingWorkflowDecision.ORDINARY_COMPLETED


def test_session_committed_continuation_mismatch_blocks_completion(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    ref = _consumed_action_with_evidence(tmp_path, runtime)
    runtime.continue_(continuation_id="cont-existing", stop_after_model_boundary=True)
    completion = runtime.session_store.lookup_model_continuation_completion_evidence(runtime.session_id, continuation_id="cont-existing")
    assert completion.evidence is not None
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _checkpoint(
            workflow_id="workflow-1",
            session_id=runtime.session_id,
            ref=ref,
            model_continuation_intent=_session_committed_intent(
                runtime=runtime,
                ref=ref,
                continuation_id="cont-missing",
                committed_turn_id=completion.evidence.message_id,
            ),
        )
    )

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert result.inspection.decision == CodingWorkflowDecision.BLOCKED_UNCERTAIN
    assert store.load_checkpoint("workflow-1").phase == CodingWorkflowPhase.TOOL_COMPLETED
    assert llm.call_count == 1


def test_active_pending_action_blocks_ordinary_completion(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    ref = _consumed_action_with_evidence(tmp_path, runtime)
    runtime.continue_(continuation_id="cont-existing", stop_after_model_boundary=True)
    completion = runtime.session_store.lookup_model_continuation_completion_evidence(runtime.session_id, continuation_id="cont-existing")
    assert completion.evidence is not None
    pending_store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    active = pending_store.stage(
        action_type="write_file",
        details={"session_id": runtime.session_id},
        effect={"effect_id": "effect-active", "payload_digest": "c" * 64, "tool_name": "write_file", "analysis": {}},
        session_id=runtime.session_id,
    )
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _checkpoint(
            workflow_id="workflow-1",
            session_id=runtime.session_id,
            ref=ref,
            model_continuation_intent=_session_committed_intent(
                runtime=runtime,
                ref=ref,
                continuation_id="cont-existing",
                committed_turn_id=completion.evidence.message_id,
            ),
        )
    )

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert result.inspection.decision == CodingWorkflowDecision.BLOCKED_UNCERTAIN
    assert result.inspection.action_id == active["token"]
    assert store.load_checkpoint("workflow-1").phase == CodingWorkflowPhase.TOOL_COMPLETED


def test_concurrent_same_revision_only_one_runtime_attempt(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    ref = _consumed_action_with_evidence(tmp_path, runtime)
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(_checkpoint(workflow_id="workflow-1", session_id=runtime.session_id, ref=ref))

    first = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    second = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert first.model_continuation_attempted is True
    assert second.inspection.decision == CodingWorkflowDecision.STALE_REVISION
    assert llm.call_count == 1


def test_boundary_continuation_stages_tool_without_execution(tmp_path: Path) -> None:
    llm = ScriptedLLMClient(
        [
            {
                "text": "",
                "tool_calls": [{"id": "call-write", "name": "write_file", "arguments_chunk": '{"path":"notes.txt","content":"alpha"}'}],
                "finish_reason": "tool_calls",
                "raw": {},
            }
        ]
    )
    runtime = _runtime(tmp_path, llm)

    runtime.continue_(continuation_id="cont-1", stop_after_model_boundary=True)
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()

    assert llm.call_count == 1
    assert pending and pending[0]["action_type"] == "planner_approval"
    assert runtime.state.pending_tool_calls[0].id == "call-write"
    assert not (tmp_path / "notes.txt").exists()
    assert runtime.session_store.lookup_model_continuation_completion_evidence(runtime.session_id, continuation_id="cont-1").status == "found"


def test_post_call_cas_failure_does_not_retry_model(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    ref = _consumed_action_with_evidence(tmp_path, runtime)
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(_checkpoint(workflow_id="workflow-1", session_id=runtime.session_id, ref=ref))
    original_replace = store.replace_checkpoint
    calls = {"count": 0}

    def flaky_replace(checkpoint: CodingWorkflowCheckpoint, *, expected_revision: int) -> CodingWorkflowCheckpoint:
        calls["count"] += 1
        if calls["count"] == 2:
            raise CheckpointStaleRevision("forced stale")
        return original_replace(checkpoint, expected_revision=expected_revision)

    store.replace_checkpoint = flaky_replace  # type: ignore[method-assign]

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert result.model_continuation_attempted is True
    assert result.inspection.decision == CodingWorkflowDecision.BLOCKED_UNCERTAIN
    assert llm.call_count == 1


def test_initial_validation_pass_resume_commits_completed_terminal(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([])
    runtime = _runtime(tmp_path, llm)
    ref, digest, _reference = _stage_consumed_validation_result(tmp_path, runtime, returncode=0)
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _validation_checkpoint(
            workflow_id="workflow-validation",
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            selected_digest=digest,
            pending_ref=ref,
        )
    )

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    checkpoint = store.load_checkpoint("workflow-validation")

    assert result.inspection.decision == CodingWorkflowDecision.COMPLETED
    assert result.external_effect_count == 0
    assert result.model_continuation_attempted is False
    assert llm.call_count == 0
    assert checkpoint.revision == 1
    assert checkpoint.phase == CodingWorkflowPhase.COMPLETED
    assert checkpoint.validation_execution_count == 1
    assert checkpoint.final_outcome_summary is not None
    assert checkpoint.final_outcome_summary.final_status == ValidationFinalStatus.PASSED
    assert checkpoint.terminal_outcome is not None
    assert checkpoint.terminal_outcome.terminal_kind == CodingWorkflowTerminalKind.VALIDATION_COMPLETION


def test_initial_validation_trusted_tests_failed_resume_stops_before_repair(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([])
    runtime = _runtime(tmp_path, llm)
    ref, digest, _reference = _stage_consumed_validation_result(tmp_path, runtime, returncode=1, stdout="FAILED\n")
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _validation_checkpoint(
            workflow_id="workflow-validation",
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            selected_digest=digest,
            pending_ref=ref,
        )
    )

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    checkpoint = store.load_checkpoint("workflow-validation")

    assert result.inspection.decision == CodingWorkflowDecision.SAFE_TO_START_REPAIR
    assert checkpoint.phase == CodingWorkflowPhase.VALIDATION_COMPLETED
    assert checkpoint.validation_execution_count == 1
    assert checkpoint.pending_action_ref is None
    assert checkpoint.last_completed_action_ref == ref
    assert checkpoint.repair_attempted is False
    assert checkpoint.revalidation_attempted is False
    assert checkpoint.final_outcome_summary is None
    assert checkpoint.terminal_outcome is None
    assert llm.call_count == 0


def _trusted_failed_validation_ready_for_repair(
    tmp_path: Path,
    runtime: AgentRuntime,
    *,
    workflow_id: str = "workflow-validation",
) -> tuple[CodingWorkflowCheckpointStore, PendingActionReference]:
    ref, digest, _reference = _stage_consumed_validation_result(tmp_path, runtime, returncode=1, stdout="FAILED\n")
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _validation_checkpoint(
            workflow_id=workflow_id,
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            selected_digest=digest,
            pending_ref=ref,
        )
    )
    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id=workflow_id,
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    assert result.inspection.decision == CodingWorkflowDecision.SAFE_TO_START_REPAIR
    return store, ref


def test_repair_resume_stale_revision_does_not_call_model(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "repair", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    store, _ref = _trusted_failed_validation_ready_for_repair(tmp_path, runtime)

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert result.inspection.decision == CodingWorkflowDecision.STALE_REVISION
    assert llm.call_count == 0
    assert store.load_checkpoint("workflow-validation").phase == CodingWorkflowPhase.VALIDATION_COMPLETED


def test_repair_resume_commits_intent_before_model_call(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "repair complete", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    store, _ref = _trusted_failed_validation_ready_for_repair(tmp_path, runtime)
    checkpoint = store.load_checkpoint("workflow-validation")
    original_replace = store.replace_checkpoint
    observed = {"intent_before_model": False}

    def spy_replace(replacement: CodingWorkflowCheckpoint, *, expected_revision: int) -> CodingWorkflowCheckpoint:
        if replacement.phase == CodingWorkflowPhase.REPAIR_STARTED:
            observed["intent_before_model"] = llm.call_count == 0 and replacement.repair_attempted is True
        return original_replace(replacement, expected_revision=expected_revision)

    store.replace_checkpoint = spy_replace  # type: ignore[method-assign]

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=checkpoint.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert observed["intent_before_model"] is True
    assert result.inspection.decision == CodingWorkflowDecision.REPAIR_COMPLETED_READY_FOR_REVALIDATION
    assert llm.call_count == 1


def test_repair_resume_model_exactly_once_and_repeated_resume_no_duplicate(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "repair complete", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    store, _ref = _trusted_failed_validation_ready_for_repair(tmp_path, runtime)
    checkpoint = store.load_checkpoint("workflow-validation")

    first = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=checkpoint.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    after_first = store.load_checkpoint("workflow-validation")
    second = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=after_first.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert first.inspection.decision == CodingWorkflowDecision.REPAIR_COMPLETED_READY_FOR_REVALIDATION
    assert second.inspection.decision == CodingWorkflowDecision.AWAITING_REVALIDATION_APPROVAL
    assert llm.call_count == 1
    assert after_first.phase == CodingWorkflowPhase.REPAIR_COMPLETED
    assert after_first.repair_attempted is True
    assert after_first.revalidation_attempted is False
    assert after_first.validation_execution_count == 1
    assert after_first.pending_action_ref is None
    after_second = store.load_checkpoint("workflow-validation")
    assert after_second.phase == CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL
    assert after_second.revalidation_attempted is True
    assert after_second.validation_execution_count == 1


def test_repair_resume_crash_after_intent_cas_before_completion_evidence_is_uncertain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    llm = ScriptedLLMClient([{"text": "not used", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    store, _ref = _trusted_failed_validation_ready_for_repair(tmp_path, runtime)
    checkpoint = store.load_checkpoint("workflow-validation")

    monkeypatch.setattr(workflow_recovery_module, "_run_repair_model_continuation", lambda *_args, **_kwargs: [])

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=checkpoint.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    after = store.load_checkpoint("workflow-validation")

    assert result.inspection.decision == CodingWorkflowDecision.REPAIR_CONTINUATION_UNCERTAIN
    assert result.inspection.reason == CodingWorkflowBlockReason.CONTINUATION_MISSING
    assert after.phase == CodingWorkflowPhase.REPAIR_STARTED
    assert after.repair_attempted is True
    assert after.validation_execution_count == 1
    assert llm.call_count == 0


def test_repair_intent_committed_without_evidence_does_not_retry(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "must not run", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    store, ref = _trusted_failed_validation_ready_for_repair(tmp_path, runtime)
    checkpoint = store.load_checkpoint("workflow-validation")
    intent_checkpoint = _validation_checkpoint(
        workflow_id="workflow-validation",
        session_id=runtime.session_id,
        phase=CodingWorkflowPhase.REPAIR_STARTED,
        selected_digest=checkpoint.selected_validation_command_digest or "a" * 64,
        completed_ref=ref,
        validation_execution_count=1,
        repair_attempted=True,
        revision=checkpoint.revision + 1,
        model_continuation_intent=_repair_intent(runtime.session_id, ref),
    )
    store.replace_checkpoint(intent_checkpoint, expected_revision=checkpoint.revision)

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=intent_checkpoint.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert result.inspection.decision == CodingWorkflowDecision.REPAIR_CONTINUATION_UNCERTAIN
    assert llm.call_count == 0
    assert store.load_checkpoint("workflow-validation").phase == CodingWorkflowPhase.REPAIR_STARTED


def test_repair_resume_tool_pending_stops_awaiting_repair_tool_approval(tmp_path: Path) -> None:
    llm = ScriptedLLMClient(
        [
            {
                "text": "",
                "tool_calls": [{"id": "call-write", "name": "write_file", "arguments_chunk": '{"path":"repair.txt","content":"fixed"}'}],
                "finish_reason": "tool_calls",
                "raw": {},
            }
        ]
    )
    runtime = _runtime(tmp_path, llm)
    store, _ref = _trusted_failed_validation_ready_for_repair(tmp_path, runtime)
    checkpoint = store.load_checkpoint("workflow-validation")

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=checkpoint.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    after = store.load_checkpoint("workflow-validation")

    assert result.inspection.decision == CodingWorkflowDecision.AWAITING_REPAIR_TOOL_APPROVAL
    assert llm.call_count == 1
    assert after.phase == CodingWorkflowPhase.AWAITING_REPAIR_TOOL_APPROVAL
    assert after.pending_action_ref is not None
    assert after.pending_action_ref.role == PendingActionRole.REPAIR_TOOL
    assert after.pending_action_ref.action_type == "planner_approval"
    assert after.repair_attempted is True
    assert after.revalidation_attempted is False
    assert not (tmp_path / "repair.txt").exists()


def test_repair_resume_blocked_model_completion_writes_terminal_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    llm = ScriptedLLMClient([{"text": "repair blocked", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    store, _ref = _trusted_failed_validation_ready_for_repair(tmp_path, runtime)
    checkpoint = store.load_checkpoint("workflow-validation")
    original = workflow_recovery_module._run_repair_model_continuation

    def blocked_run(*args: object, **kwargs: object) -> list[object]:
        original(*args, **kwargs)
        return [SimpleNamespace(is_error=True, details={"runtime_guardrail_blocked": True})]

    monkeypatch.setattr(workflow_recovery_module, "_run_repair_model_continuation", blocked_run)

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=checkpoint.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    after = store.load_checkpoint("workflow-validation")

    assert result.inspection.decision == CodingWorkflowDecision.COMPLETED
    assert llm.call_count == 1
    assert after.phase == CodingWorkflowPhase.COMPLETED
    assert after.final_outcome_summary is not None
    assert after.final_outcome_summary.final_status == ValidationFinalStatus.BLOCKED
    assert after.final_outcome_summary.repair_attempted is True
    assert after.final_outcome_summary.revalidation_attempted is False
    assert after.terminal_outcome is not None
    assert after.terminal_outcome.reason_code == "repair_continuation_blocked"


def _stage_revalidation_after_repair(tmp_path: Path, runtime: AgentRuntime) -> CodingWorkflowCheckpointStore:
    store, _ref = _trusted_failed_validation_ready_for_repair(tmp_path, runtime)
    checkpoint = store.load_checkpoint("workflow-validation")
    repair = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=checkpoint.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    assert repair.inspection.decision == CodingWorkflowDecision.REPAIR_COMPLETED_READY_FOR_REVALIDATION
    repaired = store.load_checkpoint("workflow-validation")
    staged = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=repaired.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    assert staged.inspection.decision == CodingWorkflowDecision.AWAITING_REVALIDATION_APPROVAL
    return store


def _consume_revalidation_result(
    tmp_path: Path,
    runtime: AgentRuntime,
    store: CodingWorkflowCheckpointStore,
    *,
    returncode: int = 0,
    stdout: str = "ok\n",
    write_artifact: bool = True,
    artifact_digest: str | None = None,
    include_provenance_request: bool = True,
) -> SessionEvidenceReference:
    checkpoint = store.load_checkpoint("workflow-validation")
    ref = checkpoint.pending_action_ref
    assert ref is not None
    assert ref.role == PendingActionRole.REVALIDATION
    pending_store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    payload = pending_store.load(ref.action_id)
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    pending_store.set_lifecycle(ref.action_id, "grant_consumed")
    result_digest = build_session_result_digest({"result": "revalidation", "action_id": ref.action_id, "returncode": returncode})
    reference = _record_validation_external_result(
        runtime.session_store,
        runtime.session_id,
        action_id=ref.action_id,
        result_digest=result_digest,
        logical_digest=checkpoint.selected_validation_command_digest or "",
        returncode=returncode,
        stdout=stdout,
        pending_details=details,
        include_provenance_request=include_provenance_request,
    )
    provenance = details.get("pytest_provenance_request") if isinstance(details, dict) else {}
    if write_artifact and isinstance(provenance, dict):
        write_pytest_provenance_attestation(
            artifact_path=tmp_path / str(provenance.get("artifact_relative_path") or ""),
            nonce=str(provenance.get("nonce") or ""),
            logical_command_digest=artifact_digest or checkpoint.selected_validation_command_digest or "",
            pytest_exit_status=returncode,
        )
    return reference


def test_repair_completed_resume_stages_same_command_revalidation(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "repair complete", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    store = _stage_revalidation_after_repair(tmp_path, runtime)
    checkpoint = store.load_checkpoint("workflow-validation")
    ref = checkpoint.pending_action_ref
    assert ref is not None
    action = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").load(ref.action_id)

    assert checkpoint.phase == CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL
    assert checkpoint.revalidation_attempted is True
    assert checkpoint.validation_execution_count == 1
    assert ref.role == PendingActionRole.REVALIDATION
    assert workflow_recovery_module._action_logical_command_digest(action) == checkpoint.selected_validation_command_digest
    assert llm.call_count == 1


def test_revalidation_staging_repeated_resume_does_not_create_second_action(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "repair complete", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    store = _stage_revalidation_after_repair(tmp_path, runtime)
    checkpoint = store.load_checkpoint("workflow-validation")
    pending_store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    before_tokens = {item["token"] for item in pending_store.list()}

    repeated = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=checkpoint.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    after_tokens = {item["token"] for item in pending_store.list()}

    assert repeated.inspection.decision == CodingWorkflowDecision.AWAITING_REVALIDATION_APPROVAL
    assert after_tokens == before_tokens
    assert llm.call_count == 1
    assert store.load_checkpoint("workflow-validation").validation_execution_count == 1


def test_revalidation_staging_stale_revision_does_not_stage_action(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "repair complete", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    store, _ref = _trusted_failed_validation_ready_for_repair(tmp_path, runtime)
    checkpoint = store.load_checkpoint("workflow-validation")
    repair = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=checkpoint.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    assert repair.inspection.decision == CodingWorkflowDecision.REPAIR_COMPLETED_READY_FOR_REVALIDATION
    repaired = store.load_checkpoint("workflow-validation")
    pending_store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    before_count = len(pending_store.list())

    stale = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=repaired.revision - 1,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert stale.inspection.decision == CodingWorkflowDecision.STALE_REVISION
    assert len(pending_store.list()) == before_count
    assert llm.call_count == 1


def test_revalidation_staging_post_stage_cas_failure_reports_orphan_risk(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "repair complete", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    store, _ref = _trusted_failed_validation_ready_for_repair(tmp_path, runtime)
    checkpoint = store.load_checkpoint("workflow-validation")
    repair = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=checkpoint.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    assert repair.inspection.decision == CodingWorkflowDecision.REPAIR_COMPLETED_READY_FOR_REVALIDATION
    repaired = store.load_checkpoint("workflow-validation")
    original_replace = store.replace_checkpoint

    def stale_replace(replacement: CodingWorkflowCheckpoint, *, expected_revision: int) -> CodingWorkflowCheckpoint:
        if replacement.phase == CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL:
            raise CheckpointStaleRevision("forced stale")
        return original_replace(replacement, expected_revision=expected_revision)

    store.replace_checkpoint = stale_replace  # type: ignore[method-assign]

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=repaired.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert result.inspection.decision == CodingWorkflowDecision.STALE_REVISION
    assert any(
        workflow_recovery_module._action_logical_command_digest(item) == repaired.selected_validation_command_digest
        for item in PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    )
    assert store.load_checkpoint("workflow-validation").phase == CodingWorkflowPhase.REPAIR_COMPLETED


def test_revalidation_pass_terminal_completion_count_two(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "repair complete", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    store = _stage_revalidation_after_repair(tmp_path, runtime)
    _consume_revalidation_result(tmp_path, runtime, store, returncode=0)
    ready = inspect_coding_workflow(workspace=tmp_path, workflow_id="workflow-validation", session_store=runtime.session_store)
    checkpoint = store.load_checkpoint("workflow-validation")

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=checkpoint.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    completed = store.load_checkpoint("workflow-validation")

    assert ready.decision == CodingWorkflowDecision.REVALIDATION_RESULT_READY
    assert result.inspection.decision == CodingWorkflowDecision.COMPLETED
    assert completed.validation_execution_count == 2
    assert completed.repair_attempted is True
    assert completed.revalidation_attempted is True
    assert completed.final_outcome_summary is not None
    assert completed.final_outcome_summary.final_status == ValidationFinalStatus.PASSED
    assert completed.terminal_outcome is not None
    assert completed.terminal_outcome.terminal_kind == CodingWorkflowTerminalKind.VALIDATION_COMPLETION
    assert llm.call_count == 1


def test_revalidation_trusted_tests_failed_terminal_failed_without_second_repair(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "repair complete", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    store = _stage_revalidation_after_repair(tmp_path, runtime)
    _consume_revalidation_result(tmp_path, runtime, store, returncode=1, stdout="FAILED\n")
    checkpoint = store.load_checkpoint("workflow-validation")

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=checkpoint.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    completed = store.load_checkpoint("workflow-validation")
    repeated = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=completed.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert result.inspection.decision == CodingWorkflowDecision.COMPLETED
    assert repeated.inspection.decision == CodingWorkflowDecision.COMPLETED
    assert completed.validation_execution_count == 2
    assert completed.final_outcome_summary is not None
    assert completed.final_outcome_summary.final_status == ValidationFinalStatus.FAILED
    assert completed.final_outcome_summary.pytest_completion_category == "tests_failed"
    assert llm.call_count == 1


def test_revalidation_missing_provenance_terminal_blocked(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "repair complete", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    store = _stage_revalidation_after_repair(tmp_path, runtime)
    _consume_revalidation_result(tmp_path, runtime, store, returncode=1, include_provenance_request=False)
    checkpoint = store.load_checkpoint("workflow-validation")

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=checkpoint.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    completed = store.load_checkpoint("workflow-validation")

    assert result.inspection.decision == CodingWorkflowDecision.COMPLETED
    assert completed.validation_execution_count == 2
    assert completed.final_outcome_summary is not None
    assert completed.final_outcome_summary.final_status == ValidationFinalStatus.BLOCKED
    assert completed.repair_attempted is True
    assert completed.revalidation_attempted is True
    assert llm.call_count == 1


@pytest.mark.parametrize(
    ("write_artifact", "artifact_digest", "expected_failure"),
    [
        (False, None, "artifact_missing"),
        (True, "b" * 64, "logical_command_digest_mismatch"),
    ],
)
def test_initial_validation_blocked_resume_commits_validation_terminal(
    tmp_path: Path,
    write_artifact: bool,
    artifact_digest: str | None,
    expected_failure: str,
) -> None:
    runtime = _runtime(tmp_path, ScriptedLLMClient([]))
    ref, digest, _reference = _stage_consumed_validation_result(
        tmp_path,
        runtime,
        returncode=1,
        write_artifact=write_artifact,
        artifact_digest=artifact_digest,
    )
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _validation_checkpoint(
            workflow_id="workflow-validation",
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            selected_digest=digest,
            pending_ref=ref,
        )
    )

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    checkpoint = store.load_checkpoint("workflow-validation")

    assert result.inspection.decision == CodingWorkflowDecision.COMPLETED
    assert checkpoint.validation_execution_count == 1
    assert checkpoint.final_outcome_summary is not None
    assert checkpoint.final_outcome_summary.final_status == ValidationFinalStatus.BLOCKED
    assert checkpoint.final_outcome_summary.failure_reason_code == expected_failure
    assert checkpoint.terminal_outcome is not None
    assert checkpoint.terminal_outcome.terminal_kind == CodingWorkflowTerminalKind.VALIDATION_COMPLETION
    assert checkpoint.repair_attempted is False


def test_initial_validation_resume_missing_pending_command_payload_fails_before_interpretation(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ScriptedLLMClient([]))
    ref, digest, _reference = _stage_consumed_validation_result(
        tmp_path,
        runtime,
        returncode=0,
        mutate_pending_details={"test_command_proposal": {}},
    )
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _validation_checkpoint(
            workflow_id="workflow-validation",
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            selected_digest=digest,
            pending_ref=ref,
        )
    )
    before_messages = len(runtime.session_store.load(runtime.session_id).messages)

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert result.inspection.decision == CodingWorkflowDecision.CORRUPT_INCONSISTENT
    assert result.inspection.reason == CodingWorkflowBlockReason.VALIDATION_COMMAND_MISMATCH
    assert store.load_checkpoint("workflow-validation").revision == 0
    assert len(runtime.session_store.load(runtime.session_id).messages) == before_messages


def test_initial_validation_ambiguous_external_evidence_fails_closed_without_checkpoint_write(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ScriptedLLMClient([]))
    ref, digest, _reference = _stage_consumed_validation_result(tmp_path, runtime, returncode=0)
    _append_duplicate_last_session_message(runtime.session_store, runtime.session_id)
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _validation_checkpoint(
            workflow_id="workflow-validation",
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            selected_digest=digest,
            pending_ref=ref,
        )
    )

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert result.inspection.decision == CodingWorkflowDecision.VALIDATION_RESULT_MISSING
    assert result.inspection.reason == CodingWorkflowBlockReason.RESULT_AMBIGUOUS
    assert store.load_checkpoint("workflow-validation").revision == 0
    assert runtime.llm_client.call_count == 0


def test_initial_validation_corrupt_external_evidence_fails_closed_without_checkpoint_write(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ScriptedLLMClient([]))
    ref, digest, _reference = _stage_consumed_validation_result(tmp_path, runtime, returncode=0)
    session_store = SpySessionEvidenceStore(runtime.session_store)
    session_store.lookup_external_result_details = lambda _reference: SimpleNamespace(  # type: ignore[method-assign]
        status=SessionEvidenceLookupStatus.SESSION_CORRUPT,
        details=None,
        reason="invalid_external_result_record",
    )
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _validation_checkpoint(
            workflow_id="workflow-validation",
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            selected_digest=digest,
            pending_ref=ref,
        )
    )

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=0,
        runtime=runtime,
        session_store=session_store,
        checkpoint_store=store,
    )

    assert result.inspection.decision == CodingWorkflowDecision.CORRUPT_INCONSISTENT
    assert result.inspection.reason == CodingWorkflowBlockReason.VALIDATION_COMMAND_MISMATCH
    assert store.load_checkpoint("workflow-validation").revision == 0
    assert runtime.llm_client.call_count == 0


def test_initial_validation_resume_stale_revision_happens_before_validation_evidence_write(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ScriptedLLMClient([]))
    ref, digest, _reference = _stage_consumed_validation_result(tmp_path, runtime, returncode=0)
    store = CodingWorkflowCheckpointStore(tmp_path)
    initial = store.create_checkpoint(
        _validation_checkpoint(
            workflow_id="workflow-validation",
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            selected_digest=digest,
            pending_ref=ref,
        )
    )
    store.replace_checkpoint(
        _validation_checkpoint(
            workflow_id="workflow-validation",
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            selected_digest=digest,
            pending_ref=ref,
            revision=1,
        ),
        expected_revision=initial.revision,
    )
    session_spy = SpySessionEvidenceStore(runtime.session_store)

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=0,
        runtime=runtime,
        session_store=session_spy,
        checkpoint_store=store,
    )

    assert result.inspection.decision == CodingWorkflowDecision.STALE_REVISION
    assert session_spy.write_count == 0
    assert runtime.llm_client.call_count == 0
    assert store.load_checkpoint("workflow-validation").revision == 1


def test_initial_validation_repeated_resume_does_not_increment_count_or_rerun_verifier(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ScriptedLLMClient([]))
    ref, digest, _reference = _stage_consumed_validation_result(tmp_path, runtime, returncode=0)
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(
        _validation_checkpoint(
            workflow_id="workflow-validation",
            session_id=runtime.session_id,
            phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
            selected_digest=digest,
            pending_ref=ref,
        )
    )
    first = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    checkpoint = store.load_checkpoint("workflow-validation")

    second = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-validation",
        expected_revision=checkpoint.revision,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert first.inspection.decision == CodingWorkflowDecision.COMPLETED
    assert second.inspection.decision == CodingWorkflowDecision.COMPLETED
    assert store.load_checkpoint("workflow-validation").validation_execution_count == 1
    assert store.load_checkpoint("workflow-validation").revision == checkpoint.revision
    assert runtime.llm_client.call_count == 0
