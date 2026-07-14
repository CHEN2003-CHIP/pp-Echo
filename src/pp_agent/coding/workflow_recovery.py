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
    CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2,
    CodingWorkflowCheckpoint,
    CodingWorkflowPhase,
    ModelContinuationIntent,
    ModelContinuationState,
    PendingActionReference,
    PendingActionRole,
    SessionCompletionEvidenceReference,
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
    CheckpointTerminal,
    CheckpointUnsupportedSchema,
    CodingWorkflowCheckpointStore,
)
class SessionEvidenceLookupStatus:
    FOUND = "found"
    AMBIGUOUS = "ambiguous"


class SessionEvidenceStore(Protocol):
    def lookup_external_tool_result_evidence(self, session_id: str, *, action_id: str, result_digest: str | None = None) -> Any:
        ...

    def lookup_model_continuation_completion_evidence(self, session_id: str, *, continuation_id: str) -> Any:
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
    if checkpoint.schema_version != CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2:
        return CodingWorkflowInspection(
            **base,
            decision=CodingWorkflowDecision.LEGACY_CHECKPOINT_NOT_RESUMABLE,
            reason=CodingWorkflowBlockReason.LEGACY_NOT_RESUMABLE,
        )
    if checkpoint.phase == CodingWorkflowPhase.COMPLETED:
        return CodingWorkflowInspection(**base, decision=CodingWorkflowDecision.COMPLETED)
    if checkpoint.phase in _MISSION_07_PHASES or checkpoint.validation_execution_count > 0 or checkpoint.repair_attempted or checkpoint.revalidation_attempted:
        return CodingWorkflowInspection(
            **base,
            decision=CodingWorkflowDecision.MISSION_07_DEFERRED,
            reason=CodingWorkflowBlockReason.MISSION_07_DEFERRED,
        )
    if checkpoint.pending_action_ref is not None or checkpoint.phase in _AWAITING_PHASES:
        return _inspect_pending_action(checkpoint, pending_action_store=pending_action_store, session_store=session_store)
    intent = checkpoint.model_continuation_intent
    if intent is not None:
        completion = session_store.lookup_model_continuation_completion_evidence(checkpoint.session_id, continuation_id=intent.continuation_id)
        if intent.state == ModelContinuationState.SESSION_COMMITTED:
            return CodingWorkflowInspection(
                **base,
                decision=CodingWorkflowDecision.CONTINUATION_COMPLETED_IN_SESSION,
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
        updated_at=datetime.now(timezone.utc),
        model_continuation_intent=committed_intent,
    )
    return store.replace_checkpoint(replacement, expected_revision=expected_revision)


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
