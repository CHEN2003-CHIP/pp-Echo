from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from pp_agent.coding import (
    CHECKPOINT_FILE_EXTENSION,
    CHECKPOINT_NAMESPACE,
    CODING_WORKFLOW_CHECKPOINT_DIGEST_ALGORITHM,
    CODING_WORKFLOW_CHECKPOINT_INITIAL_REVISION,
    CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION,
    CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2,
    CheckpointAlreadyExists,
    CheckpointCorrupt,
    CheckpointIdentityMismatch,
    CheckpointIntegrityFailure,
    CheckpointIoFailure,
    CheckpointLockUnavailable,
    CheckpointNotFound,
    CheckpointOversized,
    CheckpointStaleRevision,
    CheckpointTerminal,
    CheckpointUnsupportedSchema,
    CodingRecoveryEvidence,
    CodingWorkflowCheckpoint,
    CodingWorkflowCheckpointStore,
    CodingWorkflowCompletion,
    CodingWorkflowKind,
    CodingWorkflowPhase,
    ModelContinuationIntent,
    ModelContinuationState,
    PendingActionEvidence,
    PendingActionReference,
    PendingActionRole,
    ReconciliationDecision,
    ValidationFinalStatus,
    ValidationOutcomeSummary,
    checkpoint_to_canonical_json,
    reconcile_checkpoint,
)
from pp_agent.coding.workflow_checkpoint import MAX_CHECKPOINT_JSON_BYTES
from pp_agent.coding.workflow_checkpoint_store import _FileSystemOps
from pp_agent.runtime.workspace_lock import WorkspaceApplyLockTimeout


