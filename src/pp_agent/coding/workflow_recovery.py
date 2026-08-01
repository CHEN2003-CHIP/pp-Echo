from __future__ import annotations

import time
import uuid
import importlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from pp_agent.coding.workflow_checkpoint import (
    CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3,
    CodingWorkflowCheckpoint,
    CodingWorkflowCompletion,
    CodingWorkflowPhase,
    CodingWorkflowTerminalKind,
    CodingWorkflowTerminalOutcome,
    ModelContinuationIntent,
    ModelContinuationState,
    PendingActionReference,
    PendingActionRole,
    SessionCompletionEvidenceReference,
    ValidationFinalStatus,
    ValidationOutcomeSummary,
)
from pp_agent.coding.workflow_checkpoint_store import (
    CheckpointCorrupt,
    CheckpointIdentityMismatch,
    CheckpointIntegrityFailure,
    CheckpointInvariantViolation,
    CheckpointLockUnavailable,
    CheckpointNotFound,
    CheckpointStaleRevision,
    CheckpointStorageError,
    CheckpointUnsupportedSchema,
    CodingWorkflowCheckpointStore,
)
from pp_agent.coding.pytest_provenance import logical_command_digest
from pp_agent.coding.validation_execution import interpret_persisted_validation_result, stage_selected_validation_cycle
from pp_agent.coding.validation_repair import build_validation_repair_prompt
from pp_agent.coding.validation_outcome import SelectedValidationCommand
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.storage.sessions import SessionEvidenceReference, ensure_session_message_id


class SessionEvidenceLookupStatus:
    FOUND = "found"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    SESSION_CORRUPT = "session_corrupt"
    IDENTITY_MISMATCH = "identity_mismatch"


class SessionEvidenceStore(Protocol):
    def lookup_external_tool_result_evidence(self, session_id: str, *, action_id: str, result_digest: str | None = None) -> Any:
        ...

    def lookup_model_continuation_completion_evidence(self, session_id: str, *, continuation_id: str) -> Any:
        ...

    def lookup_external_result_details(self, evidence_reference: SessionEvidenceReference) -> Any:
        ...

    def lookup_pytest_provenance_request(self, evidence_reference: SessionEvidenceReference) -> Any:
        ...

    def lookup_validation_evidence(
        self,
        session_id: str,
        *,
        action_id: str,
        external_result_digest: str,
        logical_command_digest: str,
    ) -> Any:
        ...

    def append_validation_evidence(self, evidence: Any) -> Any:
        ...


class PendingActionReader(Protocol):
    def load(self, token: str) -> dict[str, Any]:
        ...

    def list(self) -> list[dict[str, Any]]:
        ...


class CodingWorkflowDecision(str, Enum):
    COMPLETED = "completed"
    AWAITING_APPROVAL = "awaiting_approval"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_UNCERTAIN = "execution_uncertain"
    DURABLE_RESULT_UNAVAILABLE = "durable_result_unavailable"
    READY_FOR_CONTINUATION_INTENT = "ready_for_continuation_intent"
    CONTINUATION_INTENT_COMMITTED = "continuation_intent_committed"
    CONTINUATION_COMPLETED_IN_SESSION = "continuation_completed_in_session"
    BLOCKED_UNCERTAIN = "blocked_uncertain"
    STALE_REVISION = "stale_revision"
    CORRUPT_INCONSISTENT = "corrupt_inconsistent"
    MISSION_07_DEFERRED = "mission_07_deferred"
    LEGACY_CHECKPOINT_NOT_RESUMABLE = "legacy_checkpoint_not_resumable"
    CHECKPOINT_MISSING = "checkpoint_missing"
    ORDINARY_COMPLETED = "ordinary_completed"
    AWAITING_VALIDATION_APPROVAL = "awaiting_validation_approval"
    VALIDATION_RESULT_READY = "validation_result_ready"
    VALIDATION_RESULT_MISSING = "validation_result_missing"
    REPAIR_CONTINUATION_UNCERTAIN = "repair_continuation_uncertain"
    AWAITING_REPAIR_TOOL_APPROVAL = "awaiting_repair_tool_approval"
    REPAIR_COMPLETED_READY_FOR_REVALIDATION = "repair_completed_ready_for_revalidation"
    AWAITING_REVALIDATION_APPROVAL = "awaiting_revalidation_approval"
    REVALIDATION_RESULT_READY = "revalidation_result_ready"
    FINAL_VALIDATION_COMPLETION_READY = "final_validation_completion_ready"
    SAFE_TO_START_REPAIR = "safe_to_start_repair"


class CodingWorkflowBlockReason(str, Enum):
    NONE = "none"
    CHECKPOINT_MISSING = "checkpoint_missing"
    CHECKPOINT_CORRUPT = "checkpoint_corrupt"
    CHECKPOINT_UNSUPPORTED = "checkpoint_unsupported"
    CHECKPOINT_STALE = "checkpoint_stale"
    CHECKPOINT_LOCK_UNAVAILABLE = "checkpoint_lock_unavailable"
    SESSION_MISSING = "session_missing"
    SESSION_CORRUPT = "session_corrupt"
    SESSION_IDENTITY_MISMATCH = "session_identity_mismatch"
    ACTION_MISSING = "action_missing"
    ACTION_IDENTITY_MISMATCH = "action_identity_mismatch"
    ACTION_STATE_UNCERTAIN = "action_state_uncertain"
    RESULT_MISSING = "result_missing"
    RESULT_AMBIGUOUS = "result_ambiguous"
    RESULT_MISMATCH = "result_mismatch"
    CONTINUATION_MISSING = "continuation_missing"
    CONTINUATION_AMBIGUOUS = "continuation_ambiguous"
    CONTINUATION_RUNTIME_FAILED = "continuation_runtime_failed"
    POST_CALL_CAS_FAILED = "post_call_cas_failed"
    MISSION_07_DEFERRED = "mission_07_deferred"
    LEGACY_NOT_RESUMABLE = "legacy_not_resumable"
    VALIDATION_COMMAND_MISMATCH = "validation_command_mismatch"
    VALIDATION_EVIDENCE_MISSING = "validation_evidence_missing"
    VALIDATION_EVIDENCE_BLOCKED = "validation_evidence_blocked"


@dataclass(frozen=True)
class CodingWorkflowInspection:
    workflow_id: str
    decision: CodingWorkflowDecision
    reason: CodingWorkflowBlockReason = CodingWorkflowBlockReason.NONE
    checkpoint_revision: int | None = None
    session_id: str | None = None
    action_id: str | None = None
    action_state: str | None = None
    continuation_id: str | None = None
    completion_message_id: str | None = None
    result_message_id: str | None = None


@dataclass(frozen=True)
class CodingWorkflowResumeResult:
    workflow_id: str
    inspection: CodingWorkflowInspection
    external_effect_count: int = 0
    model_continuation_attempted: bool = False
    checkpoint_revision: int | None = None


class RuntimeContinuation(Protocol):
    def continue_(self, continuation_id: str | None = None, *, stop_after_model_boundary: bool = False) -> list[Any]:
        ...

    def enqueue_message(self, text: str, delivery: str = "follow_up") -> Any:
        ...


_MISSION_07_PHASES = {
    CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
    CodingWorkflowPhase.VALIDATION_COMPLETED,
    CodingWorkflowPhase.REPAIR_STARTED,
    CodingWorkflowPhase.AWAITING_REPAIR_TOOL_APPROVAL,
    CodingWorkflowPhase.REPAIR_COMPLETED,
    CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL,
    CodingWorkflowPhase.REVALIDATION_COMPLETED,
    CodingWorkflowPhase.FINALIZED,
}
_AWAITING_PHASES = {
    CodingWorkflowPhase.AWAITING_TOOL_APPROVAL,
    CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
    CodingWorkflowPhase.AWAITING_REPAIR_TOOL_APPROVAL,
    CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL,
}
_ACTIVE_ACTION_STATES = {"active", "staged_not_granted", "grant_attached"}
_FAILED_ACTION_STATES = {"execution_failed", "rejected", "denied", "expired", "grant_invalidated", "orphaned", "quarantined"}


def inspect_coding_workflow(
    *,
    workspace: Path,
    workflow_id: str,
    session_store: SessionEvidenceStore,
    pending_action_store: PendingActionReader | None = None,
    checkpoint_store: CodingWorkflowCheckpointStore | None = None,
) -> CodingWorkflowInspection:
    store = checkpoint_store or CodingWorkflowCheckpointStore(workspace)
    pending_store = pending_action_store or _default_pending_action_store(Path(workspace))
    try:
        checkpoint = store.load_checkpoint(workflow_id)
    except CheckpointNotFound:
        return CodingWorkflowInspection(workflow_id, CodingWorkflowDecision.CHECKPOINT_MISSING, CodingWorkflowBlockReason.CHECKPOINT_MISSING)
    except CheckpointUnsupportedSchema:
        return CodingWorkflowInspection(workflow_id, CodingWorkflowDecision.CORRUPT_INCONSISTENT, CodingWorkflowBlockReason.CHECKPOINT_UNSUPPORTED)
    except (CheckpointCorrupt, CheckpointIntegrityFailure, CheckpointInvariantViolation, CheckpointIdentityMismatch, CheckpointStorageError):
        return CodingWorkflowInspection(workflow_id, CodingWorkflowDecision.CORRUPT_INCONSISTENT, CodingWorkflowBlockReason.CHECKPOINT_CORRUPT)
    return _inspect_checkpoint(checkpoint, session_store=session_store, pending_action_store=pending_store)


