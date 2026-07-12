from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import uuid
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pp_agent.coding.validation_outcome import SelectedValidationCommand

PYTEST_PROVENANCE_SCHEMA_VERSION = 1
PYTEST_PROVENANCE_PLUGIN_ID = "pp_agent.coding.pytest_provenance_plugin"
PYTEST_PROVENANCE_PLUGIN_VERSION = "1"
PYTEST_PROVENANCE_DIR = ".pp-agent/validation-provenance"
PYTEST_PROVENANCE_MAX_BYTES = 4096

PytestCompletionCategory = Literal[
    "passed",
    "tests_failed",
    "interrupted",
    "internal_error",
    "usage_error",
    "no_tests_collected",
    "unknown",
]
PytestProvenanceStatus = Literal["valid", "invalid", "missing", "skipped"]

_EXIT_STATUS_BY_CATEGORY: dict[str, int] = {
    "passed": 0,
    "tests_failed": 1,
    "interrupted": 2,
    "internal_error": 3,
    "usage_error": 4,
    "no_tests_collected": 5,
}
_CATEGORY_BY_EXIT_STATUS = {value: key for key, value in _EXIT_STATUS_BY_CATEGORY.items()}
_ATTESTATION_FIELDS = {
    "schema_version",
    "plugin_id",
    "plugin_version",
    "nonce",
    "logical_command_digest",
    "category",
    "pytest_exit_status",
}
_RESERVED_ARGUMENTS = {
    "-p",
    "--pp-echo-pytest-provenance-file",
    "--pp-echo-pytest-provenance-nonce",
    "--pp-echo-pytest-logical-command-digest",
}


@dataclass(frozen=True)
class PytestProvenanceRequest:
    """Host-side request for one pytest provenance attestation artifact."""

    nonce: str
    logical_command_digest: str
    artifact_path: Path
    artifact_relative_path: str

    def to_internal_tool_args(self) -> dict[str, object]:
        return {
            "schema_version": PYTEST_PROVENANCE_SCHEMA_VERSION,
            "plugin_id": PYTEST_PROVENANCE_PLUGIN_ID,
            "plugin_version": PYTEST_PROVENANCE_PLUGIN_VERSION,
            "nonce": self.nonce,
            "logical_command_digest": self.logical_command_digest,
            "artifact_relative_path": self.artifact_relative_path,
        }


@dataclass(frozen=True)
class InstrumentedValidationCommand:
    """A logical pytest command plus host-only instrumentation arguments."""

    runner: str
    target: str
    quiet: bool
    logical_command: str
    logical_command_digest: str
    provenance_request: PytestProvenanceRequest

    def to_stage_test_internal_args(self) -> dict[str, object]:
        return {
            "runner": self.runner,
            "target": self.target,
            "quiet": self.quiet,
            "provenance": self.provenance_request.to_internal_tool_args(),
        }


@dataclass(frozen=True)
class PytestProvenanceVerification:
    """Verified pytest completion provenance, or a fail-closed diagnostic."""

    status: PytestProvenanceStatus
    category: PytestCompletionCategory | None = None
    pytest_exit_status: int | None = None
    failure_kind: str | None = None

    @property
    def valid(self) -> bool:
        return self.status == "valid"

    @property
    def repair_eligible(self) -> bool:
        return self.valid and self.category == "tests_failed"

    def to_observation_metadata(self) -> dict[str, object | None]:
        return {
            "pytest_provenance_status": self.status,
            "pytest_completion_category": self.category,
            "pytest_exit_status": self.pytest_exit_status,
            "pytest_provenance_failure": self.failure_kind,
        }


def build_instrumented_validation_command(
    selection: SelectedValidationCommand,
    *,
    workspace: Path,
) -> InstrumentedValidationCommand:
    """Create a host-owned pytest provenance request without changing logical command identity."""

    if not selection.selected or not selection.normalized_command or not selection.target:
        raise ValueError("A selected pytest validation command is required.")
    runner, target, quiet = _parse_supported_logical_command(selection.normalized_command)
    if target != selection.target:
        raise ValueError("Selected pytest target does not match normalized command.")
    digest = logical_command_digest(selection.normalized_command)
    nonce = uuid.uuid4().hex
    relative = f"{PYTEST_PROVENANCE_DIR}/{nonce}.json"
    artifact = _workspace_contained_path(workspace, relative)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    if artifact.exists():
        artifact.unlink()
    return InstrumentedValidationCommand(
        runner=runner,
        target=target,
        quiet=quiet,
        logical_command=selection.normalized_command,
        logical_command_digest=digest,
        provenance_request=PytestProvenanceRequest(
            nonce=nonce,
            logical_command_digest=digest,
            artifact_path=artifact,
            artifact_relative_path=relative,
        ),
    )