DIGEST = "a" * 64
def _now() -> datetime:
    return datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _checkpoint(**overrides: object) -> CodingWorkflowCheckpoint:
    values: dict[str, object] = {
        "schema_version": CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION,
        "workflow_id": "workflow-1",
        "session_id": "session-1",
        "workflow_kind": CodingWorkflowKind.CONTROLLED_CODING,
        "revision": CODING_WORKFLOW_CHECKPOINT_INITIAL_REVISION,
        "phase": CodingWorkflowPhase.PREPARED,
        "validation_execution_count": 0,
        "repair_attempted": False,
        "revalidation_attempted": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    values.update(overrides)
    return CodingWorkflowCheckpoint(**values)  # type: ignore[arg-type]


def _completed(**overrides: object) -> CodingWorkflowCheckpoint:
    values: dict[str, object] = {
        "phase": CodingWorkflowPhase.COMPLETED,
        "selected_validation_command_digest": DIGEST,
        "selected_validation_command_digest_algorithm": CODING_WORKFLOW_CHECKPOINT_DIGEST_ALGORITHM,
        "validation_execution_count": 1,
        "final_outcome_summary": ValidationOutcomeSummary(
            final_status=ValidationFinalStatus.PASSED,
            repair_attempted=False,
            revalidation_attempted=False,
        ),
        "completion_marker": CodingWorkflowCompletion(completed_at=_now()),
    }
    values.update(overrides)
    return _checkpoint(**values)


def _action_ref() -> PendingActionReference:
    return PendingActionReference(
        action_id="effect-1",
        action_digest=DIGEST,
        role=PendingActionRole.TOOL,
        action_type="run_shell",
    )


def _intent() -> ModelContinuationIntent:
    return ModelContinuationIntent(
        continuation_id="cont-1",
        source_action_ref=_action_ref(),
        source_result_digest="b" * 64,
        pre_call_session_id="session-1",
        pre_call_turn_id="turn-1",
        state=ModelContinuationState.INTENT_COMMITTED,
        created_at=_now(),
    )


def _next(checkpoint: CodingWorkflowCheckpoint, **overrides: object) -> CodingWorkflowCheckpoint:
    values = {
        **checkpoint.to_dict(include_integrity=False),
        "workflow_kind": checkpoint.workflow_kind,
        "phase": checkpoint.phase,
        "pending_action_ref": checkpoint.pending_action_ref,
        "last_completed_action_ref": checkpoint.last_completed_action_ref,
        "final_outcome_summary": checkpoint.final_outcome_summary,
        "completion_marker": checkpoint.completion_marker,
        "model_continuation_intent": checkpoint.model_continuation_intent,
        "created_at": checkpoint.created_at,
        "updated_at": checkpoint.updated_at,
        "revision": checkpoint.revision + 1,
    }
    values.update(overrides)
    return CodingWorkflowCheckpoint(**values)  # type: ignore[arg-type]


def test_store_root_and_digest_file_identity_are_workspace_contained(tmp_path: Path) -> None:
    store = CodingWorkflowCheckpointStore(tmp_path)
    path = store.checkpoint_path("workflow/../CON")

    assert store.root == (tmp_path / CHECKPOINT_NAMESPACE).resolve()
    assert path.parent == store.root
    assert path.suffix == CHECKPOINT_FILE_EXTENSION
    assert path.name.endswith(".json")
    assert ".." not in path.name
    assert "\\" not in path.name
    path.relative_to(tmp_path)


def test_different_workflow_ids_have_stable_non_colliding_paths(tmp_path: Path) -> None:
    store = CodingWorkflowCheckpointStore(tmp_path)

    first = store.checkpoint_path("workflow-1")
    second = store.checkpoint_path("workflow-2")

    assert first == store.checkpoint_path("workflow-1")
    assert first != second


def test_temp_files_are_not_treated_as_checkpoints(tmp_path: Path) -> None:
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.root.mkdir(parents=True)
    (store.root / ".orphan.tmp").write_text("{}", encoding="utf-8")

    with pytest.raises(CheckpointNotFound):
        store.load_checkpoint("workflow-1")


@pytest.mark.skipif(not hasattr(Path, "symlink_to"), reason="symlink unsupported")
def test_store_refuses_symlinked_pp_agent_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (tmp_path / ".pp-agent").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(CheckpointIoFailure):
        CodingWorkflowCheckpointStore(tmp_path).create_checkpoint(_checkpoint())


def test_create_load_round_trip_writes_canonical_integrity_payload(tmp_path: Path) -> None:
    store = CodingWorkflowCheckpointStore(tmp_path)
    checkpoint = _checkpoint()

    persisted = store.create_checkpoint(checkpoint)
    loaded = store.load_checkpoint(checkpoint.workflow_id)

    assert loaded == persisted
    assert loaded.integrity_digest is not None
    assert checkpoint.integrity_digest is None
    assert store.checkpoint_path(checkpoint.workflow_id).read_text(encoding="utf-8") == checkpoint_to_canonical_json(persisted)


def test_create_creates_directory_and_rejects_duplicate_or_non_initial_revision(tmp_path: Path) -> None:
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(_checkpoint())

    assert store.root.exists()
    with pytest.raises(CheckpointAlreadyExists):
        store.create_checkpoint(_checkpoint())
    with pytest.raises(CheckpointStaleRevision):
        store.create_checkpoint(_checkpoint(workflow_id="workflow-2", revision=1))


def test_load_missing_oversized_invalid_utf8_invalid_json_and_object_shape(tmp_path: Path) -> None:
    store = CodingWorkflowCheckpointStore(tmp_path)
    with pytest.raises(CheckpointNotFound):
        store.load_checkpoint("workflow-1")

    path = store.checkpoint_path("workflow-1")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * (MAX_CHECKPOINT_JSON_BYTES + 1))
    with pytest.raises(CheckpointOversized):
        store.load_checkpoint("workflow-1")

    path.write_bytes(b"\xff")
    with pytest.raises(CheckpointCorrupt):
        store.load_checkpoint("workflow-1")

    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(CheckpointCorrupt):
        store.load_checkpoint("workflow-1")

    path.write_text("[]", encoding="utf-8")
    with pytest.raises(CheckpointCorrupt):
        store.load_checkpoint("workflow-1")