def resume_coding_workflow(
    *,
    workspace: Path,
    workflow_id: str,
    expected_revision: int,
    runtime: RuntimeContinuation,
    session_store: SessionEvidenceStore,
    pending_action_store: PendingActionReader | None = None,
    checkpoint_store: CodingWorkflowCheckpointStore | None = None,
) -> CodingWorkflowResumeResult:
    store = checkpoint_store or CodingWorkflowCheckpointStore(workspace)
    pending_store = pending_action_store or _default_pending_action_store(Path(workspace))
    inspection = inspect_coding_workflow(
        workspace=workspace,
        workflow_id=workflow_id,
        session_store=session_store,
        pending_action_store=pending_store,
        checkpoint_store=store,
    )
    if inspection.checkpoint_revision is not None and inspection.checkpoint_revision != expected_revision:
        stale = CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=inspection.checkpoint_revision,
            session_id=inspection.session_id,
            action_id=inspection.action_id,
            action_state=inspection.action_state,
            continuation_id=inspection.continuation_id,
        )
        return CodingWorkflowResumeResult(workflow_id, stale, checkpoint_revision=inspection.checkpoint_revision)
    if inspection.decision == CodingWorkflowDecision.CONTINUATION_COMPLETED_IN_SESSION:
        finalized = _finalize_session_committed_completion(
            store=store,
            workflow_id=workflow_id,
            expected_revision=expected_revision,
            session_store=session_store,
            pending_action_store=pending_store,
        )
        return CodingWorkflowResumeResult(workflow_id, finalized, checkpoint_revision=finalized.checkpoint_revision)
    if inspection.decision == CodingWorkflowDecision.VALIDATION_RESULT_READY:
        consumed = _resume_initial_validation_result(
            store=store,
            workflow_id=workflow_id,
            expected_revision=expected_revision,
            session_store=session_store,
            pending_action_store=pending_store,
            workspace=workspace,
        )
        return CodingWorkflowResumeResult(workflow_id, consumed, checkpoint_revision=consumed.checkpoint_revision)
    if inspection.decision == CodingWorkflowDecision.SAFE_TO_START_REPAIR:
        repair = _resume_repair_continuation(
            store=store,
            workflow_id=workflow_id,
            expected_revision=expected_revision,
            runtime=runtime,
            session_store=session_store,
            pending_action_store=pending_store,
            workspace=workspace,
        )
        return CodingWorkflowResumeResult(
            workflow_id,
            repair,
            external_effect_count=1 if repair.continuation_id else 0,
            model_continuation_attempted=repair.continuation_id is not None,
            checkpoint_revision=repair.checkpoint_revision,
        )
    if inspection.decision == CodingWorkflowDecision.REPAIR_COMPLETED_READY_FOR_REVALIDATION:
        repaired = _resume_repair_completed_ready_for_revalidation(
            store=store,
            workflow_id=workflow_id,
            expected_revision=expected_revision,
            runtime=runtime,
            session_store=session_store,
            pending_action_store=pending_store,
            workspace=workspace,
        )
        return CodingWorkflowResumeResult(workflow_id, repaired, checkpoint_revision=repaired.checkpoint_revision)
    if inspection.decision == CodingWorkflowDecision.REVALIDATION_RESULT_READY:
        revalidated = _resume_revalidation_result(
            store=store,
            workflow_id=workflow_id,
            expected_revision=expected_revision,
            session_store=session_store,
            pending_action_store=pending_store,
            workspace=workspace,
        )
        return CodingWorkflowResumeResult(workflow_id, revalidated, checkpoint_revision=revalidated.checkpoint_revision)
    if inspection.decision != CodingWorkflowDecision.READY_FOR_CONTINUATION_INTENT:
        return CodingWorkflowResumeResult(workflow_id, inspection, checkpoint_revision=inspection.checkpoint_revision)

    try:
        checkpoint = store.load_checkpoint(workflow_id)
    except CheckpointStorageError:
        blocked = _blocked(workflow_id, CodingWorkflowBlockReason.CHECKPOINT_CORRUPT)
        return CodingWorkflowResumeResult(workflow_id, blocked)
    if checkpoint.revision != expected_revision:
        stale = CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
        return CodingWorkflowResumeResult(workflow_id, stale, checkpoint_revision=checkpoint.revision)

    refreshed = _inspect_checkpoint(checkpoint, session_store=session_store, pending_action_store=pending_store)
    if refreshed.decision != CodingWorkflowDecision.READY_FOR_CONTINUATION_INTENT:
        return CodingWorkflowResumeResult(workflow_id, refreshed, checkpoint_revision=checkpoint.revision)
    source_ref = checkpoint.last_completed_action_ref or checkpoint.pending_action_ref
    if source_ref is None or source_ref.action_digest is None:
        blocked = CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.DURABLE_RESULT_UNAVAILABLE,
            CodingWorkflowBlockReason.RESULT_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=source_ref.action_id if source_ref else None,
        )
        return CodingWorkflowResumeResult(workflow_id, blocked, checkpoint_revision=checkpoint.revision)

    continuation_id = f"coding-cont-{uuid.uuid4().hex}"
    intent_checkpoint = _replace_checkpoint_fields(
        checkpoint,
        revision=checkpoint.revision + 1,
        phase=CodingWorkflowPhase.TOOL_COMPLETED,
        pending_action_ref=None,
        last_completed_action_ref=source_ref,
        updated_at=datetime.now(timezone.utc),
        model_continuation_intent=ModelContinuationIntent(
            continuation_id=continuation_id,
            source_action_ref=source_ref,
            source_result_digest=source_ref.action_digest,
            pre_call_session_id=checkpoint.session_id,
            pre_call_turn_id=f"turn-{int(time.time() * 1000)}",
            state=ModelContinuationState.INTENT_COMMITTED,
            created_at=datetime.now(timezone.utc),
        ),
    )
    try:
        intent_checkpoint = store.replace_checkpoint(intent_checkpoint, expected_revision=expected_revision)
    except CheckpointStaleRevision:
        stale = CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=source_ref.action_id,
        )
        return CodingWorkflowResumeResult(workflow_id, stale, checkpoint_revision=checkpoint.revision)
    except CheckpointLockUnavailable:
        locked = CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.BLOCKED_UNCERTAIN,
            CodingWorkflowBlockReason.CHECKPOINT_LOCK_UNAVAILABLE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=source_ref.action_id,
        )
        return CodingWorkflowResumeResult(workflow_id, locked, checkpoint_revision=checkpoint.revision)

    try:
        runtime.continue_(continuation_id=continuation_id, stop_after_model_boundary=True)
    except Exception:  # noqa: BLE001
        blocked = CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.BLOCKED_UNCERTAIN,
            CodingWorkflowBlockReason.CONTINUATION_RUNTIME_FAILED,
            checkpoint_revision=intent_checkpoint.revision,
            session_id=intent_checkpoint.session_id,
            action_id=intent_checkpoint.last_completed_action_ref.action_id if intent_checkpoint.last_completed_action_ref else None,
            continuation_id=continuation_id,
        )
        return CodingWorkflowResumeResult(
            workflow_id,
            blocked,
            external_effect_count=1,
            model_continuation_attempted=True,
            checkpoint_revision=intent_checkpoint.revision,
        )

    completion = session_store.lookup_model_continuation_completion_evidence(intent_checkpoint.session_id, continuation_id=continuation_id)
    if completion.status != SessionEvidenceLookupStatus.FOUND or completion.evidence is None:
        blocked = CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.BLOCKED_UNCERTAIN,
            CodingWorkflowBlockReason.CONTINUATION_MISSING,
            checkpoint_revision=intent_checkpoint.revision,
            session_id=intent_checkpoint.session_id,
            action_id=intent_checkpoint.last_completed_action_ref.action_id if intent_checkpoint.last_completed_action_ref else None,
            continuation_id=continuation_id,
        )
        return CodingWorkflowResumeResult(
            workflow_id,
            blocked,
            external_effect_count=1,
            model_continuation_attempted=True,
            checkpoint_revision=intent_checkpoint.revision,
        )

    active_pending_action_id = _active_pending_action_id_for_session(pending_store, intent_checkpoint.session_id)
    if active_pending_action_id is not None:
        blocked = CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.BLOCKED_UNCERTAIN,
            CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
            checkpoint_revision=intent_checkpoint.revision,
            session_id=intent_checkpoint.session_id,
            action_id=active_pending_action_id,
            continuation_id=continuation_id,
            completion_message_id=completion.evidence.message_id,
        )
        return CodingWorkflowResumeResult(
            workflow_id,
            blocked,
            external_effect_count=1,
            model_continuation_attempted=True,
            checkpoint_revision=intent_checkpoint.revision,
        )

    try:
        committed = _commit_completion(
            store=store,
            checkpoint=intent_checkpoint,
            completion_message_id=completion.evidence.message_id,
            expected_revision=intent_checkpoint.revision,
        )
    except CheckpointStaleRevision:
        blocked = CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.BLOCKED_UNCERTAIN,
            CodingWorkflowBlockReason.POST_CALL_CAS_FAILED,
            checkpoint_revision=intent_checkpoint.revision,
            session_id=intent_checkpoint.session_id,
            continuation_id=continuation_id,
            completion_message_id=completion.evidence.message_id,
        )
        return CodingWorkflowResumeResult(
            workflow_id,
            blocked,
            external_effect_count=1,
            model_continuation_attempted=True,
            checkpoint_revision=intent_checkpoint.revision,
        )
    next_inspection = _inspect_checkpoint(committed, session_store=session_store, pending_action_store=pending_store)
    return CodingWorkflowResumeResult(
        workflow_id,
        next_inspection,
        external_effect_count=1,
        model_continuation_attempted=True,
        checkpoint_revision=committed.revision,
    )