def logical_command_digest(command: str) -> str:
    normalized = str(command or "").strip()
    if not normalized:
        raise ValueError("logical command is required.")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def write_pytest_provenance_attestation(
    *,
    artifact_path: Path,
    nonce: str,
    logical_command_digest: str,
    pytest_exit_status: int,
) -> None:
    """Write a small atomic pytest provenance attestation from the trusted plugin."""

    category = _CATEGORY_BY_EXIT_STATUS.get(int(pytest_exit_status), "unknown")
    payload = {
        "schema_version": PYTEST_PROVENANCE_SCHEMA_VERSION,
        "plugin_id": PYTEST_PROVENANCE_PLUGIN_ID,
        "plugin_version": PYTEST_PROVENANCE_PLUGIN_VERSION,
        "nonce": str(nonce),
        "logical_command_digest": str(logical_command_digest),
        "category": category,
        "pytest_exit_status": int(pytest_exit_status),
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = artifact_path.with_name(f"{artifact_path.name}.tmp")
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    tmp_path.write_text(rendered, encoding="utf-8")
    tmp_path.replace(artifact_path)


def verify_pytest_provenance_attestation(
    request: PytestProvenanceRequest,
    *,
    exit_code: int | None,
    timed_out: bool,
    tool_failed: bool = False,
    cleanup: bool = True,
) -> PytestProvenanceVerification:
    """Verify the one expected pytest attestation and fail closed on any mismatch."""

    path = request.artifact_path
    try:
        if timed_out:
            return PytestProvenanceVerification(status="invalid", failure_kind="timeout")
        if tool_failed and exit_code is None:
            return PytestProvenanceVerification(status="invalid", failure_kind="tool_failed")
        if not path.exists():
            return PytestProvenanceVerification(status="missing", failure_kind="artifact_missing")
        if not path.is_file():
            return PytestProvenanceVerification(status="invalid", failure_kind="artifact_not_file")
        if path.stat().st_size > PYTEST_PROVENANCE_MAX_BYTES:
            return PytestProvenanceVerification(status="invalid", failure_kind="artifact_oversized")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return PytestProvenanceVerification(status="invalid", failure_kind="artifact_malformed")
        if not isinstance(payload, dict):
            return PytestProvenanceVerification(status="invalid", failure_kind="artifact_not_object")
        if set(payload) != _ATTESTATION_FIELDS:
            return PytestProvenanceVerification(status="invalid", failure_kind="artifact_schema_fields")
        if payload.get("schema_version") != PYTEST_PROVENANCE_SCHEMA_VERSION:
            return PytestProvenanceVerification(status="invalid", failure_kind="schema_version_mismatch")
        if payload.get("plugin_id") != PYTEST_PROVENANCE_PLUGIN_ID:
            return PytestProvenanceVerification(status="invalid", failure_kind="plugin_identity_mismatch")
        if payload.get("plugin_version") != PYTEST_PROVENANCE_PLUGIN_VERSION:
            return PytestProvenanceVerification(status="invalid", failure_kind="plugin_version_mismatch")
        if payload.get("nonce") != request.nonce:
            return PytestProvenanceVerification(status="invalid", failure_kind="nonce_mismatch")
        if payload.get("logical_command_digest") != request.logical_command_digest:
            return PytestProvenanceVerification(status="invalid", failure_kind="logical_command_digest_mismatch")
        category = str(payload.get("category") or "")
        pytest_exit_status = _optional_int(payload.get("pytest_exit_status"))
        if category not in _EXIT_STATUS_BY_CATEGORY and category != "unknown":
            return PytestProvenanceVerification(status="invalid", failure_kind="unknown_category")
        if pytest_exit_status is None:
            return PytestProvenanceVerification(status="invalid", failure_kind="missing_pytest_exit_status")
        if category == "unknown":
            if pytest_exit_status in _CATEGORY_BY_EXIT_STATUS:
                return PytestProvenanceVerification(status="invalid", failure_kind="category_exit_status_mismatch")
        elif _EXIT_STATUS_BY_CATEGORY[category] != pytest_exit_status:
            return PytestProvenanceVerification(status="invalid", failure_kind="category_exit_status_mismatch")
        if exit_code is not None and int(exit_code) != pytest_exit_status:
            return PytestProvenanceVerification(status="invalid", failure_kind="process_exit_status_mismatch")
        return PytestProvenanceVerification(
            status="valid",
            category=category,  # type: ignore[arg-type]
            pytest_exit_status=pytest_exit_status,
        )
    finally:
        if cleanup:
            try:
                path.unlink(missing_ok=True)
                path.with_name(f"{path.name}.tmp").unlink(missing_ok=True)
            except OSError:
                pass


def provenance_request_from_pending_details(
    details: dict[str, Any],
    *,
    workspace: Path,
) -> PytestProvenanceRequest | None:
    raw = details.get("pytest_provenance_request")
    if not isinstance(raw, dict):
        return None
    try:
        artifact_relative = str(raw["artifact_relative_path"])
        return PytestProvenanceRequest(
            nonce=str(raw["nonce"]),
            logical_command_digest=str(raw["logical_command_digest"]),
            artifact_path=_workspace_contained_path(workspace, artifact_relative),
            artifact_relative_path=artifact_relative,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _workspace_contained_path(workspace: Path, relative: str) -> Path:
    raw = str(relative or "").replace("\\", "/")
    if not raw.startswith(f"{PYTEST_PROVENANCE_DIR}/"):
        raise ValueError("pytest provenance artifact must use the validation provenance directory.")
    path = Path(raw)
    if path.is_absolute() or path.drive:
        raise ValueError("pytest provenance artifact path must be workspace-relative.")
    resolved = (workspace / path).resolve()
    root = workspace.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("pytest provenance artifact path must stay inside the workspace.")
    return resolved


def _parse_supported_logical_command(command: str) -> tuple[str, str, bool]:
    parts = str(command or "").strip().split()
    if len(parts) < 2:
        raise ValueError("Unsupported pytest command.")
    if any(part in _RESERVED_ARGUMENTS or part.startswith("--pp-echo-pytest-") for part in parts):
        raise ValueError("Pytest command contains reserved provenance arguments.")
    if parts[0] in {"python", "python3", "py"}:
        if len(parts) < 4 or parts[1:3] != ["-m", "pytest"]:
            raise ValueError("Unsupported pytest command.")
        runner = parts[0]
        args = parts[3:]
    elif parts[0] == "pytest":
        runner = "pytest"
        args = parts[1:]
    else:
        raise ValueError("Unsupported pytest command.")
    if len(args) == 1:
        return runner, args[0], False
    if len(args) == 2 and args[1] == "-q":
        return runner, args[0], True
    raise ValueError("Unsupported pytest command arguments.")


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