def test_load_future_schema_integrity_mismatch_and_identity_mismatch_fail_closed(tmp_path: Path) -> None:
    store = CodingWorkflowCheckpointStore(tmp_path)
    persisted = store.create_checkpoint(_checkpoint())
    path = store.checkpoint_path(persisted.workflow_id)
    payload = persisted.to_dict()

    future = dict(payload)
    future["schema_version"] = 999
    path.write_text(json.dumps(future, sort_keys=True), encoding="utf-8")
    with pytest.raises(CheckpointUnsupportedSchema):
        store.load_checkpoint(persisted.workflow_id)

    bad_digest = dict(payload)
    bad_digest["revision"] = 99
    path.write_text(json.dumps(bad_digest, sort_keys=True), encoding="utf-8")
    with pytest.raises(CheckpointIntegrityFailure):
        store.load_checkpoint(persisted.workflow_id)

    changed_identity = dict(payload)
    changed_identity["workflow_id"] = "workflow-2"
    changed_identity["integrity_digest"] = None
    changed = CodingWorkflowCheckpoint.from_dict(changed_identity)
    changed_persisted = CodingWorkflowCheckpointStore._with_integrity(changed)
    path.write_text(checkpoint_to_canonical_json(changed_persisted), encoding="utf-8")
    with pytest.raises(CheckpointIdentityMismatch):
        store.load_checkpoint(persisted.workflow_id)


def test_replace_validates_cas_revision_identity_and_terminality(tmp_path: Path) -> None:
    store = CodingWorkflowCheckpointStore(tmp_path)
    current = store.create_checkpoint(_checkpoint())
    replacement = _next(current, phase=CodingWorkflowPhase.RUNTIME_STARTED)

    persisted = store.replace_checkpoint(replacement, expected_revision=0)

    assert persisted.revision == 1
    assert store.load_checkpoint("workflow-1").phase == CodingWorkflowPhase.RUNTIME_STARTED
    with pytest.raises(CheckpointStaleRevision):
        store.replace_checkpoint(_next(persisted), expected_revision=0)
    with pytest.raises(CheckpointStaleRevision):
        store.replace_checkpoint(_next(persisted, revision=3), expected_revision=1)
    with pytest.raises(CheckpointIdentityMismatch):
        store.replace_checkpoint(_next(persisted, session_id="session-2"), expected_revision=1)

    terminal_store = CodingWorkflowCheckpointStore(tmp_path / "terminal")
    terminal = terminal_store.create_checkpoint(_completed())
    with pytest.raises(CheckpointTerminal):
        terminal_store.replace_checkpoint(_next(terminal), expected_revision=0)


def test_store_loads_v2_checkpoint_and_rejects_silent_schema_upgrade(tmp_path: Path) -> None:
    store = CodingWorkflowCheckpointStore(tmp_path)
    current = store.create_checkpoint(
        _checkpoint(
            schema_version=CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2,
            phase=CodingWorkflowPhase.TOOL_COMPLETED,
            last_completed_action_ref=_action_ref(),
            model_continuation_intent=_intent(),
        )
    )

    loaded = store.load_checkpoint("workflow-1")

    assert loaded.schema_version == CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2
    assert loaded.model_continuation_intent == current.model_continuation_intent

    v1_store = CodingWorkflowCheckpointStore(tmp_path / "v1")
    v1_current = v1_store.create_checkpoint(_checkpoint())
    with pytest.raises(CheckpointCorrupt):
        v1_store.replace_checkpoint(
            _next(v1_current, schema_version=CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2),
            expected_revision=0,
        )


class _FailingTempStore(CodingWorkflowCheckpointStore):
    def _temp_path_for(self, target: Path) -> Path:
        temp = target.parent / "temp-as-directory.tmp"
        temp.mkdir(exist_ok=True)
        return temp


class _FailingFsyncOps(_FileSystemOps):
    def fsync_file(self, handle: Any) -> None:
        raise OSError("fsync failed")