def _inspect_checkpoint(
    checkpoint: CodingWorkflowCheckpoint,
    *,
    session_store: SessionEvidenceStore,
    pending_action_store: PendingActionReader,
) -> CodingWorkflowInspection:
    base = {
        "workflow_id": checkpoint.workflow_id,
        "checkpoint_revision": checkpoint.revision,
        "session_id": checkpoint.session_id,
    }
    if checkpoint.schema_version != CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3:
        return CodingWorkflowInspection(
            **base,
            decision=CodingWorkflowDecision.LEGACY_CHECKPOINT_NOT_RESUMABLE,
            reason=CodingWorkflowBlockReason.LEGACY_NOT_RESUMABLE,
        )
    if checkpoint.phase == CodingWorkflowPhase.COMPLETED:
        if (
            checkpoint.schema_version == CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3
            and checkpoint.terminal_outcome is not None
            and checkpoint.terminal_outcome.terminal_kind == CodingWorkflowTerminalKind.ORDINARY_COMPLETION
        ):
            evidence = checkpoint.terminal_outcome.session_completion_evidence_ref
            return CodingWorkflowInspection(
                **base,
                decision=CodingWorkflowDecision.ORDINARY_COMPLETED,
                action_id=evidence.source_action_id if evidence else None,
                continuation_id=evidence.continuation_id if evidence else None,
                completion_message_id=evidence.committed_turn_id if evidence else None,
            )
        return CodingWorkflowInspection(**base, decision=CodingWorkflowDecision.COMPLETED)
    if checkpoint.phase in _MISSION_07_PHASES or checkpoint.validation_execution_count > 0 or checkpoint.repair_attempted or checkpoint.revalidation_attempted:
        return _inspect_mission_07_checkpoint(checkpoint, session_store=session_store, pending_action_store=pending_action_store)
    if checkpoint.pending_action_ref is not None or checkpoint.phase in _AWAITING_PHASES:
        return _inspect_pending_action(checkpoint, pending_action_store=pending_action_store, session_store=session_store)
    intent = checkpoint.model_continuation_intent
    if intent is not None:
        completion = session_store.lookup_model_continuation_completion_evidence(checkpoint.session_id, continuation_id=intent.continuation_id)
        if intent.state == ModelContinuationState.SESSION_COMMITTED:
            if checkpoint.schema_version == CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3:
                return CodingWorkflowInspection(
                    **base,
                    decision=CodingWorkflowDecision.CONTINUATION_COMPLETED_IN_SESSION,
                    action_id=intent.source_action_ref.action_id,
                    continuation_id=intent.continuation_id,
                    completion_message_id=(
                        intent.completed_session_evidence_ref.committed_turn_id if intent.completed_session_evidence_ref else None
                    ),
                )
            return CodingWorkflowInspection(
                **base,
                decision=CodingWorkflowDecision.LEGACY_CHECKPOINT_NOT_RESUMABLE,
                reason=CodingWorkflowBlockReason.LEGACY_NOT_RESUMABLE,
                action_id=intent.source_action_ref.action_id,
                continuation_id=intent.continuation_id,
                completion_message_id=(
                    intent.completed_session_evidence_ref.committed_turn_id if intent.completed_session_evidence_ref else None
                ),
            )
        if completion.status == SessionEvidenceLookupStatus.FOUND and completion.evidence is not None:
            return CodingWorkflowInspection(
                **base,
                decision=CodingWorkflowDecision.CONTINUATION_COMPLETED_IN_SESSION,
                action_id=intent.source_action_ref.action_id,
                continuation_id=intent.continuation_id,
                completion_message_id=completion.evidence.message_id,
            )
        if completion.status == SessionEvidenceLookupStatus.AMBIGUOUS:
            return CodingWorkflowInspection(
                **base,
                decision=CodingWorkflowDecision.BLOCKED_UNCERTAIN,
                reason=CodingWorkflowBlockReason.CONTINUATION_AMBIGUOUS,
                action_id=intent.source_action_ref.action_id,
                continuation_id=intent.continuation_id,
            )
        return CodingWorkflowInspection(
            **base,
            decision=CodingWorkflowDecision.CONTINUATION_INTENT_COMMITTED,
            reason=CodingWorkflowBlockReason.CONTINUATION_MISSING,
            action_id=intent.source_action_ref.action_id,
            continuation_id=intent.continuation_id,
        )
    if checkpoint.last_completed_action_ref is None:
        return CodingWorkflowInspection(**base, decision=CodingWorkflowDecision.BLOCKED_UNCERTAIN, reason=CodingWorkflowBlockReason.ACTION_MISSING)
    return _inspect_completed_action(checkpoint, pending_action_store=pending_action_store, session_store=session_store)


def _inspect_mission_07_checkpoint(
    checkpoint: CodingWorkflowCheckpoint,
    *,
    session_store: SessionEvidenceStore,
    pending_action_store: PendingActionReader,
) -> CodingWorkflowInspection:
    base = {
        "workflow_id": checkpoint.workflow_id,
        "checkpoint_revision": checkpoint.revision,
        "session_id": checkpoint.session_id,
    }
    if checkpoint.selected_validation_command_digest is None:
        return CodingWorkflowInspection(
            **base,
            decision=CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            reason=CodingWorkflowBlockReason.VALIDATION_COMMAND_MISMATCH,
        )
    if checkpoint.phase == CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL:
        return _inspect_role_pending_action(
            checkpoint,
            expected_role=PendingActionRole.VALIDATION,
            awaiting_decision=CodingWorkflowDecision.AWAITING_VALIDATION_APPROVAL,
            ready_decision=CodingWorkflowDecision.VALIDATION_RESULT_READY,
            missing_decision=CodingWorkflowDecision.VALIDATION_RESULT_MISSING,
            pending_action_store=pending_action_store,
            session_store=session_store,
        )
    if checkpoint.phase == CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL:
        return _inspect_role_pending_action(
            checkpoint,
            expected_role=PendingActionRole.REVALIDATION,
            awaiting_decision=CodingWorkflowDecision.AWAITING_REVALIDATION_APPROVAL,
            ready_decision=CodingWorkflowDecision.REVALIDATION_RESULT_READY,
            missing_decision=CodingWorkflowDecision.VALIDATION_RESULT_MISSING,
            pending_action_store=pending_action_store,
            session_store=session_store,
        )
    if checkpoint.phase == CodingWorkflowPhase.AWAITING_REPAIR_TOOL_APPROVAL:
        return _inspect_role_pending_action(
            checkpoint,
            expected_role=PendingActionRole.REPAIR_TOOL,
            awaiting_decision=CodingWorkflowDecision.AWAITING_REPAIR_TOOL_APPROVAL,
            ready_decision=CodingWorkflowDecision.REPAIR_COMPLETED_READY_FOR_REVALIDATION,
            missing_decision=CodingWorkflowDecision.DURABLE_RESULT_UNAVAILABLE,
            pending_action_store=pending_action_store,
            session_store=session_store,
        )
    if checkpoint.phase == CodingWorkflowPhase.VALIDATION_COMPLETED:
        ref = checkpoint.last_completed_action_ref
        if ref is None:
            return CodingWorkflowInspection(
                **base,
                decision=CodingWorkflowDecision.CORRUPT_INCONSISTENT,
                reason=CodingWorkflowBlockReason.ACTION_MISSING,
            )
        active_conflict = _active_pending_action_id_for_session(pending_action_store, checkpoint.session_id)
        if active_conflict is not None:
            return CodingWorkflowInspection(
                **base,
                decision=CodingWorkflowDecision.CORRUPT_INCONSISTENT,
                reason=CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
                action_id=active_conflict,
            )
        trusted_failure = _trusted_tests_failed_validation_evidence(checkpoint, ref, session_store)
        if trusted_failure is True and not checkpoint.repair_attempted:
            return CodingWorkflowInspection(
                **base,
                decision=CodingWorkflowDecision.SAFE_TO_START_REPAIR,
                action_id=ref.action_id,
                action_state="grant_consumed",
            )
        if trusted_failure is False and not checkpoint.repair_attempted:
            return CodingWorkflowInspection(
                **base,
                decision=CodingWorkflowDecision.CORRUPT_INCONSISTENT,
                reason=CodingWorkflowBlockReason.VALIDATION_EVIDENCE_MISSING,
                action_id=ref.action_id,
            )
        return _inspect_role_action_ref(
            checkpoint,
            ref,
            expected_role=PendingActionRole.VALIDATION,
            active_decision=CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            consumed_decision=CodingWorkflowDecision.VALIDATION_RESULT_READY,
            missing_decision=CodingWorkflowDecision.VALIDATION_RESULT_MISSING,
            pending_action_store=pending_action_store,
            session_store=session_store,
        )
    if checkpoint.phase == CodingWorkflowPhase.REVALIDATION_COMPLETED:
        ref = checkpoint.last_completed_action_ref
        if ref is None:
            return CodingWorkflowInspection(
                **base,
                decision=CodingWorkflowDecision.CORRUPT_INCONSISTENT,
                reason=CodingWorkflowBlockReason.ACTION_MISSING,
            )
        active_conflict = _active_pending_action_id_for_session(pending_action_store, checkpoint.session_id)
        if active_conflict is not None:
            return CodingWorkflowInspection(
                **base,
                decision=CodingWorkflowDecision.CORRUPT_INCONSISTENT,
                reason=CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
                action_id=active_conflict,
            )
        return _inspect_role_action_ref(
            checkpoint,
            ref,
            expected_role=PendingActionRole.REVALIDATION,
            active_decision=CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            consumed_decision=CodingWorkflowDecision.REVALIDATION_RESULT_READY,
            missing_decision=CodingWorkflowDecision.VALIDATION_RESULT_MISSING,
            pending_action_store=pending_action_store,
            session_store=session_store,
        )
    if checkpoint.phase == CodingWorkflowPhase.REPAIR_STARTED:
        intent = checkpoint.model_continuation_intent
        if intent is None:
            return CodingWorkflowInspection(
                **base,
                decision=CodingWorkflowDecision.REPAIR_CONTINUATION_UNCERTAIN,
                reason=CodingWorkflowBlockReason.CONTINUATION_MISSING,
            )
        return _inspect_repair_continuation_intent(checkpoint, session_store=session_store)
    if checkpoint.phase == CodingWorkflowPhase.REPAIR_COMPLETED:
        if checkpoint.revalidation_attempted:
            return CodingWorkflowInspection(
                **base,
                decision=CodingWorkflowDecision.CORRUPT_INCONSISTENT,
                reason=CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
            )
        return CodingWorkflowInspection(**base, decision=CodingWorkflowDecision.REPAIR_COMPLETED_READY_FOR_REVALIDATION)
    if checkpoint.phase == CodingWorkflowPhase.FINALIZED:
        if checkpoint.final_outcome_summary is None:
            return CodingWorkflowInspection(
                **base,
                decision=CodingWorkflowDecision.CORRUPT_INCONSISTENT,
                reason=CodingWorkflowBlockReason.CHECKPOINT_CORRUPT,
            )
        return CodingWorkflowInspection(**base, decision=CodingWorkflowDecision.FINAL_VALIDATION_COMPLETION_READY)
    return CodingWorkflowInspection(
        **base,
        decision=CodingWorkflowDecision.CORRUPT_INCONSISTENT,
        reason=CodingWorkflowBlockReason.CHECKPOINT_CORRUPT,
    )


