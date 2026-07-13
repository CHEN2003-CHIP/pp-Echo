from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import uuid
import hashlib
from typing import Any, Callable, Mapping

from pp_agent.coding.workflow_checkpoint import (
    CODING_WORKFLOW_CHECKPOINT_INITIAL_REVISION,
    MAX_CHECKPOINT_JSON_BYTES,
    CheckpointValidationError,
    CodingWorkflowCheckpoint,
    CodingWorkflowPhase,
    PendingActionReference,
    checkpoint_from_dict,
    checkpoint_integrity_digest,
    checkpoint_to_canonical_json,
    next_checkpoint_revision,
)
from pp_agent.runtime.workspace_lock import (
    WorkspaceApplyLock,
    WorkspaceApplyLockError,
    WorkspaceApplyLockTimeout,
)


CHECKPOINT_NAMESPACE = Path(".pp-agent") / "workflow-checkpoints" / "coding"
CHECKPOINT_FILE_EXTENSION = ".json"
CHECKPOINT_TEMP_SUFFIX = ".tmp"


class CheckpointStorageError(RuntimeError):
    """Base class for coding workflow checkpoint storage failures."""

    code = "storage_error"


class CheckpointNotFound(CheckpointStorageError):
    code = "not_found"


class CheckpointAlreadyExists(CheckpointStorageError):
    code = "already_exists"


class CheckpointStaleRevision(CheckpointStorageError):
    code = "stale_revision"


class CheckpointTerminal(CheckpointStorageError):
    code = "terminal"


class CheckpointLockUnavailable(CheckpointStorageError):
    code = "lock_unavailable"


class CheckpointOversized(CheckpointStorageError):
    code = "oversized"


class CheckpointCorrupt(CheckpointStorageError):
    code = "corrupt"


class CheckpointUnsupportedSchema(CheckpointCorrupt):
    code = "unsupported_schema"


class CheckpointIntegrityFailure(CheckpointCorrupt):
    code = "integrity_failure"


class CheckpointIdentityMismatch(CheckpointCorrupt):
    code = "identity_mismatch"


class CheckpointInvariantViolation(CheckpointCorrupt):
    code = "invariant_violation"


class CheckpointIoFailure(CheckpointStorageError):
    code = "io_failure"


class ReconciliationDecision(str, Enum):
    COMPLETED = "completed"
    INSPECT_ONLY = "inspect_only"
    AWAITING_AUTHORITATIVE_ACTION = "awaiting_authoritative_action"
    BLOCKED_CORRUPT_STATE = "blocked_corrupt_state"
    BLOCKED_INCONSISTENT_STATE = "blocked_inconsistent_state"
    STALE_REVISION = "stale_revision"
    NOT_RESUMABLE = "not_resumable"
    NEEDS_BOUNDARY_RECONCILIATION = "needs_boundary_reconciliation"


@dataclass(frozen=True)
class PendingActionEvidence:
    """Read-only safe evidence about pending actions for one workflow."""

    active_count: int = 0
    referenced_action_exists: bool | None = None
    referenced_action_id: str | None = None
    referenced_action_digest: str | None = None
    referenced_action_role: str | None = None
    conflicting_active_count: int = 0


@dataclass(frozen=True)
class CodingRecoveryEvidence:
    """Read-only recovery evidence without transcript, tokens, payloads, or traces."""

    session_exists: bool | None = None
    session_id: str | None = None
    pending_action: PendingActionEvidence | None = None
    loaded_revision: int | None = None
    checkpoint_error_code: str | None = None


@dataclass(frozen=True)
class CheckpointReconciliationResult:
    decision: ReconciliationDecision
    reason: str
    workflow_id: str | None = None
    session_id: str | None = None
    checkpoint_revision: int | None = None
    evidence_revision: int | None = None


class _FileSystemOps:
    def replace(self, source: Path, target: Path) -> None:
        os.replace(source, target)

    def fsync_file(self, handle: Any) -> None:
        os.fsync(handle.fileno())

    def fsync_directory(self, path: Path) -> None:
        if os.name == "nt":
            return
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


LockFactory = Callable[[Path], WorkspaceApplyLock]


