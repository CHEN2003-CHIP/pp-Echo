from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pp_agent.coding.repository_summary import repository_relative_posix_path
from pp_agent.coding.repository_summary_collector import (
    RepositorySummaryCollectionLimits,
    RepositorySummaryDocument,
    _LoadedDocument,
    _ResolvedDocument,
    _SkippedDocument,
    _WarningCollector,
    _document_source_key,
    _read_document,
    _resolve_document,
)


SCOPED_INSTRUCTION_FILENAMES = ("AGENTS.md", "CLAUDE.md")
ScopedInstructionKind = Literal["AGENTS.md", "CLAUDE.md"]


@dataclass(frozen=True)
class ScopedInstruction:
    """A bounded repository-local instruction resolved for a nested scope."""

    source_path: str
    scope_root: str
    source_kind: ScopedInstructionKind
    content: str
    content_digest: str
    bytes_consumed: int
    truncated: bool = False

    @property
    def source_identity(self) -> str:
        """Stable source identity; content freshness is represented separately by digest."""

        return self.source_path

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-friendly payload."""

        return {
            "source_path": self.source_path,
            "source_identity": self.source_identity,
            "scope_root": self.scope_root,
            "source_kind": self.source_kind,
            "content": self.content,
            "content_digest": self.content_digest,
            "bytes_consumed": self.bytes_consumed,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class ScopedInstructionWarning:
    """A controlled scoped-instruction warning without absolute paths."""

    code: str
    message: str
    source_path: str | None = None
    scope_root: str | None = None
    source_kind: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-friendly warning payload."""

        payload: dict[str, object] = {"code": self.code, "message": self.message}
        if self.source_path:
            payload["source_path"] = self.source_path
        if self.scope_root:
            payload["scope_root"] = self.scope_root
        if self.source_kind:
            payload["source_kind"] = self.source_kind
        return payload