def _inspect_pending_action(
    checkpoint: CodingWorkflowCheckpoint,
    *,
    pending_action_store: PendingActionReader,
    session_store: SessionEvidenceStore,
) -> CodingWorkflowInspection:
    ref = checkpoint.pending_action_ref
    if ref is None:
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    action = _load_action(pending_action_store, ref.action_id)
    if action is None:
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    if not _action_matches_ref(action, ref, checkpoint.session_id):
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_IDENTITY_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    state = _pending_action_state(action)
    if state in _ACTIVE_ACTION_STATES:
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.AWAITING_APPROVAL,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state=state,
        )
    if state == "execution_in_progress" or state == "execution_succeeded":
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.EXECUTION_UNCERTAIN,
            CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state=state,
        )
    if state in _FAILED_ACTION_STATES:
        decision = {
            "execution_failed": CodingWorkflowDecision.EXECUTION_FAILED,
            "rejected": CodingWorkflowDecision.REJECTED,
            "denied": CodingWorkflowDecision.REJECTED,
            "expired": CodingWorkflowDecision.EXPIRED,
            "grant_invalidated": CodingWorkflowDecision.INVALIDATED,
        }.get(state, CodingWorkflowDecision.CORRUPT_INCONSISTENT)
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            decision,
            CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state=state,
        )
    if state == "grant_consumed":
        return _result_evidence_decision(checkpoint, ref, session_store, action_state=state)
    return CodingWorkflowInspection(
        checkpoint.workflow_id,
        CodingWorkflowDecision.CORRUPT_INCONSISTENT,
        CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
        checkpoint_revision=checkpoint.revision,
        session_id=checkpoint.session_id,
        action_id=ref.action_id,
        action_state=state,
    )


def _inspect_role_pending_action(
    checkpoint: CodingWorkflowCheckpoint,
    *,
    expected_role: PendingActionRole,
    awaiting_decision: CodingWorkflowDecision,
    ready_decision: CodingWorkflowDecision,
    missing_decision: CodingWorkflowDecision,
    pending_action_store: PendingActionReader,
    session_store: SessionEvidenceStore,
) -> CodingWorkflowInspection:
    ref = checkpoint.pending_action_ref
    if ref is None:
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    return _inspect_role_action_ref(
        checkpoint,
        ref,
        expected_role=expected_role,
        active_decision=awaiting_decision,
        consumed_decision=ready_decision,
        missing_decision=missing_decision,
        pending_action_store=pending_action_store,
        session_store=session_store,
    )


def _inspect_role_action_ref(
    checkpoint: CodingWorkflowCheckpoint,
    ref: PendingActionReference,
    *,
    expected_role: PendingActionRole,
    active_decision: CodingWorkflowDecision,
    consumed_decision: CodingWorkflowDecision,
    missing_decision: CodingWorkflowDecision,
    pending_action_store: PendingActionReader,
    session_store: SessionEvidenceStore,
) -> CodingWorkflowInspection:
    if ref.role != expected_role:
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_IDENTITY_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    action = _load_action(pending_action_store, ref.action_id)
    if action is None:
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    if not _action_matches_ref(action, ref, checkpoint.session_id):
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_IDENTITY_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    requires_command_match = expected_role in {PendingActionRole.VALIDATION, PendingActionRole.REVALIDATION}
    if requires_command_match and not _action_matches_selected_validation_digest(action, checkpoint):
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.VALIDATION_COMMAND_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    state = _pending_action_state(action)
    if state in _ACTIVE_ACTION_STATES:
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            active_decision,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state=state,
        )
    if state == "execution_in_progress" or state == "execution_succeeded":
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.EXECUTION_UNCERTAIN,
            CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state=state,
        )
    if state in _FAILED_ACTION_STATES:
        decision = {
            "execution_failed": CodingWorkflowDecision.EXECUTION_FAILED,
            "rejected": CodingWorkflowDecision.REJECTED,
            "denied": CodingWorkflowDecision.REJECTED,
            "expired": CodingWorkflowDecision.EXPIRED,
            "grant_invalidated": CodingWorkflowDecision.INVALIDATED,
        }.get(state, CodingWorkflowDecision.CORRUPT_INCONSISTENT)
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            decision,
            CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state=state,
        )
    if state != "grant_consumed":
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state=state,
        )
    return _validation_result_evidence_decision(
        checkpoint,
        ref,
        session_store,
        action_state=state,
        ready_decision=consumed_decision,
        missing_decision=missing_decision,
    )


def _inspect_repair_continuation_intent(
    checkpoint: CodingWorkflowCheckpoint,
    *,
    session_store: SessionEvidenceStore,
) -> CodingWorkflowInspection:
    intent = checkpoint.model_continuation_intent
    assert intent is not None
    completion = session_store.lookup_model_continuation_completion_evidence(checkpoint.session_id, continuation_id=intent.continuation_id)
    if completion.status == SessionEvidenceLookupStatus.FOUND and completion.evidence is not None:
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.REPAIR_COMPLETED_READY_FOR_REVALIDATION,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=intent.source_action_ref.action_id,
            continuation_id=intent.continuation_id,
            completion_message_id=completion.evidence.message_id,
        )
    reason = (
        CodingWorkflowBlockReason.CONTINUATION_AMBIGUOUS
        if completion.status == SessionEvidenceLookupStatus.AMBIGUOUS
        else CodingWorkflowBlockReason.CONTINUATION_MISSING
    )
    return CodingWorkflowInspection(
        checkpoint.workflow_id,
        CodingWorkflowDecision.REPAIR_CONTINUATION_UNCERTAIN,
        reason,
        checkpoint_revision=checkpoint.revision,
        session_id=checkpoint.session_id,
        action_id=intent.source_action_ref.action_id,
        continuation_id=intent.continuation_id,
    )


def _validation_result_evidence_decision(
    checkpoint: CodingWorkflowCheckpoint,
    ref: PendingActionReference,
    session_store: SessionEvidenceStore,
    *,
    action_state: str,
    ready_decision: CodingWorkflowDecision,
    missing_decision: CodingWorkflowDecision,
) -> CodingWorkflowInspection:
    result = session_store.lookup_external_tool_result_evidence(
        checkpoint.session_id,
        action_id=ref.action_id,
    )
    if result.status == SessionEvidenceLookupStatus.FOUND and result.evidence is not None:
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            ready_decision,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state=action_state,
            result_message_id=result.evidence.message_id,
        )
    if result.status == SessionEvidenceLookupStatus.IDENTITY_MISMATCH:
        reason = CodingWorkflowBlockReason.RESULT_MISMATCH
    elif result.status == SessionEvidenceLookupStatus.AMBIGUOUS:
        reason = CodingWorkflowBlockReason.RESULT_AMBIGUOUS
    else:
        reason = CodingWorkflowBlockReason.RESULT_MISSING
    return CodingWorkflowInspection(
        checkpoint.workflow_id,
        missing_decision,
        reason,
        checkpoint_revision=checkpoint.revision,
        session_id=checkpoint.session_id,
        action_id=ref.action_id,
        action_state=action_state,
    )


def _inspect_completed_action(
    checkpoint: CodingWorkflowCheckpoint,
    *,
    pending_action_store: PendingActionReader,
    session_store: SessionEvidenceStore,
) -> CodingWorkflowInspection:
    ref = checkpoint.last_completed_action_ref
    assert ref is not None
    action = _load_action(pending_action_store, ref.action_id)
    if action is None:
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    if not _action_matches_ref(action, ref, checkpoint.session_id):
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_IDENTITY_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    state = _pending_action_state(action)
    if state != "grant_consumed":
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.BLOCKED_UNCERTAIN,
            CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state=state,
        )
    return _result_evidence_decision(checkpoint, ref, session_store, action_state=state)


def _result_evidence_decision(
    checkpoint: CodingWorkflowCheckpoint,
    ref: PendingActionReference,
    session_store: SessionEvidenceStore,
    *,
    action_state: str,
) -> CodingWorkflowInspection:
    if ref.action_digest is None:
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.DURABLE_RESULT_UNAVAILABLE,
            CodingWorkflowBlockReason.RESULT_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state=action_state,
        )
    result = session_store.lookup_external_tool_result_evidence(
        checkpoint.session_id,
        action_id=ref.action_id,
        result_digest=_session_result_digest(ref.action_digest),
    )
    if result.status == SessionEvidenceLookupStatus.FOUND and result.evidence is not None:
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.READY_FOR_CONTINUATION_INTENT,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state=action_state,
            result_message_id=result.evidence.message_id,
        )
    reason = CodingWorkflowBlockReason.RESULT_AMBIGUOUS if result.status == SessionEvidenceLookupStatus.AMBIGUOUS else CodingWorkflowBlockReason.RESULT_MISSING
    return CodingWorkflowInspection(
        checkpoint.workflow_id,
        CodingWorkflowDecision.DURABLE_RESULT_UNAVAILABLE,
        reason,
        checkpoint_revision=checkpoint.revision,
        session_id=checkpoint.session_id,
        action_id=ref.action_id,
        action_state=action_state,
    )


def _load_action(pending_action_store: PendingActionReader, action_id: str) -> dict[str, Any] | None:
    try:
        return pending_action_store.load(action_id)
    except (FileNotFoundError, ValueError, TypeError):
        return None


def _action_matches_ref(action: dict[str, Any], ref: PendingActionReference, session_id: str) -> bool:
    if str(action.get("token") or "") != ref.action_id:
        return False
    action_session_id = str(action.get("session_id") or (action.get("details") or {}).get("session_id") or "")
    if action_session_id and action_session_id != session_id:
        return False
    if ref.action_type is not None and str(action.get("action_type") or "") != ref.action_type:
        return False
    if ref.action_digest is not None:
        digest = str(action.get("canonical_key") or (action.get("effect") or {}).get("payload_digest") or "")
        if digest and digest != ref.action_digest:
            return False
    return True


def _action_matches_selected_validation_digest(action: dict[str, Any], checkpoint: CodingWorkflowCheckpoint) -> bool:
    expected = checkpoint.selected_validation_command_digest
    if expected is None:
        return True
    observed = _action_logical_command_digest(action)
    return observed == expected


def _action_logical_command_digest(action: dict[str, Any]) -> str | None:
    details = action.get("details") or {}
    candidates = [
        details.get("logical_command_digest") if isinstance(details, dict) else None,
        ((details.get("command_proposal") or {}).get("logical_command_digest") if isinstance(details, dict) else None),
        ((details.get("validation") or {}).get("logical_command_digest") if isinstance(details, dict) else None),
        ((details.get("pytest_provenance_request") or {}).get("logical_command_digest") if isinstance(details, dict) else None),
    ]
    for value in candidates:
        if isinstance(value, str) and value:
            return value
    return None


def _session_result_digest(checkpoint_digest: str) -> str:
    return checkpoint_digest if checkpoint_digest.startswith("sha256:") else f"sha256:{checkpoint_digest}"


def _default_pending_action_store(workspace: Path) -> PendingActionReader:
    approvals = importlib.import_module("pp_agent.storage.approvals")
    return approvals.PendingActionStore(workspace / ".pp-agent" / "pending-edits")


