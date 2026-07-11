from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from pp_agent.coding.repository_summary import repository_relative_posix_path
from pp_agent.coding.scope import TaskScope
from pp_agent.coding.scoped_instruction import (
    ScopedInstruction,
    ScopedInstructionWarning,
    resolve_scoped_instructions,
)


@dataclass(frozen=True)
class ScopedInstructionActivationRecord:
    """One active scoped instruction and its first safe trigger provenance."""

    instruction: ScopedInstruction
    trigger_kind: str
    trigger_path: str

    @property
    def activation_identity(self) -> tuple[str, str]:
        return (self.instruction.source_path, self.instruction.content_digest)

    def to_dict(self, *, include_content: bool = False) -> dict[str, object]:
        instruction = self.instruction.to_dict()
        if not include_content:
            instruction = {key: value for key, value in instruction.items() if key != "content"}
        return {
            "instruction": instruction,
            "trigger_kind": self.trigger_kind,
            "trigger_path": self.trigger_path,
        }


@dataclass
class ScopedInstructionActivationState:
    """Run-scoped activation state for task/read scoped repository instructions."""

    repository_root: Path
    active_by_source_path: dict[str, ScopedInstructionActivationRecord] = field(default_factory=dict)
    seeded_targets: list[str] = field(default_factory=list)
    observed_read_targets: list[str] = field(default_factory=list)
    warnings: list[ScopedInstructionWarning] = field(default_factory=list)
    current_duplicate_claims: set[tuple[str, str]] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.repository_root = self.repository_root.resolve()

    def begin_continuation(self) -> None:
        """Start a new tool-processing continuation for duplicate-claim suppression."""

        self.current_duplicate_claims.clear()

    def seed_task_scope(self, scope: TaskScope) -> None:
        """Activate scoped instructions for concrete TaskScope paths only."""

        for target in concrete_task_scope_targets(scope):
            self.seed_target(target)

    def seed_target(self, target_path: str | Path) -> None:
        """Resolve and activate instructions for one concrete task target."""

        self._activate_target(target_path, trigger_kind="task_scope", target_bucket=self.seeded_targets)

    def observe_read_result(self, *, tool_name: str, result: Any) -> None:
        """Activate instructions after a successful structured read_file result."""

        if tool_name != "read_file" or result.tool_name not in {"", "read_file"}:
            return
        if result.is_error:
            return
        details = result.details if isinstance(result.details, dict) else {}
        if details.get("attachment_fallback"):
            return
        path = details.get("path")
        if not isinstance(path, str) or not path.strip():
            return
        self._activate_target(path, trigger_kind="read_file", target_bucket=self.observed_read_targets, claim_duplicates=True)

    def active_instructions(self) -> tuple[ScopedInstruction, ...]:
        """Return a deterministic active instruction set without duplicate source versions."""

        return tuple(record.instruction for record in self.active_records())

    def active_records(self) -> tuple[ScopedInstructionActivationRecord, ...]:
        """Return deterministic activation records ordered by scope depth then source path."""

        return tuple(sorted(self.active_by_source_path.values(), key=_record_sort_key))

    def to_dict(self, *, include_content: bool = False) -> dict[str, object]:
        """Serialize state without absolute paths or raw runtime objects."""

        return {
            "active_records": [record.to_dict(include_content=include_content) for record in self.active_records()],
            "seeded_targets": list(self.seeded_targets),
            "observed_read_targets": list(self.observed_read_targets),
            "warnings": [warning.to_dict() for warning in self.warnings],
        }

    def summary(self) -> dict[str, object]:
        """Return trace-safe bounded activation metadata for loop summaries."""

        return {
            "active_count": len(self.active_by_source_path),
            "active_sources": [record.instruction.source_path for record in self.active_records()],
            "seeded_target_count": len(self.seeded_targets),
            "observed_read_target_count": len(self.observed_read_targets),
            "warning_count": len(self.warnings),
        }

    def _activate_target(
        self,
        target_path: str | Path,
        *,
        trigger_kind: str,
        target_bucket: list[str],
        claim_duplicates: bool = False,
    ) -> None:
        normalized = self._canonical_target_path(target_path)
        if normalized is None:
            return
        claim_key = (trigger_kind, normalized)
        if claim_duplicates and claim_key in self.current_duplicate_claims:
            return
        self.current_duplicate_claims.add(claim_key)
        if normalized not in target_bucket:
            target_bucket.append(normalized)
        resolution = resolve_scoped_instructions(repository_root=self.repository_root, target_path=normalized)
        self._merge_warnings(resolution.warnings)
        for instruction in resolution.instructions:
            self._activate_instruction(instruction, trigger_kind=trigger_kind, trigger_path=normalized)

    def _activate_instruction(self, instruction: ScopedInstruction, *, trigger_kind: str, trigger_path: str) -> None:
        existing = self.active_by_source_path.get(instruction.source_path)
        if existing is not None and existing.instruction.content_digest == instruction.content_digest:
            return
        self.active_by_source_path[instruction.source_path] = ScopedInstructionActivationRecord(
            instruction=instruction,
            trigger_kind=existing.trigger_kind if existing is not None else trigger_kind,
            trigger_path=existing.trigger_path if existing is not None else trigger_path,
        )

    def _merge_warnings(self, warnings: tuple[ScopedInstructionWarning, ...]) -> None:
        seen = {_warning_key(warning) for warning in self.warnings}
        for warning in warnings:
            key = _warning_key(warning)
            if key in seen:
                continue
            seen.add(key)
            self.warnings.append(warning)

    def _canonical_target_path(self, target_path: str | Path) -> str | None:
        raw = str(target_path).strip()
        if not raw:
            return None
        try:
            candidate = Path(target_path)
            if candidate.is_absolute():
                resolved = candidate.resolve(strict=False)
                normalized = resolved.relative_to(self.repository_root).as_posix()
            else:
                normalized = repository_relative_posix_path(raw)
        except (OSError, ValueError):
            return None
        if normalized in {"", "."}:
            return None
        return normalized


def concrete_task_scope_targets(scope: TaskScope) -> tuple[str, ...]:
    """Return concrete repository-relative TaskScope targets without expanding broad scopes."""

    targets: list[str] = []
    for raw in scope.allowed_paths:
        target = _concrete_scope_target(raw)
        if target is None or target in targets:
            continue
        targets.append(target)
    return tuple(targets)


def _concrete_scope_target(raw: str) -> str | None:
    value = str(raw or "").strip().replace("\\", "/").rstrip("/")
    if not value or value in {".", "/"}:
        return None
    if "*" in value:
        return None
    try:
        normalized = repository_relative_posix_path(value)
    except ValueError:
        return None
    if not normalized or normalized == ".":
        return None
    return PurePosixPath(normalized).as_posix()


def _record_sort_key(record: ScopedInstructionActivationRecord) -> tuple[int, str]:
    scope_root = record.instruction.scope_root
    depth = len(PurePosixPath(scope_root).parts) if scope_root else 0
    return (depth, record.instruction.source_path)


def _warning_key(warning: ScopedInstructionWarning) -> tuple[Any, ...]:
    return (warning.code, warning.source_path, warning.scope_root, warning.source_kind, warning.message)