class _FailingReplaceOps(_FileSystemOps):
    def replace(self, source: Path, target: Path) -> None:
        raise OSError("replace failed")


def test_atomic_write_failures_keep_old_checkpoint_intact_and_cleanup_owned_temp(tmp_path: Path) -> None:
    store = CodingWorkflowCheckpointStore(tmp_path)
    current = store.create_checkpoint(_checkpoint())
    old_text = store.checkpoint_path(current.workflow_id).read_text(encoding="utf-8")

    with pytest.raises(CheckpointIoFailure):
        _FailingTempStore(tmp_path).replace_checkpoint(_next(current), expected_revision=0)
    assert store.checkpoint_path(current.workflow_id).read_text(encoding="utf-8") == old_text
    assert not (store.root / "temp-as-directory.tmp").exists()

    with pytest.raises(CheckpointIoFailure):
        CodingWorkflowCheckpointStore(tmp_path, fs_ops=_FailingFsyncOps()).replace_checkpoint(_next(current), expected_revision=0)
    assert store.checkpoint_path(current.workflow_id).read_text(encoding="utf-8") == old_text

    with pytest.raises(CheckpointIoFailure):
        CodingWorkflowCheckpointStore(tmp_path, fs_ops=_FailingReplaceOps()).replace_checkpoint(_next(current), expected_revision=0)
    assert store.checkpoint_path(current.workflow_id).read_text(encoding="utf-8") == old_text
    assert not list(store.root.glob("*.tmp"))
    assert not list(store.root.glob(".*.tmp"))


def test_repeated_writers_with_same_expected_revision_do_not_blind_overwrite(tmp_path: Path) -> None:
    store = CodingWorkflowCheckpointStore(tmp_path)
    current = store.create_checkpoint(_checkpoint())
    first = _next(current, phase=CodingWorkflowPhase.RUNTIME_STARTED)
    second = _next(current, phase=CodingWorkflowPhase.TOOL_COMPLETED)

    store.replace_checkpoint(first, expected_revision=0)
    with pytest.raises(CheckpointStaleRevision):
        store.replace_checkpoint(second, expected_revision=0)

    loaded = store.load_checkpoint(current.workflow_id)
    assert loaded.revision == 1
    assert loaded.phase == CodingWorkflowPhase.RUNTIME_STARTED


def test_lock_failure_is_typed_and_release_allows_later_write(tmp_path: Path) -> None:
    def unavailable(_workspace: Path) -> Any:
        class Lock:
            def acquire(self) -> Any:
                raise WorkspaceApplyLockTimeout("busy")

        return Lock()

    with pytest.raises(CheckpointLockUnavailable):
        CodingWorkflowCheckpointStore(tmp_path, lock_factory=unavailable).create_checkpoint(_checkpoint())

    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(_checkpoint())
    assert store.load_checkpoint("workflow-1").revision == 0


def test_completed_reconciliation_is_deterministic_and_read_only() -> None:
    checkpoint = _completed()
    evidence = CodingRecoveryEvidence(
        session_exists=True,
        session_id=checkpoint.session_id,
        pending_action=PendingActionEvidence(active_count=0),
        loaded_revision=checkpoint.revision,
    )

    first = reconcile_checkpoint(checkpoint, evidence)
    second = reconcile_checkpoint(checkpoint, evidence)

    assert first == second
    assert first.decision == ReconciliationDecision.COMPLETED
    assert checkpoint.phase == CodingWorkflowPhase.COMPLETED