def _pending_action_state(item: dict[str, Any]) -> str:
    expires_at = item.get("expires_at")
    if isinstance(expires_at, (int, float)) and expires_at > 0 and time.time() > float(expires_at):
        return "expired"
    lifecycle = item.get("lifecycle") or {}
    state = str(lifecycle.get("state") or "").strip()
    if not state or state in _ACTIVE_ACTION_STATES:
        return "active"
    return state


def _active_pending_action_id_for_session(pending_action_store: PendingActionReader, session_id: str) -> str | None:
    action = _active_pending_action_for_session(pending_action_store, session_id)
    return str(action.get("token") or "") if action is not None else None


def _active_pending_action_for_session(pending_action_store: PendingActionReader, session_id: str) -> dict[str, Any] | None:
    try:
        actions = pending_action_store.list()
    except (FileNotFoundError, ValueError, TypeError):
        return None
    for action in actions:
        if _action_session_id(action) != session_id:
            continue
        if _pending_action_state(action) in _ACTIVE_ACTION_STATES:
            return action
    return None


def _action_session_id(action: dict[str, Any]) -> str:
    return str(action.get("session_id") or (action.get("details") or {}).get("session_id") or "")


def _pending_action_ref_from_action(action: dict[str, Any], *, role: PendingActionRole) -> PendingActionReference | None:
    action_id = str(action.get("token") or "").strip()
    action_type = str(action.get("action_type") or "").strip()
    if not action_id or not action_type:
        return None
    digest = str(action.get("canonical_key") or (action.get("effect") or {}).get("payload_digest") or "").strip() or None
    return PendingActionReference(
        action_id=action_id,
        role=role,
        action_digest=digest,
        action_type=action_type,
    )


def _pending_revalidation_reference_from_action(
    action: dict[str, Any] | None,
    checkpoint: CodingWorkflowCheckpoint,
) -> PendingActionReference | None:
    if action is None:
        return None
    if str(action.get("action_type") or "") != "run_shell":
        return None
    if not _action_matches_selected_validation_digest(action, checkpoint):
        return None
    action_id = str(action.get("token") or "").strip()
    digest = str(action.get("canonical_key") or (action.get("effect") or {}).get("payload_digest") or "").strip()
    if not action_id or not digest:
        return None
    return PendingActionReference(
        action_id=action_id,
        role=PendingActionRole.REVALIDATION,
        action_digest=digest,
        action_type="run_shell",
    )


def _trusted_tests_failed_validation_evidence(
    checkpoint: CodingWorkflowCheckpoint,
    ref: PendingActionReference,
    session_store: SessionEvidenceStore,
) -> bool | None:
    expected = checkpoint.selected_validation_command_digest
    if expected is None:
        return False
    evidence_ref = _external_result_evidence_reference(checkpoint, ref, session_store)
    if evidence_ref is None:
        return None
    result = session_store.lookup_validation_evidence(
        checkpoint.session_id,
        action_id=ref.action_id,
        external_result_digest=evidence_ref.result_digest,
        logical_command_digest=expected,
    )
    if result.status != SessionEvidenceLookupStatus.FOUND or result.evidence is None:
        return False
    evidence = result.evidence
    return (
        evidence.execution_status == "executed"
        and evidence.validation_status == "failed"
        and evidence.pytest_provenance_status == "valid"
        and evidence.pytest_completion_category == "tests_failed"
    )


def _run_repair_model_continuation(runtime: RuntimeContinuation, prompt: str, *, continuation_id: str) -> list[Any]:
    state = getattr(runtime, "state", None)
    messages = getattr(state, "messages", None)
    if isinstance(messages, list):
        message = ChatMessage(role="user", content=[TextPart(text=prompt)], timestamp=time.time())
        ensure_session_message_id(message)
        messages.append(message)
    return list(runtime.continue_(continuation_id=continuation_id, stop_after_model_boundary=True) or [])


def _repair_events_blocked(events: list[Any]) -> bool:
    for event in events:
        if bool(getattr(event, "is_error", False)):
            return True
        details = getattr(event, "details", None)
        if isinstance(event, dict):
            details = event.get("details")
        if _contains_blocking_detail(details):
            return True
    return False


def _contains_blocking_detail(value: Any) -> bool:
    if isinstance(value, dict):
        if any(bool(value.get(key)) for key in ("scope_blocked", "runtime_guardrail_blocked", "approval_unavailable")):
            return True
        return any(_contains_blocking_detail(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_blocking_detail(item) for item in value)
    return False


def _committed_repair_intent(
    checkpoint: CodingWorkflowCheckpoint,
    *,
    completion_message_id: str,
) -> ModelContinuationIntent:
    intent = checkpoint.model_continuation_intent
    if intent is None:
        raise CheckpointInvariantViolation("missing repair continuation intent")
    evidence = SessionCompletionEvidenceReference(
        session_id=checkpoint.session_id,
        continuation_id=intent.continuation_id,
        source_action_id=intent.source_action_ref.action_id,
        source_result_digest=intent.source_result_digest,
        committed_turn_id=completion_message_id,
    )
    return ModelContinuationIntent(
        continuation_id=intent.continuation_id,
        source_action_ref=intent.source_action_ref,
        source_result_digest=intent.source_result_digest,
        pre_call_session_id=intent.pre_call_session_id,
        pre_call_turn_id=intent.pre_call_turn_id,
        state=ModelContinuationState.SESSION_COMMITTED,
        created_at=intent.created_at,
        completed_session_evidence_ref=evidence,
    )


def _commit_repair_awaiting_tool_approval(
    *,
    store: CodingWorkflowCheckpointStore,
    checkpoint: CodingWorkflowCheckpoint,
    pending_action: dict[str, Any],
    completion_message_id: str,
    expected_revision: int,
) -> CodingWorkflowCheckpoint:
    ref = _pending_action_ref_from_action(pending_action, role=PendingActionRole.REPAIR_TOOL)
    if ref is None:
        raise CheckpointInvariantViolation("missing repair pending action reference")
    now = datetime.now(timezone.utc)
    replacement = _replace_checkpoint_fields(
        checkpoint,
        revision=checkpoint.revision + 1,
        phase=CodingWorkflowPhase.AWAITING_REPAIR_TOOL_APPROVAL,
        repair_attempted=True,
        validation_execution_count=1,
        pending_action_ref=ref,
        model_continuation_intent=None,
        updated_at=now,
    )
    return store.replace_checkpoint(replacement, expected_revision=expected_revision)


def _commit_repair_completed(
    *,
    store: CodingWorkflowCheckpointStore,
    checkpoint: CodingWorkflowCheckpoint,
    completion_message_id: str,
    expected_revision: int,
) -> CodingWorkflowCheckpoint:
    now = datetime.now(timezone.utc)
    replacement = _replace_checkpoint_fields(
        checkpoint,
        revision=checkpoint.revision + 1,
        phase=CodingWorkflowPhase.REPAIR_COMPLETED,
        repair_attempted=True,
        validation_execution_count=1,
        pending_action_ref=None,
        model_continuation_intent=_committed_repair_intent(checkpoint, completion_message_id=completion_message_id),
        updated_at=now,
    )
    return store.replace_checkpoint(replacement, expected_revision=expected_revision)


def _commit_repair_blocked(
    *,
    store: CodingWorkflowCheckpointStore,
    checkpoint: CodingWorkflowCheckpoint,
    completion_message_id: str,
    expected_revision: int,
) -> CodingWorkflowCheckpoint:
    completed_at = datetime.now(timezone.utc)
    summary = ValidationOutcomeSummary(
        final_status=ValidationFinalStatus.BLOCKED,
        repair_attempted=True,
        revalidation_attempted=False,
        failure_reason_code="repair_continuation_blocked",
    )
    replacement = _replace_checkpoint_fields(
        checkpoint,
        revision=checkpoint.revision + 1,
        phase=CodingWorkflowPhase.COMPLETED,
        repair_attempted=True,
        validation_execution_count=1,
        pending_action_ref=None,
        final_outcome_summary=summary,
        completion_marker=CodingWorkflowCompletion(completed_at=completed_at),
        model_continuation_intent=_committed_repair_intent(checkpoint, completion_message_id=completion_message_id),
        terminal_outcome=CodingWorkflowTerminalOutcome(
            terminal_kind=CodingWorkflowTerminalKind.VALIDATION_COMPLETION,
            completed_at=completed_at,
            reason_code="repair_continuation_blocked",
            validation_outcome_summary=summary,
        ),
        updated_at=completed_at,
    )
    return store.replace_checkpoint(replacement, expected_revision=expected_revision)


def _commit_completion(
    *,
    store: CodingWorkflowCheckpointStore,
    checkpoint: CodingWorkflowCheckpoint,
    completion_message_id: str,
    expected_revision: int,
) -> CodingWorkflowCheckpoint:
    intent = checkpoint.model_continuation_intent
    if intent is None:
        raise CheckpointInvariantViolation("missing continuation intent")
    evidence = SessionCompletionEvidenceReference(
        session_id=checkpoint.session_id,
        continuation_id=intent.continuation_id,
        source_action_id=intent.source_action_ref.action_id,
        source_result_digest=intent.source_result_digest,
        committed_turn_id=completion_message_id,
    )
    completed_at = datetime.now(timezone.utc)
    committed_intent = ModelContinuationIntent(
        continuation_id=intent.continuation_id,
        source_action_ref=intent.source_action_ref,
        source_result_digest=intent.source_result_digest,
        pre_call_session_id=intent.pre_call_session_id,
        pre_call_turn_id=intent.pre_call_turn_id,
        state=ModelContinuationState.SESSION_COMMITTED,
        created_at=intent.created_at,
        completed_session_evidence_ref=evidence,
    )
    replacement = _replace_checkpoint_fields(
        checkpoint,
        revision=checkpoint.revision + 1,
        phase=CodingWorkflowPhase.COMPLETED,
        pending_action_ref=None,
        final_outcome_summary=None,
        completion_marker=CodingWorkflowCompletion(completed_at=completed_at),
        model_continuation_intent=committed_intent,
        terminal_outcome=CodingWorkflowTerminalOutcome(
            terminal_kind=CodingWorkflowTerminalKind.ORDINARY_COMPLETION,
            completed_at=completed_at,
            reason_code="ordinary_model_stop",
            session_completion_evidence_ref=evidence,
        ),
        updated_at=completed_at,
    )
    return store.replace_checkpoint(replacement, expected_revision=expected_revision)


def _finalize_session_committed_completion(
    *,
    store: CodingWorkflowCheckpointStore,
    workflow_id: str,
    expected_revision: int,
    session_store: SessionEvidenceStore,
    pending_action_store: PendingActionReader,
) -> CodingWorkflowInspection:
    try:
        checkpoint = store.load_checkpoint(workflow_id)
    except CheckpointStorageError:
        return _blocked(workflow_id, CodingWorkflowBlockReason.CHECKPOINT_CORRUPT)
    if checkpoint.revision != expected_revision:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    if checkpoint.schema_version != CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.LEGACY_CHECKPOINT_NOT_RESUMABLE,
            CodingWorkflowBlockReason.LEGACY_NOT_RESUMABLE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    intent = checkpoint.model_continuation_intent
    if intent is None or intent.state != ModelContinuationState.SESSION_COMMITTED or intent.completed_session_evidence_ref is None:
        return _inspect_checkpoint(checkpoint, session_store=session_store, pending_action_store=pending_action_store)
    completion = session_store.lookup_model_continuation_completion_evidence(checkpoint.session_id, continuation_id=intent.continuation_id)
    if completion.status != SessionEvidenceLookupStatus.FOUND or completion.evidence is None:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.BLOCKED_UNCERTAIN,
            CodingWorkflowBlockReason.CONTINUATION_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=intent.source_action_ref.action_id,
            continuation_id=intent.continuation_id,
        )
    evidence = intent.completed_session_evidence_ref
    if completion.evidence.message_id != evidence.committed_turn_id:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.BLOCKED_UNCERTAIN,
            CodingWorkflowBlockReason.CONTINUATION_AMBIGUOUS,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=intent.source_action_ref.action_id,
            continuation_id=intent.continuation_id,
            completion_message_id=completion.evidence.message_id,
        )
    active_pending_action_id = _active_pending_action_id_for_session(pending_action_store, checkpoint.session_id)
    if active_pending_action_id is not None:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.BLOCKED_UNCERTAIN,
            CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=active_pending_action_id,
            continuation_id=intent.continuation_id,
            completion_message_id=completion.evidence.message_id,
        )
    try:
        completed = _write_ordinary_completion(
            store=store,
            checkpoint=checkpoint,
            evidence=evidence,
            expected_revision=expected_revision,
        )
    except CheckpointStaleRevision:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=intent.source_action_ref.action_id,
            continuation_id=intent.continuation_id,
        )
    return _inspect_checkpoint(completed, session_store=session_store, pending_action_store=pending_action_store)