class CodingWorkflowCheckpointStore:
    """Coding-owned atomic checkpoint persistence for the 08B checkpoint contract."""

    def __init__(
        self,
        workspace: Path,
        *,
        lock_factory: LockFactory | None = None,
        fs_ops: _FileSystemOps | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        try:
            self.workspace.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CheckpointIoFailure("could not create checkpoint workspace") from exc
        self.root = (self.workspace / CHECKPOINT_NAMESPACE).resolve()
        self._lock_factory = lock_factory or (lambda workspace: WorkspaceApplyLock(workspace))
        self._fs_ops = fs_ops or _FileSystemOps()
        self._validate_contained(self.root)

    def checkpoint_path(self, workflow_id: str) -> Path:
        filename = f"{_workflow_filename_digest(workflow_id)}{CHECKPOINT_FILE_EXTENSION}"
        path = (self.root / filename).resolve()
        self._validate_contained(path)
        return path

    def checkpoint_exists(self, workflow_id: str) -> bool:
        return self.checkpoint_path(workflow_id).exists()

    def create_checkpoint(self, checkpoint: CodingWorkflowCheckpoint) -> CodingWorkflowCheckpoint:
        if checkpoint.revision != CODING_WORKFLOW_CHECKPOINT_INITIAL_REVISION:
            raise CheckpointStaleRevision("initial checkpoint revision must be 0")
        persisted = self._with_integrity(checkpoint)
        target = self.checkpoint_path(persisted.workflow_id)
        with self._acquire_lock():
            self._prepare_root()
            if target.exists():
                raise CheckpointAlreadyExists("checkpoint already exists")
            self._atomic_write(target, checkpoint_to_canonical_json(persisted).encode("utf-8"))
        return persisted

    def load_checkpoint(self, workflow_id: str) -> CodingWorkflowCheckpoint:
        path = self.checkpoint_path(workflow_id)
        if not path.exists():
            raise CheckpointNotFound("checkpoint not found")
        data = self._read_bounded_json(path)
        checkpoint = self._checkpoint_from_json(data)
        if checkpoint.workflow_id != workflow_id:
            raise CheckpointIdentityMismatch("checkpoint workflow identity mismatch")
        return checkpoint

    def replace_checkpoint(
        self,
        checkpoint: CodingWorkflowCheckpoint,
        *,
        expected_revision: int,
    ) -> CodingWorkflowCheckpoint:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise CheckpointStaleRevision("expected revision is invalid")
        target = self.checkpoint_path(checkpoint.workflow_id)
        with self._acquire_lock():
            current = self.load_checkpoint(checkpoint.workflow_id)
            if current.phase == CodingWorkflowPhase.COMPLETED:
                raise CheckpointTerminal("completed checkpoint is immutable")
            if current.revision != expected_revision:
                raise CheckpointStaleRevision("checkpoint revision is stale")
            expected_next = next_checkpoint_revision(current.revision)
            if checkpoint.revision != expected_next:
                raise CheckpointStaleRevision("replacement checkpoint must use the next revision")
            if checkpoint.workflow_id != current.workflow_id or checkpoint.session_id != current.session_id:
                raise CheckpointIdentityMismatch("checkpoint identity cannot change")
            persisted = self._with_integrity(checkpoint)
            self._atomic_write(target, checkpoint_to_canonical_json(persisted).encode("utf-8"))
        return persisted

    def delete_checkpoint(self, workflow_id: str) -> None:
        raise NotImplementedError("checkpoint deletion is deferred")

    def _checkpoint_from_json(self, data: Mapping[str, Any]) -> CodingWorkflowCheckpoint:
        try:
            return checkpoint_from_dict(data)
        except CheckpointValidationError as exc:
            message = str(exc)
            if "schema_version" in message:
                raise CheckpointUnsupportedSchema("checkpoint schema is unsupported") from exc
            if "integrity_digest" in message:
                raise CheckpointIntegrityFailure("checkpoint integrity digest mismatch") from exc
            raise CheckpointInvariantViolation("checkpoint invariant violation") from exc

    def _read_bounded_json(self, path: Path) -> dict[str, Any]:
        try:
            stat = path.stat()
        except OSError as exc:
            raise CheckpointIoFailure("could not stat checkpoint") from exc
        if stat.st_size > MAX_CHECKPOINT_JSON_BYTES:
            raise CheckpointOversized("checkpoint file exceeds maximum size")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CheckpointIoFailure("could not read checkpoint") from exc
        if len(raw) > MAX_CHECKPOINT_JSON_BYTES:
            raise CheckpointOversized("checkpoint file exceeds maximum size")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CheckpointCorrupt("checkpoint is not valid UTF-8") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CheckpointCorrupt("checkpoint is not valid JSON") from exc
        if not isinstance(data, dict):
            raise CheckpointCorrupt("checkpoint JSON must be an object")
        return data

    def _atomic_write(self, target: Path, data: bytes) -> None:
        if len(data) > MAX_CHECKPOINT_JSON_BYTES:
            raise CheckpointOversized("checkpoint canonical JSON exceeds maximum size")
        self._validate_contained(target)
        self._prepare_root()
        temp = self._temp_path_for(target)
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
                self._fs_ops.fsync_file(handle)
            self._fs_ops.replace(temp, target)
            self._fs_ops.fsync_directory(target.parent)
        except CheckpointStorageError:
            raise
        except OSError as exc:
            raise CheckpointIoFailure("checkpoint atomic write failed") from exc
        finally:
            try:
                if temp.exists():
                    if temp.is_dir():
                        temp.rmdir()
                    else:
                        temp.unlink()
            except OSError:
                pass

    def _temp_path_for(self, target: Path) -> Path:
        temp = target.with_name(f".{target.stem}.{os.getpid()}.{uuid.uuid4().hex}{CHECKPOINT_TEMP_SUFFIX}")
        self._validate_contained(temp.resolve())
        return temp

    def _prepare_root(self) -> None:
        pp_agent = self.workspace / ".pp-agent"
        self._ensure_dir(pp_agent)
        self._ensure_dir(pp_agent / "workflow-checkpoints")
        self._ensure_dir(self.root)

    def _ensure_dir(self, path: Path) -> None:
        if path.exists() and path.is_symlink():
            raise CheckpointIoFailure("checkpoint storage directory is a symlink")
        try:
            path.mkdir(mode=0o700, exist_ok=True)
        except OSError as exc:
            raise CheckpointIoFailure("could not create checkpoint storage directory") from exc
        if path.is_symlink():
            raise CheckpointIoFailure("checkpoint storage directory is a symlink")
        self._validate_contained(path.resolve())

    def _acquire_lock(self) -> Any:
        try:
            return self._lock_factory(self.workspace).acquire()
        except WorkspaceApplyLockTimeout as exc:
            raise CheckpointLockUnavailable("checkpoint lock unavailable") from exc
        except WorkspaceApplyLockError as exc:
            raise CheckpointLockUnavailable("checkpoint lock unavailable") from exc

    def _validate_contained(self, path: Path) -> None:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise CheckpointIoFailure("checkpoint path escapes workspace") from exc

    @staticmethod
    def _with_integrity(checkpoint: CodingWorkflowCheckpoint) -> CodingWorkflowCheckpoint:
        digest = checkpoint_integrity_digest(checkpoint)
        return CodingWorkflowCheckpoint(
            schema_version=checkpoint.schema_version,
            workflow_id=checkpoint.workflow_id,
            session_id=checkpoint.session_id,
            workflow_kind=checkpoint.workflow_kind,
            revision=checkpoint.revision,
            phase=checkpoint.phase,
            selected_validation_command_digest=checkpoint.selected_validation_command_digest,
            selected_validation_command_digest_algorithm=checkpoint.selected_validation_command_digest_algorithm,
            validation_execution_count=checkpoint.validation_execution_count,
            repair_attempted=checkpoint.repair_attempted,
            revalidation_attempted=checkpoint.revalidation_attempted,
            pending_action_ref=checkpoint.pending_action_ref,
            last_completed_action_ref=checkpoint.last_completed_action_ref,
            final_outcome_summary=checkpoint.final_outcome_summary,
            completion_marker=checkpoint.completion_marker,
            created_at=checkpoint.created_at,
            updated_at=checkpoint.updated_at,
            integrity_digest=digest,
        )


def reconcile_checkpoint(
    checkpoint: CodingWorkflowCheckpoint | None,
    evidence: CodingRecoveryEvidence,
) -> CheckpointReconciliationResult:
    """Return a read-only reconciliation decision without executing recovery."""

    if checkpoint is None:
        return CheckpointReconciliationResult(
            decision=ReconciliationDecision.BLOCKED_CORRUPT_STATE if evidence.checkpoint_error_code else ReconciliationDecision.NOT_RESUMABLE,
            reason=evidence.checkpoint_error_code or "checkpoint_missing",
            evidence_revision=evidence.loaded_revision,
        )
    if evidence.loaded_revision is not None and evidence.loaded_revision != checkpoint.revision:
        return _result(checkpoint, ReconciliationDecision.STALE_REVISION, "stale_revision", evidence)
    if evidence.session_exists is False:
        return _result(checkpoint, ReconciliationDecision.BLOCKED_INCONSISTENT_STATE, "session_missing", evidence)
    if evidence.session_id is not None and evidence.session_id != checkpoint.session_id:
        return _result(checkpoint, ReconciliationDecision.BLOCKED_INCONSISTENT_STATE, "session_identity_mismatch", evidence)
    pending = evidence.pending_action
    if pending is not None:
        if pending.active_count < 0 or pending.conflicting_active_count < 0:
            return _result(checkpoint, ReconciliationDecision.BLOCKED_INCONSISTENT_STATE, "invalid_pending_counts", evidence)
        if pending.active_count > 1 or pending.conflicting_active_count > 0:
            return _result(checkpoint, ReconciliationDecision.BLOCKED_INCONSISTENT_STATE, "multiple_active_actions", evidence)
    if checkpoint.phase == CodingWorkflowPhase.COMPLETED:
        if pending is not None and pending.active_count > 0:
            return _result(checkpoint, ReconciliationDecision.BLOCKED_INCONSISTENT_STATE, "completed_with_active_pending_action", evidence)
        return _result(checkpoint, ReconciliationDecision.COMPLETED, "completed", evidence)
    if checkpoint.pending_action_ref is not None:
        if pending is None or pending.referenced_action_exists is None:
            return _result(checkpoint, ReconciliationDecision.NEEDS_BOUNDARY_RECONCILIATION, "pending_action_evidence_missing", evidence)
        if pending.referenced_action_exists is False:
            return _result(checkpoint, ReconciliationDecision.BLOCKED_INCONSISTENT_STATE, "referenced_action_missing", evidence)
        if not _pending_reference_matches(checkpoint.pending_action_ref, pending):
            return _result(checkpoint, ReconciliationDecision.BLOCKED_INCONSISTENT_STATE, "referenced_action_identity_mismatch", evidence)
        return _result(checkpoint, ReconciliationDecision.AWAITING_AUTHORITATIVE_ACTION, "awaiting_authoritative_action", evidence)
    if pending is not None and pending.active_count > 0:
        return _result(checkpoint, ReconciliationDecision.BLOCKED_INCONSISTENT_STATE, "unexpected_active_pending_action", evidence)
    if evidence.session_exists is None:
        return _result(checkpoint, ReconciliationDecision.INSPECT_ONLY, "insufficient_session_evidence", evidence)
    return _result(checkpoint, ReconciliationDecision.INSPECT_ONLY, "inspect_only", evidence)


def _pending_reference_matches(reference: PendingActionReference, evidence: PendingActionEvidence) -> bool:
    if evidence.referenced_action_id is not None and evidence.referenced_action_id != reference.action_id:
        return False
    if evidence.referenced_action_digest is not None and reference.action_digest is not None and evidence.referenced_action_digest != reference.action_digest:
        return False
    if evidence.referenced_action_role is not None and evidence.referenced_action_role != reference.role.value:
        return False
    return True


def _result(
    checkpoint: CodingWorkflowCheckpoint,
    decision: ReconciliationDecision,
    reason: str,
    evidence: CodingRecoveryEvidence,
) -> CheckpointReconciliationResult:
    return CheckpointReconciliationResult(
        decision=decision,
        reason=reason,
        workflow_id=checkpoint.workflow_id,
        session_id=checkpoint.session_id,
        checkpoint_revision=checkpoint.revision,
        evidence_revision=evidence.loaded_revision,
    )


def _workflow_filename_digest(workflow_id: str) -> str:
    if not isinstance(workflow_id, str) or not workflow_id:
        raise CheckpointIdentityMismatch("workflow_id is required")
    return hashlib.sha256(workflow_id.encode("utf-8")).hexdigest()


__all__ = [
    "CHECKPOINT_FILE_EXTENSION",
    "CHECKPOINT_NAMESPACE",
    "CHECKPOINT_TEMP_SUFFIX",
    "CheckpointAlreadyExists",
    "CheckpointCorrupt",
    "CheckpointIdentityMismatch",
    "CheckpointIntegrityFailure",
    "CheckpointInvariantViolation",
    "CheckpointIoFailure",
    "CheckpointLockUnavailable",
    "CheckpointNotFound",
    "CheckpointOversized",
    "CheckpointReconciliationResult",
    "CheckpointStaleRevision",
    "CheckpointStorageError",
    "CheckpointTerminal",
    "CheckpointUnsupportedSchema",
    "CodingRecoveryEvidence",
    "CodingWorkflowCheckpointStore",
    "PendingActionEvidence",
    "ReconciliationDecision",
    "reconcile_checkpoint",
]