def test_reconciliation_detects_static_inconsistencies_without_advancing() -> None:
    pending_ref = PendingActionReference(
        action_id="effect-1",
        role=PendingActionRole.VALIDATION,
        action_digest=DIGEST,
    )
    awaiting = _checkpoint(
        phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
        selected_validation_command_digest=DIGEST,
        selected_validation_command_digest_algorithm=CODING_WORKFLOW_CHECKPOINT_DIGEST_ALGORITHM,
        pending_action_ref=pending_ref,
    )

    assert reconcile_checkpoint(None, CodingRecoveryEvidence(checkpoint_error_code="invalid_json")).decision == ReconciliationDecision.BLOCKED_CORRUPT_STATE
    assert reconcile_checkpoint(awaiting, CodingRecoveryEvidence(loaded_revision=99)).decision == ReconciliationDecision.STALE_REVISION
    assert reconcile_checkpoint(awaiting, CodingRecoveryEvidence(session_exists=False)).reason == "session_missing"
    assert reconcile_checkpoint(awaiting, CodingRecoveryEvidence(session_exists=True, session_id="other")).reason == "session_identity_mismatch"
    assert reconcile_checkpoint(awaiting, CodingRecoveryEvidence(session_exists=True, session_id="session-1")).decision == ReconciliationDecision.NEEDS_BOUNDARY_RECONCILIATION
    assert (
        reconcile_checkpoint(
            awaiting,
            CodingRecoveryEvidence(
                session_exists=True,
                session_id="session-1",
                pending_action=PendingActionEvidence(active_count=1, referenced_action_exists=False),
            ),
        ).reason
        == "referenced_action_missing"
    )
    assert (
        reconcile_checkpoint(
            awaiting,
            CodingRecoveryEvidence(
                session_exists=True,
                session_id="session-1",
                pending_action=PendingActionEvidence(
                    active_count=1,
                    referenced_action_exists=True,
                    referenced_action_id="effect-2",
                ),
            ),
        ).reason
        == "referenced_action_identity_mismatch"
    )
    assert (
        reconcile_checkpoint(
            awaiting,
            CodingRecoveryEvidence(
                session_exists=True,
                session_id="session-1",
                pending_action=PendingActionEvidence(
                    active_count=2,
                    referenced_action_exists=True,
                    referenced_action_id="effect-1",
                ),
            ),
        ).reason
        == "multiple_active_actions"
    )
    assert (
        reconcile_checkpoint(
            _completed(),
            CodingRecoveryEvidence(
                session_exists=True,
                session_id="session-1",
                pending_action=PendingActionEvidence(active_count=1),
            ),
        ).reason
        == "completed_with_active_pending_action"
    )


def test_reconciliation_awaits_authoritative_action_and_inspects_only_when_evidence_is_insufficient() -> None:
    pending_ref = PendingActionReference(
        action_id="effect-1",
        role=PendingActionRole.TOOL,
        action_digest=DIGEST,
    )
    awaiting = _checkpoint(
        phase=CodingWorkflowPhase.AWAITING_TOOL_APPROVAL,
        pending_action_ref=pending_ref,
    )

    result = reconcile_checkpoint(
        awaiting,
        CodingRecoveryEvidence(
            session_exists=True,
            session_id="session-1",
            pending_action=PendingActionEvidence(
                active_count=1,
                referenced_action_exists=True,
                referenced_action_id="effect-1",
                referenced_action_digest=DIGEST,
                referenced_action_role="tool",
            ),
        ),
    )
    inspect = reconcile_checkpoint(_checkpoint(), CodingRecoveryEvidence())

    assert result.decision == ReconciliationDecision.AWAITING_AUTHORITATIVE_ACTION
    assert inspect.decision == ReconciliationDecision.INSPECT_ONLY


def test_scope_protection_no_runtime_tool_approval_or_session_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> Any:  # pragma: no cover - should never run
        raise AssertionError("08C storage/reconciliation must not execute external side effects")

    monkeypatch.setattr(subprocess, "run", fail)

    store = CodingWorkflowCheckpointStore(tmp_path)
    checkpoint = store.create_checkpoint(_checkpoint())
    result = reconcile_checkpoint(
        checkpoint,
        CodingRecoveryEvidence(session_exists=True, session_id=checkpoint.session_id, pending_action=PendingActionEvidence(active_count=0)),
    )

    assert result.decision == ReconciliationDecision.INSPECT_ONLY
    assert not hasattr(store, "session_store")
    assert not hasattr(store, "pending_action_store")