def _write_ordinary_completion(
    *,
    store: CodingWorkflowCheckpointStore,
    checkpoint: CodingWorkflowCheckpoint,
    evidence: SessionCompletionEvidenceReference,
    expected_revision: int,
) -> CodingWorkflowCheckpoint:
    completed_at = datetime.now(timezone.utc)
    replacement = _replace_checkpoint_fields(
        checkpoint,
        revision=checkpoint.revision + 1,
        phase=CodingWorkflowPhase.COMPLETED,
        pending_action_ref=None,
        final_outcome_summary=None,
        completion_marker=CodingWorkflowCompletion(completed_at=completed_at),
        terminal_outcome=CodingWorkflowTerminalOutcome(
            terminal_kind=CodingWorkflowTerminalKind.ORDINARY_COMPLETION,
            completed_at=completed_at,
            reason_code="ordinary_model_stop",
            session_completion_evidence_ref=evidence,
        ),
        updated_at=completed_at,
    )
    return store.replace_checkpoint(replacement, expected_revision=expected_revision)


def _resume_repair_continuation(
    *,
    store: CodingWorkflowCheckpointStore,
    workflow_id: str,
    expected_revision: int,
    runtime: RuntimeContinuation,
    session_store: SessionEvidenceStore,
    pending_action_store: PendingActionReader,
    workspace: Path,
) -> CodingWorkflowInspection:
    try:
        checkpoint = store.load_checkpoint(workflow_id)
    except CheckpointStorageError:
        return _blocked(workflow_id, CodingWorkflowBlockReason.CHECKPOINT_CORRUPT)
    if checkpoint.revision != expected_revision:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    refreshed = _inspect_checkpoint(checkpoint, session_store=session_store, pending_action_store=pending_action_store)
    if refreshed.decision != CodingWorkflowDecision.SAFE_TO_START_REPAIR:
        return refreshed
    ref = checkpoint.last_completed_action_ref
    if ref is None:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    action = _load_action(pending_action_store, ref.action_id)
    if action is None or not _action_matches_ref(action, ref, checkpoint.session_id):
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_IDENTITY_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    selection = _reconstruct_validation_selection(action, checkpoint)
    evidence_reference = _external_result_evidence_reference(checkpoint, ref, session_store)
    if selection is None or evidence_reference is None:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.VALIDATION_EVIDENCE_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    cycle = interpret_persisted_validation_result(
        selection=selection,
        evidence_reference=evidence_reference,
        session_store=session_store,  # type: ignore[arg-type]
        workspace=workspace,
    )
    if not _is_trusted_tests_failed_cycle(cycle) or cycle.observation is None:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.VALIDATION_EVIDENCE_BLOCKED,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )

    continuation_id = f"repair-cont-{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    intent_checkpoint = _replace_checkpoint_fields(
        checkpoint,
        revision=checkpoint.revision + 1,
        phase=CodingWorkflowPhase.REPAIR_STARTED,
        repair_attempted=True,
        validation_execution_count=1,
        pending_action_ref=None,
        last_completed_action_ref=ref,
        model_continuation_intent=ModelContinuationIntent(
            continuation_id=continuation_id,
            source_action_ref=ref,
            source_result_digest=evidence_reference.result_digest.removeprefix("sha256:"),
            pre_call_session_id=checkpoint.session_id,
            pre_call_turn_id=f"turn-{int(time.time() * 1000)}",
            state=ModelContinuationState.INTENT_COMMITTED,
            created_at=now,
        ),
        updated_at=now,
    )
    try:
        intent_checkpoint = store.replace_checkpoint(intent_checkpoint, expected_revision=expected_revision)
    except CheckpointStaleRevision:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    except CheckpointLockUnavailable:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.BLOCKED_UNCERTAIN,
            CodingWorkflowBlockReason.CHECKPOINT_LOCK_UNAVAILABLE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )

    prompt = build_validation_repair_prompt(
        task="Resume durable controlled coding workflow repair.",
        selection=selection,
        observation=cycle.observation,
    )
    try:
        repair_events = _run_repair_model_continuation(runtime, prompt, continuation_id=continuation_id)
    except Exception:  # noqa: BLE001
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.REPAIR_CONTINUATION_UNCERTAIN,
            CodingWorkflowBlockReason.CONTINUATION_RUNTIME_FAILED,
            checkpoint_revision=intent_checkpoint.revision,
            session_id=intent_checkpoint.session_id,
            action_id=ref.action_id,
            continuation_id=continuation_id,
        )
    return _reconcile_repair_continuation_completion(
        store=store,
        workflow_id=workflow_id,
        expected_revision=intent_checkpoint.revision,
        session_store=session_store,
        pending_action_store=pending_action_store,
        repair_blocked=_repair_events_blocked(repair_events),
    )


def _reconcile_repair_continuation_completion(
    *,
    store: CodingWorkflowCheckpointStore,
    workflow_id: str,
    expected_revision: int,
    session_store: SessionEvidenceStore,
    pending_action_store: PendingActionReader,
    repair_blocked: bool = False,
) -> CodingWorkflowInspection:
    try:
        checkpoint = store.load_checkpoint(workflow_id)
    except CheckpointStorageError:
        return _blocked(workflow_id, CodingWorkflowBlockReason.CHECKPOINT_CORRUPT)
    if checkpoint.revision != expected_revision:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    if checkpoint.phase != CodingWorkflowPhase.REPAIR_STARTED or checkpoint.model_continuation_intent is None:
        return _inspect_checkpoint(checkpoint, session_store=session_store, pending_action_store=pending_action_store)
    intent = checkpoint.model_continuation_intent
    completion = session_store.lookup_model_continuation_completion_evidence(checkpoint.session_id, continuation_id=intent.continuation_id)
    if completion.status != SessionEvidenceLookupStatus.FOUND or completion.evidence is None:
        reason = (
            CodingWorkflowBlockReason.CONTINUATION_AMBIGUOUS
            if completion.status == SessionEvidenceLookupStatus.AMBIGUOUS
            else CodingWorkflowBlockReason.CONTINUATION_MISSING
        )
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.REPAIR_CONTINUATION_UNCERTAIN,
            reason,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=intent.source_action_ref.action_id,
            continuation_id=intent.continuation_id,
        )
    pending_action = _active_pending_action_for_session(pending_action_store, checkpoint.session_id)
    try:
        if pending_action is not None:
            committed = _commit_repair_awaiting_tool_approval(
                store=store,
                checkpoint=checkpoint,
                pending_action=pending_action,
                completion_message_id=completion.evidence.message_id,
                expected_revision=expected_revision,
            )
        elif repair_blocked:
            committed = _commit_repair_blocked(
                store=store,
                checkpoint=checkpoint,
                completion_message_id=completion.evidence.message_id,
                expected_revision=expected_revision,
            )
        else:
            committed = _commit_repair_completed(
                store=store,
                checkpoint=checkpoint,
                completion_message_id=completion.evidence.message_id,
                expected_revision=expected_revision,
            )
    except CheckpointStaleRevision:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=intent.source_action_ref.action_id,
            continuation_id=intent.continuation_id,
        )
    return _inspect_checkpoint(committed, session_store=session_store, pending_action_store=pending_action_store)


