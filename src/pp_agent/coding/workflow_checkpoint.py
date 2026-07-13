from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping


CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION = 1
CODING_WORKFLOW_CHECKPOINT_DIGEST_ALGORITHM = "sha256"
CODING_WORKFLOW_CHECKPOINT_KIND = "controlled_coding"
CODING_WORKFLOW_CHECKPOINT_INITIAL_REVISION = 0

MAX_IDENTIFIER_LENGTH = 128
MAX_ACTION_TYPE_LENGTH = 64
MAX_FAILURE_CODE_LENGTH = 96
MAX_CHECKPOINT_JSON_BYTES = 16 * 1024

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[a-f0-9]{64}$")
_FORBIDDEN_PAYLOAD_KEYS = {
    "approval_token",
    "artifact_path",
    "command",
    "environment",
    "env",
    "nonce",
    "patch",
    "raw_attestation",
    "stderr",
    "stdout",
    "task",
    "token",
}


class CheckpointValidationError(ValueError):
    """Raised when a coding workflow checkpoint fails closed validation."""


class CodingWorkflowKind(str, Enum):
    CONTROLLED_CODING = CODING_WORKFLOW_CHECKPOINT_KIND


class CodingWorkflowPhase(str, Enum):
    PREPARED = "prepared"
    RUNTIME_STARTED = "runtime_started"
    AWAITING_TOOL_APPROVAL = "awaiting_tool_approval"
    TOOL_COMPLETED = "tool_completed"
    AWAITING_VALIDATION_APPROVAL = "awaiting_validation_approval"
    VALIDATION_COMPLETED = "validation_completed"
    REPAIR_STARTED = "repair_started"
    AWAITING_REPAIR_TOOL_APPROVAL = "awaiting_repair_tool_approval"
    REPAIR_COMPLETED = "repair_completed"
    AWAITING_REVALIDATION_APPROVAL = "awaiting_revalidation_approval"
    REVALIDATION_COMPLETED = "revalidation_completed"
    FINALIZED = "finalized"
    COMPLETED = "completed"
    BLOCKED_CORRUPT = "blocked_corrupt"
    BLOCKED_INCONSISTENT = "blocked_inconsistent"


class PendingActionRole(str, Enum):
    TOOL = "tool"
    VALIDATION = "validation"
    REPAIR_TOOL = "repair_tool"
    REVALIDATION = "revalidation"


class ValidationFinalStatus(str, Enum):
    NOT_RUN = "not_run"
    APPROVAL_PENDING = "approval_pending"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    VALIDATION_NONZERO = "validation_nonzero"


@dataclass(frozen=True)
class PendingActionReference:
    """Safe reference to a pending action without approval state or token data."""

    action_id: str
    role: PendingActionRole
    action_digest: str | None = None
    action_type: str | None = None

    def __post_init__(self) -> None:
        _validate_identifier(self.action_id, "pending_action_ref.action_id")
        if not isinstance(self.role, PendingActionRole):
            raise CheckpointValidationError("pending_action_ref.role must be PendingActionRole")
        if self.action_digest is not None:
            _validate_digest(self.action_digest, "pending_action_ref.action_digest")
        if self.action_type is not None:
            _validate_bounded_text(self.action_type, "pending_action_ref.action_type", MAX_ACTION_TYPE_LENGTH)

    def to_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "role": self.role.value,
            "action_digest": self.action_digest,
            "action_type": self.action_type,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PendingActionReference":
        _reject_unknown_fields(data, {"action_id", "role", "action_digest", "action_type"}, "pending_action_ref")
        return cls(
            action_id=_required_str(data, "action_id"),
            role=_enum_value(PendingActionRole, data.get("role"), "pending_action_ref.role"),
            action_digest=_optional_str(data.get("action_digest"), "pending_action_ref.action_digest"),
            action_type=_optional_str(data.get("action_type"), "pending_action_ref.action_type"),
        )