@dataclass(frozen=True)
class ScopedInstructionResolution:
    """Result of a bounded scoped-instruction lookup."""

    instructions: tuple[ScopedInstruction, ...] = ()
    warnings: tuple[ScopedInstructionWarning, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-friendly payload."""

        return {
            "instructions": [instruction.to_dict() for instruction in self.instructions],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


def resolve_scoped_instructions(
    *,
    repository_root: Path,
    target_path: str | Path,
    limits: RepositorySummaryCollectionLimits | None = None,
) -> ScopedInstructionResolution:
    """Resolve nested AGENTS.md/CLAUDE.md instructions for one concrete target path.

    The resolver is runtime-independent: it has no TaskScope state, no read_file hook,
    and no ContextPipeline integration. Digests describe the bounded content consumed.
    """

    active_limits = limits or RepositorySummaryCollectionLimits()
    root = repository_root.resolve()
    target_resolution = _resolve_target(root, target_path)
    if isinstance(target_resolution, ScopedInstructionWarning):
        return ScopedInstructionResolution(warnings=(target_resolution,))

    start_directory, normalized_target = target_resolution
    instructions: list[ScopedInstruction] = []
    warnings: list[ScopedInstructionWarning] = []
    for directory in _scoped_directories(root, start_directory):
        selected, directory_warnings = _resolve_directory_instruction(root, directory, active_limits, normalized_target)
        warnings.extend(directory_warnings)
        if selected is not None:
            instructions.append(selected)
    return ScopedInstructionResolution(tuple(instructions), tuple(warnings))


def _resolve_target(root: Path, target_path: str | Path) -> tuple[Path, str] | ScopedInstructionWarning:
    raw_path = Path(target_path)
    if raw_path.is_absolute():
        candidate = raw_path
        resolved_for_identity = candidate.resolve(strict=False)
        if not _is_relative_to(resolved_for_identity, root):
            return ScopedInstructionWarning("outside_root_rejected", "Scoped instruction target path was outside the repository root.")
        normalized = resolved_for_identity.relative_to(root).as_posix()
    else:
        raw = str(target_path)
        try:
            normalized = repository_relative_posix_path(raw)
        except ValueError:
            return ScopedInstructionWarning("outside_root_rejected", "Scoped instruction target path was outside the repository root.")
        candidate = root / PurePosixPath(normalized)
    if candidate.exists():
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            return ScopedInstructionWarning("outside_root_rejected", "Scoped instruction target path could not be resolved safely.", source_path=normalized)
        if not _is_relative_to(resolved, root):
            return ScopedInstructionWarning("symlink_escape_rejected", "Scoped instruction target symlink escaped the repository root.", source_path=normalized)
        return (resolved if resolved.is_dir() else resolved.parent), normalized
    parent = candidate.parent.resolve(strict=False)
    if not _is_relative_to(parent, root):
        return ScopedInstructionWarning("outside_root_rejected", "Scoped instruction target path was outside the repository root.", source_path=normalized)
    return parent, normalized


def _scoped_directories(root: Path, start_directory: Path) -> list[Path]:
    directories: list[Path] = []
    current = start_directory.resolve(strict=False)
    while current != root and _is_relative_to(current, root):
        directories.append(current)
        current = current.parent
    return list(reversed(directories))


def _resolve_directory_instruction(
    root: Path,
    directory: Path,
    limits: RepositorySummaryCollectionLimits,
    normalized_target: str,
) -> tuple[ScopedInstruction | None, list[ScopedInstructionWarning]]:
    warnings: list[ScopedInstructionWarning] = []
    for filename in SCOPED_INSTRUCTION_FILENAMES:
        relative_path = (directory.relative_to(root) / filename).as_posix()
        if relative_path == normalized_target:
            continue
        collector_warnings = _WarningCollector(limit=8)
        candidate = RepositorySummaryDocument(relative_path, "project_instruction")
        resolved = _resolve_document(root, candidate, collector_warnings, _document_source_key(relative_path))
        if resolved is None:
            warnings.extend(_convert_collector_warnings(collector_warnings, relative_path, filename))
            continue
        if isinstance(resolved, _SkippedDocument):
            warnings.extend(_convert_collector_warnings(collector_warnings, resolved.relative_path, filename, fallback_reason=resolved.skip_reason))
            continue
        if isinstance(resolved, _ResolvedDocument) and not resolved.absolute_path.exists():
            continue
        document = _read_document(root, resolved, limits, 0, collector_warnings)
        if not isinstance(document, _LoadedDocument):
            reason = str(document.skip_reason or "source_skipped")
            warnings.extend(_convert_collector_warnings(collector_warnings, relative_path, filename, fallback_reason=reason))
            continue
        if not document.content.strip():
            warnings.append(_warning("empty_instruction", "Scoped instruction file was empty.", relative_path, filename))
            continue
        warnings.extend(_convert_collector_warnings(collector_warnings, relative_path, filename))
        return _scoped_instruction_from_loaded(document, filename), warnings
    return None, warnings


def _scoped_instruction_from_loaded(document: _LoadedDocument, filename: str) -> ScopedInstruction:
    scope_root = PurePosixPath(document.relative_path).parent.as_posix()
    if scope_root == ".":
        scope_root = ""
    content_digest = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
    return ScopedInstruction(
        source_path=repository_relative_posix_path(document.relative_path),
        scope_root=repository_relative_posix_path(scope_root) if scope_root else "",
        source_kind=filename,  # type: ignore[arg-type]
        content=document.content,
        content_digest=content_digest,
        bytes_consumed=document.bytes_consumed,
        truncated=document.truncated,
    )


def _convert_collector_warnings(
    collector: _WarningCollector,
    source_path: str,
    source_kind: str,
    *,
    fallback_reason: str | None = None,
) -> list[ScopedInstructionWarning]:
    scope_root = PurePosixPath(source_path).parent.as_posix()
    if scope_root == ".":
        scope_root = ""
    converted = [
        _warning(warning.code, warning.message, source_path, source_kind, scope_root=scope_root)
        for warning in collector.items
        if warning.code != "optional_source_missing"
    ]
    if not converted and fallback_reason and fallback_reason != "optional_source_missing":
        converted.append(_warning(fallback_reason, "Scoped instruction candidate was skipped.", source_path, source_kind, scope_root=scope_root))
    return converted


def _warning(code: str, message: str, source_path: str, source_kind: str, *, scope_root: str | None = None) -> ScopedInstructionWarning:
    return ScopedInstructionWarning(
        code=code,
        message=message,
        source_path=repository_relative_posix_path(source_path),
        scope_root=repository_relative_posix_path(scope_root) if scope_root else None,
        source_kind=source_kind,
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