def _resume_repair_completed_ready_for_revalidation(
    *,
    store: CodingWorkflowCheckpointStore,
    workflow_id: str,
    expected_revision: int,
    runtime: RuntimeContinuation,
    session_store: SessionEvidenceStore,
    pending_action_store: PendingActionReader,
    workspace: Path,
) -> CodingWorkflowInspection:
    try:
        checkpoint = store.load_checkpoint(workflow_id)
    except CheckpointStorageError:
        return _blocked(workflow_id, CodingWorkflowBlockReason.CHECKPOINT_CORRUPT)
    if checkpoint.revision != expected_revision:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    if checkpoint.phase == CodingWorkflowPhase.REPAIR_STARTED:
        return _reconcile_repair_continuation_completion(
            store=store,
            workflow_id=workflow_id,
            expected_revision=expected_revision,
            session_store=session_store,
            pending_action_store=pending_action_store,
        )
    if checkpoint.phase == CodingWorkflowPhase.AWAITING_REPAIR_TOOL_APPROVAL:
        return _resume_consumed_repair_tool_result(
            store=store,
            checkpoint=checkpoint,
            expected_revision=expected_revision,
            session_store=session_store,
            pending_action_store=pending_action_store,
        )
    if checkpoint.phase != CodingWorkflowPhase.REPAIR_COMPLETED:
        return _inspect_checkpoint(checkpoint, session_store=session_store, pending_action_store=pending_action_store)
    refreshed = _inspect_checkpoint(checkpoint, session_store=session_store, pending_action_store=pending_action_store)
    if refreshed.decision != CodingWorkflowDecision.REPAIR_COMPLETED_READY_FOR_REVALIDATION:
        return refreshed
    if checkpoint.revalidation_attempted or checkpoint.validation_execution_count != 1 or not checkpoint.repair_attempted:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    source_ref = checkpoint.last_completed_action_ref
    if source_ref is None:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    action = _load_action(pending_action_store, source_ref.action_id)
    if action is None or not _action_matches_ref(action, source_ref, checkpoint.session_id):
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_IDENTITY_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=source_ref.action_id,
        )
    selection = _reconstruct_validation_selection(action, checkpoint)
    if selection is None:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.VALIDATION_COMMAND_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=source_ref.action_id,
        )
    registry = getattr(runtime, "tool_registry", None)
    if registry is None:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.BLOCKED_UNCERTAIN,
            CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    staged = stage_selected_validation_cycle(
        selection,
        registry,
        reason="Run same validation command after one bounded repair attempt",
    )
    if staged.status != "approval_pending" or not staged.approval_token:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.BLOCKED_UNCERTAIN,
            CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=source_ref.action_id,
        )
    revalidation_action = _load_action(pending_action_store, staged.approval_token)
    revalidation_ref = _pending_revalidation_reference_from_action(revalidation_action, checkpoint)
    if revalidation_ref is None:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.VALIDATION_COMMAND_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=staged.approval_token,
        )
    now = datetime.now(timezone.utc)
    replacement = _replace_checkpoint_fields(
        checkpoint,
        revision=checkpoint.revision + 1,
        phase=CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL,
        validation_execution_count=1,
        repair_attempted=True,
        revalidation_attempted=True,
        pending_action_ref=revalidation_ref,
        last_completed_action_ref=source_ref,
        model_continuation_intent=None,
        updated_at=now,
    )
    try:
        committed = store.replace_checkpoint(replacement, expected_revision=expected_revision)
    except CheckpointStaleRevision:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=revalidation_ref.action_id,
        )
    except (CheckpointLockUnavailable, CheckpointStorageError):
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.BLOCKED_UNCERTAIN,
            CodingWorkflowBlockReason.ACTION_STATE_UNCERTAIN,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=revalidation_ref.action_id,
        )
    return _inspect_checkpoint(committed, session_store=session_store, pending_action_store=pending_action_store)


def _resume_consumed_repair_tool_result(
    *,
    store: CodingWorkflowCheckpointStore,
    checkpoint: CodingWorkflowCheckpoint,
    expected_revision: int,
    session_store: SessionEvidenceStore,
    pending_action_store: PendingActionReader,
) -> CodingWorkflowInspection:
    refreshed = _inspect_checkpoint(checkpoint, session_store=session_store, pending_action_store=pending_action_store)
    if refreshed.decision != CodingWorkflowDecision.REPAIR_COMPLETED_READY_FOR_REVALIDATION:
        return refreshed
    ref = checkpoint.pending_action_ref
    if ref is None or ref.role != PendingActionRole.REPAIR_TOOL:
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    action = _load_action(pending_action_store, ref.action_id)
    if action is None or not _action_matches_ref(action, ref, checkpoint.session_id):
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_IDENTITY_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    if _pending_action_state(action) != "grant_consumed":
        return refreshed
    now = datetime.now(timezone.utc)
    replacement = _replace_checkpoint_fields(
        checkpoint,
        revision=checkpoint.revision + 1,
        phase=CodingWorkflowPhase.REPAIR_COMPLETED,
        validation_execution_count=1,
        repair_attempted=True,
        revalidation_attempted=False,
        pending_action_ref=None,
        updated_at=now,
    )
    try:
        committed = store.replace_checkpoint(replacement, expected_revision=expected_revision)
    except CheckpointStaleRevision:
        return CodingWorkflowInspection(
            checkpoint.workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    return _inspect_checkpoint(committed, session_store=session_store, pending_action_store=pending_action_store)


def _resume_initial_validation_result(
    *,
    store: CodingWorkflowCheckpointStore,
    workflow_id: str,
    expected_revision: int,
    session_store: SessionEvidenceStore,
    pending_action_store: PendingActionReader,
    workspace: Path,
) -> CodingWorkflowInspection:
    try:
        checkpoint = store.load_checkpoint(workflow_id)
    except CheckpointStorageError:
        return _blocked(workflow_id, CodingWorkflowBlockReason.CHECKPOINT_CORRUPT)
    if checkpoint.revision != expected_revision:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    if checkpoint.schema_version != CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.LEGACY_CHECKPOINT_NOT_RESUMABLE,
            CodingWorkflowBlockReason.LEGACY_NOT_RESUMABLE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    if checkpoint.phase != CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL:
        return _inspect_checkpoint(checkpoint, session_store=session_store, pending_action_store=pending_action_store)

    refreshed = _inspect_checkpoint(checkpoint, session_store=session_store, pending_action_store=pending_action_store)
    if refreshed.decision != CodingWorkflowDecision.VALIDATION_RESULT_READY:
        return refreshed
    ref = checkpoint.pending_action_ref
    if ref is None or ref.role != PendingActionRole.VALIDATION or ref.action_digest is None:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id if ref else None,
        )
    action = _load_action(pending_action_store, ref.action_id)
    if action is None or not _action_matches_ref(action, ref, checkpoint.session_id):
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_IDENTITY_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    if _pending_action_state(action) != "grant_consumed":
        return _inspect_checkpoint(checkpoint, session_store=session_store, pending_action_store=pending_action_store)

    selection = _reconstruct_validation_selection(action, checkpoint)
    if selection is None:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.VALIDATION_COMMAND_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state="grant_consumed",
        )
    evidence_reference = _external_result_evidence_reference(checkpoint, ref, session_store)
    if evidence_reference is None:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.VALIDATION_RESULT_MISSING,
            CodingWorkflowBlockReason.RESULT_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state="grant_consumed",
        )
    if not _typed_validation_evidence_identity_matches(session_store, evidence_reference, checkpoint):
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.VALIDATION_COMMAND_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state="grant_consumed",
            result_message_id=evidence_reference.message_id,
        )

    cycle = interpret_persisted_validation_result(
        selection=selection,
        evidence_reference=evidence_reference,
        session_store=session_store,  # type: ignore[arg-type]
        workspace=workspace,
    )
    summary = _validation_summary_from_cycle(cycle)
    try:
        if _is_trusted_tests_failed_cycle(cycle):
            committed = _commit_initial_validation_ready_for_repair(
                store=store,
                checkpoint=checkpoint,
                ref=ref,
                expected_revision=expected_revision,
            )
            return CodingWorkflowInspection(
                workflow_id,
                CodingWorkflowDecision.SAFE_TO_START_REPAIR,
                checkpoint_revision=committed.revision,
                session_id=committed.session_id,
                action_id=ref.action_id,
                action_state="grant_consumed",
                result_message_id=evidence_reference.message_id,
            )
        committed = _commit_initial_validation_terminal(
            store=store,
            checkpoint=checkpoint,
            ref=ref,
            summary=summary,
            expected_revision=expected_revision,
        )
    except CheckpointStaleRevision:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    return _inspect_checkpoint(committed, session_store=session_store, pending_action_store=pending_action_store)


def _resume_revalidation_result(
    *,
    store: CodingWorkflowCheckpointStore,
    workflow_id: str,
    expected_revision: int,
    session_store: SessionEvidenceStore,
    pending_action_store: PendingActionReader,
    workspace: Path,
) -> CodingWorkflowInspection:
    try:
        checkpoint = store.load_checkpoint(workflow_id)
    except CheckpointStorageError:
        return _blocked(workflow_id, CodingWorkflowBlockReason.CHECKPOINT_CORRUPT)
    if checkpoint.revision != expected_revision:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    if checkpoint.schema_version != CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.LEGACY_CHECKPOINT_NOT_RESUMABLE,
            CodingWorkflowBlockReason.LEGACY_NOT_RESUMABLE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    if checkpoint.phase != CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL:
        return _inspect_checkpoint(checkpoint, session_store=session_store, pending_action_store=pending_action_store)
    refreshed = _inspect_checkpoint(checkpoint, session_store=session_store, pending_action_store=pending_action_store)
    if refreshed.decision != CodingWorkflowDecision.REVALIDATION_RESULT_READY:
        return refreshed
    ref = checkpoint.pending_action_ref
    if ref is None or ref.role != PendingActionRole.REVALIDATION:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
        )
    action = _load_action(pending_action_store, ref.action_id)
    if action is None or not _action_matches_ref(action, ref, checkpoint.session_id):
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.ACTION_IDENTITY_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    if _pending_action_state(action) != "grant_consumed":
        return refreshed
    selection = _reconstruct_validation_selection(action, checkpoint)
    if selection is None:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.VALIDATION_COMMAND_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state="grant_consumed",
        )
    evidence_reference = _external_result_evidence_reference(checkpoint, ref, session_store)
    if evidence_reference is None:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.VALIDATION_RESULT_MISSING,
            CodingWorkflowBlockReason.RESULT_MISSING,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state="grant_consumed",
        )
    if not _typed_validation_evidence_identity_matches(session_store, evidence_reference, checkpoint):
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.CORRUPT_INCONSISTENT,
            CodingWorkflowBlockReason.VALIDATION_COMMAND_MISMATCH,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
            action_state="grant_consumed",
            result_message_id=evidence_reference.message_id,
        )
    cycle = interpret_persisted_validation_result(
        selection=selection,
        evidence_reference=evidence_reference,
        session_store=session_store,  # type: ignore[arg-type]
        workspace=workspace,
    )
    summary = _revalidation_summary_from_cycle(cycle)
    try:
        committed = _commit_revalidation_terminal(
            store=store,
            checkpoint=checkpoint,
            ref=ref,
            summary=summary,
            expected_revision=expected_revision,
        )
    except CheckpointStaleRevision:
        return CodingWorkflowInspection(
            workflow_id,
            CodingWorkflowDecision.STALE_REVISION,
            CodingWorkflowBlockReason.CHECKPOINT_STALE,
            checkpoint_revision=checkpoint.revision,
            session_id=checkpoint.session_id,
            action_id=ref.action_id,
        )
    return _inspect_checkpoint(committed, session_store=session_store, pending_action_store=pending_action_store)