@dataclass(frozen=True)
class ValidationOutcomeSummary:
    """Bounded final validation outcome summary for checkpoint persistence."""

    final_status: ValidationFinalStatus
    repair_attempted: bool
    revalidation_attempted: bool
    pytest_completion_category: str | None = None
    failure_reason_code: str | None = None
    completion_kind: str = "validation_outcome"

    def __post_init__(self) -> None:
        if not isinstance(self.final_status, ValidationFinalStatus):
            raise CheckpointValidationError("final_outcome_summary.final_status must be ValidationFinalStatus")
        _validate_bool(self.repair_attempted, "final_outcome_summary.repair_attempted")
        _validate_bool(self.revalidation_attempted, "final_outcome_summary.revalidation_attempted")
        if self.revalidation_attempted and not self.repair_attempted:
            raise CheckpointValidationError("revalidation summary requires repair_attempted=true")
        if self.pytest_completion_category is not None:
            _validate_bounded_text(self.pytest_completion_category, "final_outcome_summary.pytest_completion_category", MAX_FAILURE_CODE_LENGTH)
        if self.failure_reason_code is not None:
            _validate_bounded_text(self.failure_reason_code, "final_outcome_summary.failure_reason_code", MAX_FAILURE_CODE_LENGTH)
        _validate_bounded_text(self.completion_kind, "final_outcome_summary.completion_kind", MAX_FAILURE_CODE_LENGTH)

    def to_dict(self) -> dict[str, object]:
        return {
            "final_status": self.final_status.value,
            "repair_attempted": self.repair_attempted,
            "revalidation_attempted": self.revalidation_attempted,
            "pytest_completion_category": self.pytest_completion_category,
            "failure_reason_code": self.failure_reason_code,
            "completion_kind": self.completion_kind,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ValidationOutcomeSummary":
        _reject_forbidden_payload_keys(data, "final_outcome_summary")
        _reject_unknown_fields(
            data,
            {
                "final_status",
                "repair_attempted",
                "revalidation_attempted",
                "pytest_completion_category",
                "failure_reason_code",
                "completion_kind",
            },
            "final_outcome_summary",
        )
        return cls(
            final_status=_enum_value(ValidationFinalStatus, data.get("final_status"), "final_outcome_summary.final_status"),
            repair_attempted=_required_bool(data, "repair_attempted"),
            revalidation_attempted=_required_bool(data, "revalidation_attempted"),
            pytest_completion_category=_optional_str(data.get("pytest_completion_category"), "final_outcome_summary.pytest_completion_category"),
            failure_reason_code=_optional_str(data.get("failure_reason_code"), "final_outcome_summary.failure_reason_code"),
            completion_kind=_optional_str(data.get("completion_kind"), "final_outcome_summary.completion_kind") or "validation_outcome",
        )


@dataclass(frozen=True)
class CodingWorkflowCompletion:
    """Explicit terminal marker separate from phase and final outcome."""

    completed_at: datetime
    marker: str = "completed"

    def __post_init__(self) -> None:
        _validate_utc_datetime(self.completed_at, "completion_marker.completed_at")
        if self.marker != "completed":
            raise CheckpointValidationError("completion_marker.marker must be 'completed'")

    def to_dict(self) -> dict[str, object]:
        return {"marker": self.marker, "completed_at": _format_utc(self.completed_at)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CodingWorkflowCompletion":
        _reject_unknown_fields(data, {"marker", "completed_at"}, "completion_marker")
        return cls(
            marker=_required_str(data, "marker"),
            completed_at=_parse_utc_datetime(data.get("completed_at"), "completion_marker.completed_at"),
        )


@dataclass(frozen=True)
class CodingWorkflowCheckpoint:
    """Versioned, immutable, JSON-safe checkpoint contract for coding workflow recovery."""

    schema_version: int
    workflow_id: str
    session_id: str
    workflow_kind: CodingWorkflowKind
    revision: int
    phase: CodingWorkflowPhase
    validation_execution_count: int
    repair_attempted: bool
    revalidation_attempted: bool
    created_at: datetime
    updated_at: datetime
    selected_validation_command_digest: str | None = None
    selected_validation_command_digest_algorithm: str | None = None
    pending_action_ref: PendingActionReference | None = None
    last_completed_action_ref: PendingActionReference | None = None
    final_outcome_summary: ValidationOutcomeSummary | None = None
    completion_marker: CodingWorkflowCompletion | None = None
    integrity_digest: str | None = None

    def __post_init__(self) -> None:
        validate_checkpoint(self)

    def to_dict(self, *, include_integrity: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "session_id": self.session_id,
            "workflow_kind": self.workflow_kind.value,
            "revision": self.revision,
            "phase": self.phase.value,
            "selected_validation_command_digest": self.selected_validation_command_digest,
            "selected_validation_command_digest_algorithm": self.selected_validation_command_digest_algorithm,
            "validation_execution_count": self.validation_execution_count,
            "repair_attempted": self.repair_attempted,
            "revalidation_attempted": self.revalidation_attempted,
            "pending_action_ref": self.pending_action_ref.to_dict() if self.pending_action_ref is not None else None,
            "last_completed_action_ref": self.last_completed_action_ref.to_dict() if self.last_completed_action_ref is not None else None,
            "final_outcome_summary": self.final_outcome_summary.to_dict() if self.final_outcome_summary is not None else None,
            "completion_marker": self.completion_marker.to_dict() if self.completion_marker is not None else None,
            "created_at": _format_utc(self.created_at),
            "updated_at": _format_utc(self.updated_at),
        }
        if include_integrity:
            payload["integrity_digest"] = self.integrity_digest
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CodingWorkflowCheckpoint":
        _reject_forbidden_payload_keys(data, "checkpoint")
        _reject_unknown_fields(
            data,
            {
                "schema_version",
                "workflow_id",
                "session_id",
                "workflow_kind",
                "revision",
                "phase",
                "selected_validation_command_digest",
                "selected_validation_command_digest_algorithm",
                "validation_execution_count",
                "repair_attempted",
                "revalidation_attempted",
                "pending_action_ref",
                "last_completed_action_ref",
                "final_outcome_summary",
                "completion_marker",
                "created_at",
                "updated_at",
                "integrity_digest",
            },
            "checkpoint",
        )
        return cls(
            schema_version=_required_int(data, "schema_version"),
            workflow_id=_required_str(data, "workflow_id"),
            session_id=_required_str(data, "session_id"),
            workflow_kind=_enum_value(CodingWorkflowKind, data.get("workflow_kind"), "workflow_kind"),
            revision=_required_int(data, "revision"),
            phase=_enum_value(CodingWorkflowPhase, data.get("phase"), "phase"),
            selected_validation_command_digest=_optional_str(data.get("selected_validation_command_digest"), "selected_validation_command_digest"),
            selected_validation_command_digest_algorithm=_optional_str(
                data.get("selected_validation_command_digest_algorithm"),
                "selected_validation_command_digest_algorithm",
            ),
            validation_execution_count=_required_int(data, "validation_execution_count"),
            repair_attempted=_required_bool(data, "repair_attempted"),
            revalidation_attempted=_required_bool(data, "revalidation_attempted"),
            pending_action_ref=_optional_nested(PendingActionReference, data.get("pending_action_ref"), "pending_action_ref"),
            last_completed_action_ref=_optional_nested(PendingActionReference, data.get("last_completed_action_ref"), "last_completed_action_ref"),
            final_outcome_summary=_optional_nested(ValidationOutcomeSummary, data.get("final_outcome_summary"), "final_outcome_summary"),
            completion_marker=_optional_nested(CodingWorkflowCompletion, data.get("completion_marker"), "completion_marker"),
            created_at=_parse_utc_datetime(data.get("created_at"), "created_at"),
            updated_at=_parse_utc_datetime(data.get("updated_at"), "updated_at"),
            integrity_digest=_optional_str(data.get("integrity_digest"), "integrity_digest"),
        )


def validate_checkpoint(checkpoint: CodingWorkflowCheckpoint) -> CodingWorkflowCheckpoint:
    """Validate contract-local checkpoint facts without I/O or external stores."""

    if checkpoint.schema_version != CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION:
        raise CheckpointValidationError("unsupported checkpoint schema_version")
    _validate_identifier(checkpoint.workflow_id, "workflow_id")
    _validate_identifier(checkpoint.session_id, "session_id")
    if not isinstance(checkpoint.workflow_kind, CodingWorkflowKind):
        raise CheckpointValidationError("workflow_kind must be CodingWorkflowKind")
    if not isinstance(checkpoint.phase, CodingWorkflowPhase):
        raise CheckpointValidationError("phase must be CodingWorkflowPhase")
    _validate_revision(checkpoint.revision)
    _validate_validation_count(checkpoint.validation_execution_count)
    _validate_bool(checkpoint.repair_attempted, "repair_attempted")
    _validate_bool(checkpoint.revalidation_attempted, "revalidation_attempted")
    _validate_utc_datetime(checkpoint.created_at, "created_at")
    _validate_utc_datetime(checkpoint.updated_at, "updated_at")
    if checkpoint.created_at > checkpoint.updated_at:
        raise CheckpointValidationError("created_at must not be later than updated_at")
    _validate_selected_command_digest(checkpoint)
    _validate_phase_action_ref(checkpoint)
    _validate_mission_07_invariants(checkpoint)
    _validate_completion_contract(checkpoint)
    _validate_integrity_digest(checkpoint)
    return checkpoint


def next_checkpoint_revision(revision: int) -> int:
    _validate_revision(revision)
    return revision + 1


def checkpoint_to_canonical_json(checkpoint: CodingWorkflowCheckpoint, *, include_integrity: bool = True) -> str:
    payload = checkpoint.to_dict(include_integrity=include_integrity)
    encoded = _canonical_json(payload)
    if len(encoded.encode("utf-8")) > MAX_CHECKPOINT_JSON_BYTES:
        raise CheckpointValidationError("checkpoint canonical JSON exceeds maximum size")
    return encoded


def checkpoint_integrity_digest(checkpoint: CodingWorkflowCheckpoint) -> str:
    return _sha256_hex(checkpoint_to_canonical_json(checkpoint, include_integrity=False).encode("utf-8"))


def checkpoint_from_dict(data: Mapping[str, Any]) -> CodingWorkflowCheckpoint:
    return CodingWorkflowCheckpoint.from_dict(data)


def checkpoint_to_dict(checkpoint: CodingWorkflowCheckpoint) -> dict[str, object]:
    return checkpoint.to_dict()


def _validate_selected_command_digest(checkpoint: CodingWorkflowCheckpoint) -> None:
    digest = checkpoint.selected_validation_command_digest
    algorithm = checkpoint.selected_validation_command_digest_algorithm
    if digest is None:
        if algorithm is not None:
            raise CheckpointValidationError("selected_validation_command_digest_algorithm requires digest")
    else:
        _validate_digest(digest, "selected_validation_command_digest")
        if algorithm != CODING_WORKFLOW_CHECKPOINT_DIGEST_ALGORITHM:
            raise CheckpointValidationError("selected_validation_command_digest_algorithm must be sha256")
    if checkpoint.validation_execution_count > 0 and digest is None:
        raise CheckpointValidationError("selected command digest is required once validation has executed")
    if checkpoint.phase in _PHASES_REQUIRING_SELECTED_COMMAND and digest is None:
        raise CheckpointValidationError("selected command digest is required for validation and repair phases")


def _validate_phase_action_ref(checkpoint: CodingWorkflowCheckpoint) -> None:
    if checkpoint.phase in _PHASE_PENDING_ROLES:
        if checkpoint.pending_action_ref is None:
            raise CheckpointValidationError("pending_action_ref is required for awaiting approval phases")
        expected = _PHASE_PENDING_ROLES[checkpoint.phase]
        if checkpoint.pending_action_ref.role != expected:
            raise CheckpointValidationError("pending_action_ref role does not match phase")
    elif checkpoint.pending_action_ref is not None:
        raise CheckpointValidationError("pending_action_ref is only allowed for awaiting approval phases")


def _validate_mission_07_invariants(checkpoint: CodingWorkflowCheckpoint) -> None:
    if checkpoint.revalidation_attempted and not checkpoint.repair_attempted:
        raise CheckpointValidationError("revalidation_attempted requires repair_attempted")
    if checkpoint.validation_execution_count == 2 and not checkpoint.revalidation_attempted:
        raise CheckpointValidationError("validation_execution_count=2 requires revalidation_attempted")
    if checkpoint.revalidation_attempted and checkpoint.validation_execution_count < 1:
        raise CheckpointValidationError("revalidation_attempted requires at least one validation execution")
    if checkpoint.phase in _REPAIR_PHASES and not checkpoint.repair_attempted:
        raise CheckpointValidationError("repair phase requires repair_attempted")
    if checkpoint.phase in _REVALIDATION_PHASES and not checkpoint.revalidation_attempted:
        raise CheckpointValidationError("revalidation phase requires revalidation_attempted")
    if checkpoint.phase in _POST_VALIDATION_PHASES and checkpoint.validation_execution_count < 1:
        raise CheckpointValidationError("post-validation phase requires validation_execution_count >= 1")
    if checkpoint.phase == CodingWorkflowPhase.REVALIDATION_COMPLETED and checkpoint.validation_execution_count != 2:
        raise CheckpointValidationError("revalidation_completed requires validation_execution_count=2")


def _validate_completion_contract(checkpoint: CodingWorkflowCheckpoint) -> None:
    if checkpoint.final_outcome_summary is not None:
        if checkpoint.validation_execution_count == 0:
            raise CheckpointValidationError("final outcome requires validation_execution_count > 0")
        if checkpoint.final_outcome_summary.repair_attempted != checkpoint.repair_attempted:
            raise CheckpointValidationError("final outcome repair flag must match checkpoint")
        if checkpoint.final_outcome_summary.revalidation_attempted != checkpoint.revalidation_attempted:
            raise CheckpointValidationError("final outcome revalidation flag must match checkpoint")
    if checkpoint.phase == CodingWorkflowPhase.COMPLETED:
        if checkpoint.final_outcome_summary is None:
            raise CheckpointValidationError("completed checkpoint requires final_outcome_summary")
        if checkpoint.completion_marker is None:
            raise CheckpointValidationError("completed checkpoint requires completion_marker")
        if checkpoint.pending_action_ref is not None:
            raise CheckpointValidationError("completed checkpoint must not have active pending action reference")
        return
    if checkpoint.completion_marker is not None:
        raise CheckpointValidationError("completion_marker is only allowed for completed phase")
    if checkpoint.phase == CodingWorkflowPhase.FINALIZED:
        if checkpoint.final_outcome_summary is None:
            raise CheckpointValidationError("finalized phase requires final_outcome_summary")
    elif checkpoint.final_outcome_summary is not None:
        raise CheckpointValidationError("final_outcome_summary is only allowed for finalized or completed phase")


def _validate_integrity_digest(checkpoint: CodingWorkflowCheckpoint) -> None:
    if checkpoint.integrity_digest is None:
        return
    _validate_digest(checkpoint.integrity_digest, "integrity_digest")
    expected = checkpoint_integrity_digest(
        CodingWorkflowCheckpoint(
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
            integrity_digest=None,
        )
    )
    if checkpoint.integrity_digest != expected:
        raise CheckpointValidationError("integrity_digest mismatch")


def _required_str(data: Mapping[str, Any], key: str) -> str:
    if key not in data:
        raise CheckpointValidationError(f"missing required field: {key}")
    value = data[key]
    if not isinstance(value, str):
        raise CheckpointValidationError(f"{key} must be a string")
    return value


def _optional_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CheckpointValidationError(f"{field} must be a string or null")
    return value


def _required_int(data: Mapping[str, Any], key: str) -> int:
    if key not in data:
        raise CheckpointValidationError(f"missing required field: {key}")
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise CheckpointValidationError(f"{key} must be an integer")
    return value


def _required_bool(data: Mapping[str, Any], key: str) -> bool:
    if key not in data:
        raise CheckpointValidationError(f"missing required field: {key}")
    value = data[key]
    _validate_bool(value, key)
    return value


def _validate_bool(value: Any, field: str) -> None:
    if not isinstance(value, bool):
        raise CheckpointValidationError(f"{field} must be a boolean")


def _enum_value(enum_type: type[Enum], value: Any, field: str) -> Any:
    if not isinstance(value, str):
        raise CheckpointValidationError(f"{field} must be a string enum value")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise CheckpointValidationError(f"unknown {field}") from exc


def _optional_nested(cls: Any, value: Any, field: str) -> Any:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise CheckpointValidationError(f"{field} must be an object or null")
    return cls.from_dict(value)


def _validate_identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CheckpointValidationError(f"{field} is required")
    if len(value) > MAX_IDENTIFIER_LENGTH or not _IDENTIFIER_RE.match(value):
        raise CheckpointValidationError(f"{field} has invalid format")


def _validate_bounded_text(value: str, field: str, limit: int) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CheckpointValidationError(f"{field} is required")
    if len(value) > limit or any(char in value for char in "\r\n\t"):
        raise CheckpointValidationError(f"{field} exceeds safe bounds")


def _validate_digest(value: str, field: str) -> None:
    if not isinstance(value, str) or not _DIGEST_RE.match(value):
        raise CheckpointValidationError(f"{field} must be a sha256 hex digest")


def _validate_revision(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CheckpointValidationError("revision must be an integer")
    if value < CODING_WORKFLOW_CHECKPOINT_INITIAL_REVISION:
        raise CheckpointValidationError("revision must not be negative")
    if value > 9_007_199_254_740_991:
        raise CheckpointValidationError("revision exceeds safe integer bound")


def _validate_validation_count(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CheckpointValidationError("validation_execution_count must be an integer")
    if value < 0 or value > 2:
        raise CheckpointValidationError("validation_execution_count must be between 0 and 2")


def _validate_utc_datetime(value: datetime, field: str) -> None:
    if not isinstance(value, datetime):
        raise CheckpointValidationError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise CheckpointValidationError(f"{field} must be timezone-aware UTC")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise CheckpointValidationError(f"{field} must be UTC")


def _parse_utc_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise CheckpointValidationError(f"{field} must be an ISO-8601 UTC string")
    if not value.endswith("Z"):
        raise CheckpointValidationError(f"{field} must use UTC Z suffix")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CheckpointValidationError(f"{field} must be valid ISO-8601") from exc
    _validate_utc_datetime(parsed, field)
    return parsed


def _format_utc(value: datetime) -> str:
    _validate_utc_datetime(value, "timestamp")
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")


def _reject_unknown_fields(data: Mapping[str, Any], allowed: set[str], path: str) -> None:
    extra = set(data) - allowed
    if extra:
        raise CheckpointValidationError(f"{path} contains unknown fields")


def _reject_forbidden_payload_keys(data: Mapping[str, Any], path: str) -> None:
    forbidden = set(data) & _FORBIDDEN_PAYLOAD_KEYS
    if forbidden:
        raise CheckpointValidationError(f"{path} contains forbidden sensitive fields")


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_PHASE_PENDING_ROLES = {
    CodingWorkflowPhase.AWAITING_TOOL_APPROVAL: PendingActionRole.TOOL,
    CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL: PendingActionRole.VALIDATION,
    CodingWorkflowPhase.AWAITING_REPAIR_TOOL_APPROVAL: PendingActionRole.REPAIR_TOOL,
    CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL: PendingActionRole.REVALIDATION,
}
_PHASES_REQUIRING_SELECTED_COMMAND = {
    CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
    CodingWorkflowPhase.VALIDATION_COMPLETED,
    CodingWorkflowPhase.REPAIR_STARTED,
    CodingWorkflowPhase.AWAITING_REPAIR_TOOL_APPROVAL,
    CodingWorkflowPhase.REPAIR_COMPLETED,
    CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL,
    CodingWorkflowPhase.REVALIDATION_COMPLETED,
    CodingWorkflowPhase.FINALIZED,
    CodingWorkflowPhase.COMPLETED,
}
_POST_VALIDATION_PHASES = {
    CodingWorkflowPhase.VALIDATION_COMPLETED,
    CodingWorkflowPhase.REPAIR_STARTED,
    CodingWorkflowPhase.AWAITING_REPAIR_TOOL_APPROVAL,
    CodingWorkflowPhase.REPAIR_COMPLETED,
    CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL,
    CodingWorkflowPhase.REVALIDATION_COMPLETED,
    CodingWorkflowPhase.FINALIZED,
    CodingWorkflowPhase.COMPLETED,
}
_REPAIR_PHASES = {
    CodingWorkflowPhase.REPAIR_STARTED,
    CodingWorkflowPhase.AWAITING_REPAIR_TOOL_APPROVAL,
    CodingWorkflowPhase.REPAIR_COMPLETED,
    CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL,
    CodingWorkflowPhase.REVALIDATION_COMPLETED,
}
_REVALIDATION_PHASES = {
    CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL,
    CodingWorkflowPhase.REVALIDATION_COMPLETED,
}


__all__ = [
    "CODING_WORKFLOW_CHECKPOINT_DIGEST_ALGORITHM",
    "CODING_WORKFLOW_CHECKPOINT_INITIAL_REVISION",
    "CODING_WORKFLOW_CHECKPOINT_KIND",
    "CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION",
    "CheckpointValidationError",
    "CodingWorkflowCheckpoint",
    "CodingWorkflowCompletion",
    "CodingWorkflowKind",
    "CodingWorkflowPhase",
    "PendingActionReference",
    "PendingActionRole",
    "ValidationFinalStatus",
    "ValidationOutcomeSummary",
    "checkpoint_from_dict",
    "checkpoint_integrity_digest",
    "checkpoint_to_canonical_json",
    "checkpoint_to_dict",
    "next_checkpoint_revision",
    "validate_checkpoint",
]