def _reconstruct_validation_selection(
    action: dict[str, Any],
    checkpoint: CodingWorkflowCheckpoint,
) -> SelectedValidationCommand | None:
    details = action.get("details") if isinstance(action.get("details"), dict) else {}
    proposal = details.get("test_command_proposal") if isinstance(details, dict) else None
    provenance = details.get("pytest_provenance_request") if isinstance(details, dict) else None
    if not isinstance(proposal, dict) or not isinstance(provenance, dict):
        return None
    if proposal.get("intent") != "pytest" or proposal.get("delegates_to") != "run_shell":
        return None
    target = _string_field(proposal.get("target"))
    reason = _string_field(proposal.get("reason")) or ""
    generated = _string_field(proposal.get("generated_command"))
    provenance_digest = _string_field(provenance.get("logical_command_digest"))
    expected = checkpoint.selected_validation_command_digest
    if target is None or generated is None or provenance_digest is None or expected is None:
        return None
    normalized = _logical_command_from_generated_pytest_command(generated, target)
    if normalized is None:
        return None
    try:
        reconstructed_digest = logical_command_digest(normalized)
    except ValueError:
        return None
    if reconstructed_digest != expected or provenance_digest != expected:
        return None
    return SelectedValidationCommand(
        status="selected",
        command=normalized,
        normalized_command=normalized,
        target=target,
        command_index=0,
        reason=reason,
    )


def _logical_command_from_generated_pytest_command(generated: str, target: str) -> str | None:
    parts = generated.split()
    if not parts or not target:
        return None
    if parts[:3] == ["python", "-m", "pytest"] or parts[:3] == ["python3", "-m", "pytest"] or parts[:3] == ["py", "-m", "pytest"]:
        runner = parts[0]
        rest = parts[3:]
        prefix = f"{runner} -m pytest"
    elif parts[:1] == ["pytest"]:
        rest = parts[1:]
        prefix = "pytest"
    else:
        return None
    if not rest or rest[0] != target:
        return None
    quiet = len(rest) > 1 and rest[1] == "-q"
    return f"{prefix} {target}{' -q' if quiet else ''}"


def _external_result_evidence_reference(
    checkpoint: CodingWorkflowCheckpoint,
    ref: PendingActionReference,
    session_store: SessionEvidenceStore,
) -> SessionEvidenceReference | None:
    result = session_store.lookup_external_tool_result_evidence(
        checkpoint.session_id,
        action_id=ref.action_id,
    )
    if result.status == SessionEvidenceLookupStatus.FOUND and result.evidence is not None:
        return result.evidence
    return None


def _typed_validation_evidence_identity_matches(
    session_store: SessionEvidenceStore,
    evidence_reference: SessionEvidenceReference,
    checkpoint: CodingWorkflowCheckpoint,
) -> bool:
    expected = checkpoint.selected_validation_command_digest
    external = session_store.lookup_external_result_details(evidence_reference)
    if external.status != SessionEvidenceLookupStatus.FOUND or external.details is None:
        return False
    if external.details.logical_command_digest != expected:
        return False
    request = session_store.lookup_pytest_provenance_request(evidence_reference)
    if request.status not in {
        SessionEvidenceLookupStatus.FOUND,
        SessionEvidenceLookupStatus.NOT_FOUND,
        "invalid_provenance_request",
    }:
        return False
    if request.request is not None and request.request.logical_command_digest != expected:
        return False
    return True


def _validation_summary_from_cycle(cycle: Any) -> ValidationOutcomeSummary:
    observation = cycle.observation
    status = getattr(cycle.outcome, "final_status", "blocked")
    final_status = ValidationFinalStatus.PASSED if status == "passed" else ValidationFinalStatus.BLOCKED
    return ValidationOutcomeSummary(
        final_status=final_status,
        repair_attempted=False,
        revalidation_attempted=False,
        pytest_completion_category=getattr(observation, "pytest_completion_category", None) if observation is not None else None,
        failure_reason_code=getattr(observation, "failure_kind", None) if observation is not None else "validation_interpretation_blocked",
    )


def _revalidation_summary_from_cycle(cycle: Any) -> ValidationOutcomeSummary:
    observation = cycle.observation
    status = getattr(cycle.outcome, "final_status", "blocked")
    if status == "passed":
        final_status = ValidationFinalStatus.PASSED
    elif _is_trusted_tests_failed_cycle(cycle):
        final_status = ValidationFinalStatus.FAILED
    else:
        final_status = ValidationFinalStatus.BLOCKED
    return ValidationOutcomeSummary(
        final_status=final_status,
        repair_attempted=True,
        revalidation_attempted=True,
        pytest_completion_category=getattr(observation, "pytest_completion_category", None) if observation is not None else None,
        failure_reason_code=getattr(observation, "failure_kind", None) if observation is not None else "revalidation_interpretation_blocked",
    )


def _is_trusted_tests_failed_cycle(cycle: Any) -> bool:
    observation = cycle.observation
    return (
        cycle.status == "executed"
        and getattr(cycle.outcome, "final_status", None) == "failed"
        and observation is not None
        and observation.repair_eligible is True
        and observation.pytest_provenance_status == "valid"
        and observation.pytest_completion_category == "tests_failed"
    )


def _commit_initial_validation_ready_for_repair(
    *,
    store: CodingWorkflowCheckpointStore,
    checkpoint: CodingWorkflowCheckpoint,
    ref: PendingActionReference,
    expected_revision: int,
) -> CodingWorkflowCheckpoint:
    now = datetime.now(timezone.utc)
    replacement = _replace_checkpoint_fields(
        checkpoint,
        revision=checkpoint.revision + 1,
        phase=CodingWorkflowPhase.VALIDATION_COMPLETED,
        validation_execution_count=1,
        pending_action_ref=None,
        last_completed_action_ref=ref,
        updated_at=now,
    )
    return store.replace_checkpoint(replacement, expected_revision=expected_revision)


def _commit_revalidation_terminal(
    *,
    store: CodingWorkflowCheckpointStore,
    checkpoint: CodingWorkflowCheckpoint,
    ref: PendingActionReference,
    summary: ValidationOutcomeSummary,
    expected_revision: int,
) -> CodingWorkflowCheckpoint:
    completed_at = datetime.now(timezone.utc)
    replacement = _replace_checkpoint_fields(
        checkpoint,
        revision=checkpoint.revision + 1,
        phase=CodingWorkflowPhase.COMPLETED,
        validation_execution_count=2,
        repair_attempted=True,
        revalidation_attempted=True,
        pending_action_ref=None,
        last_completed_action_ref=ref,
        final_outcome_summary=summary,
        completion_marker=CodingWorkflowCompletion(completed_at=completed_at),
        terminal_outcome=CodingWorkflowTerminalOutcome(
            terminal_kind=CodingWorkflowTerminalKind.VALIDATION_COMPLETION,
            completed_at=completed_at,
            reason_code=f"revalidation_{summary.final_status.value}",
            validation_outcome_summary=summary,
        ),
        updated_at=completed_at,
    )
    return store.replace_checkpoint(replacement, expected_revision=expected_revision)


def _commit_initial_validation_terminal(
    *,
    store: CodingWorkflowCheckpointStore,
    checkpoint: CodingWorkflowCheckpoint,
    ref: PendingActionReference,
    summary: ValidationOutcomeSummary,
    expected_revision: int,
) -> CodingWorkflowCheckpoint:
    completed_at = datetime.now(timezone.utc)
    replacement = _replace_checkpoint_fields(
        checkpoint,
        revision=checkpoint.revision + 1,
        phase=CodingWorkflowPhase.COMPLETED,
        validation_execution_count=1,
        pending_action_ref=None,
        last_completed_action_ref=ref,
        final_outcome_summary=summary,
        completion_marker=CodingWorkflowCompletion(completed_at=completed_at),
        terminal_outcome=CodingWorkflowTerminalOutcome(
            terminal_kind=CodingWorkflowTerminalKind.VALIDATION_COMPLETION,
            completed_at=completed_at,
            reason_code=f"initial_validation_{summary.final_status.value}",
            validation_outcome_summary=summary,
        ),
        updated_at=completed_at,
    )
    return store.replace_checkpoint(replacement, expected_revision=expected_revision)


def _string_field(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _replace_checkpoint_fields(checkpoint: CodingWorkflowCheckpoint, **overrides: object) -> CodingWorkflowCheckpoint:
    values = {
        "schema_version": checkpoint.schema_version,
        "workflow_id": checkpoint.workflow_id,
        "session_id": checkpoint.session_id,
        "workflow_kind": checkpoint.workflow_kind,
        "revision": checkpoint.revision,
        "phase": checkpoint.phase,
        "selected_validation_command_digest": checkpoint.selected_validation_command_digest,
        "selected_validation_command_digest_algorithm": checkpoint.selected_validation_command_digest_algorithm,
        "validation_execution_count": checkpoint.validation_execution_count,
        "repair_attempted": checkpoint.repair_attempted,
        "revalidation_attempted": checkpoint.revalidation_attempted,
        "pending_action_ref": checkpoint.pending_action_ref,
        "last_completed_action_ref": checkpoint.last_completed_action_ref,
        "final_outcome_summary": checkpoint.final_outcome_summary,
        "completion_marker": checkpoint.completion_marker,
        "model_continuation_intent": checkpoint.model_continuation_intent,
        "terminal_outcome": checkpoint.terminal_outcome,
        "created_at": checkpoint.created_at,
        "updated_at": checkpoint.updated_at,
        "integrity_digest": None,
    }
    values.update(overrides)
    return CodingWorkflowCheckpoint(**values)  # type: ignore[arg-type]


def _blocked(workflow_id: str, reason: CodingWorkflowBlockReason) -> CodingWorkflowInspection:
    return CodingWorkflowInspection(workflow_id, CodingWorkflowDecision.BLOCKED_UNCERTAIN, reason)


__all__ = [
    "CodingWorkflowBlockReason",
    "CodingWorkflowDecision",
    "CodingWorkflowInspection",
    "CodingWorkflowResumeResult",
    "inspect_coding_workflow",
    "resume_coding_workflow",
]
