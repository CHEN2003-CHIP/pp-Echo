from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable, Literal

from pp_agent.coding.repository import RepositoryAnalysis
from pp_agent.coding.repository_summary import (
    RepositorySummary,
    RepositorySummarySection,
    RepositorySummarySource,
    RepositorySummaryWarning,
    SourceKind,
    repository_relative_posix_path,
)
from pp_agent.context.project import PROJECT_MANIFEST_NAMES, ProjectContext


DOCUMENT_WARNING_CODES = {
    "decode_failure",
    "document_count_exceeded",
    "optional_source_missing",
    "outside_root_rejected",
    "read_budget_exceeded",
    "section_truncated",
    "sensitive_source_rejected",
    "symlink_escape_rejected",
    "unsupported_binary",
    "unsupported_text_type",
    "warning_limit_reached",
}
DEFAULT_PROJECT_MAP_PATHS = (".pp-echo/project-map.json",)
SUPPORTED_TEXT_EXTENSIONS = {".md", ".rst", ".txt"}
SENSITIVE_NAME_MARKERS = ("credential", "credentials", "secret", "secrets", "token", "tokens")
SENSITIVE_SUFFIXES = (".key", ".pem")
PROTECTED_PATH_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
    ".ssh",
    ".aws",
    ".azure",
    ".config",
}

DocumentKind = Literal["project_instruction", "project_map", "module_doc"]


@dataclass(frozen=True)
class RepositorySummaryCollectionLimits:
    """Small injectable budgets for bounded repository-summary collection."""

    per_file_bytes: int = 16 * 1024
    total_bytes: int = 64 * 1024
    max_documents: int = 12
    section_bytes: int = 4 * 1024
    max_warnings: int = 20


@dataclass(frozen=True)
class RepositorySummaryDocument:
    """An explicitly approved repository document candidate."""

    path: str | Path
    source_kind: DocumentKind
    required: bool = False


@dataclass(frozen=True)
class _ResolvedDocument:
    relative_path: str
    absolute_path: Path
    source_kind: DocumentKind
    required: bool


@dataclass(frozen=True)
class _SkippedDocument:
    relative_path: str
    source_kind: DocumentKind
    skip_reason: str
    bytes_consumed: int = 0


@dataclass(frozen=True)
class _LoadedDocument:
    relative_path: str
    source_key: str
    source_kind: DocumentKind
    content: str
    bytes_consumed: int
    truncated: bool


class _WarningCollector:
    def __init__(self, limit: int) -> None:
        self._limit = max(0, int(limit))
        self._warnings: list[RepositorySummaryWarning] = []
        self._limit_reached = False

    def add(self, code: str, message: str, *, source_key: str | None = None, severity: Literal["warning", "skipped"] = "warning") -> None:
        if len(self._warnings) < self._limit:
            self._warnings.append(RepositorySummaryWarning(code, message, severity=severity, source_key=source_key))
            return
        if self._limit_reached:
            return
        self._limit_reached = True
        if self._limit > 0:
            self._warnings[-1] = RepositorySummaryWarning("warning_limit_reached", "Additional repository summary warnings were omitted.")

    @property
    def items(self) -> list[RepositorySummaryWarning]:
        return list(self._warnings)


def build_repository_summary(
    *,
    project_context: ProjectContext,
    repository_analysis: RepositoryAnalysis,
    repository_root: Path,
    project_map_paths: Iterable[str | Path] = DEFAULT_PROJECT_MAP_PATHS,
    module_doc_paths: Iterable[str | Path] = (),
    instruction_filenames: Iterable[str] = PROJECT_MANIFEST_NAMES,
    extra_documents: Iterable[RepositorySummaryDocument] = (),
    limits: RepositorySummaryCollectionLimits | None = None,
) -> RepositorySummary:
    """Build a deterministic bounded repository summary from explicit sources."""

    active_limits = limits or RepositorySummaryCollectionLimits()
    warnings = _WarningCollector(active_limits.max_warnings)
    root = repository_root.resolve()
    candidates = _document_candidates(
        instruction_filenames=instruction_filenames,
        project_map_paths=project_map_paths,
        module_doc_paths=module_doc_paths,
        repository_analysis=repository_analysis,
        extra_documents=extra_documents,
    )
    loaded_documents, document_sources = _collect_documents(root, candidates, active_limits, warnings)
    sources = [
        RepositorySummarySource("project-context", "project_context", bytes_consumed=0),
        RepositorySummarySource("repository-analysis", "repository_analysis", bytes_consumed=0),
        *document_sources,
    ]
    sections = _build_sections(project_context, repository_analysis, loaded_documents, active_limits, warnings)
    return RepositorySummary(
        workspace_name=project_context.workspace_name or repository_analysis.workspace_name,
        project_type=repository_analysis.project_type or "unknown",
        sections=sections,
        sources=sources,
        warnings=warnings.items,
    )


def _document_candidates(
    *,
    instruction_filenames: Iterable[str],
    project_map_paths: Iterable[str | Path],
    module_doc_paths: Iterable[str | Path],
    repository_analysis: RepositoryAnalysis,
    extra_documents: Iterable[RepositorySummaryDocument],
) -> list[RepositorySummaryDocument]:
    candidates: list[RepositorySummaryDocument] = []
    for name in sorted({str(name) for name in instruction_filenames}):
        candidates.append(RepositorySummaryDocument(name, "project_instruction"))
    for path in sorted({str(path) for path in project_map_paths}):
        candidates.append(RepositorySummaryDocument(path, "project_map"))
    module_paths = {str(path) for path in module_doc_paths}
    for paths in repository_analysis.module_map.values():
        for module_path in paths:
            module_paths.add(str(PurePosixPath(str(module_path).replace("\\", "/")) / "MODULE.md"))
    for path in sorted(module_paths):
        candidates.append(RepositorySummaryDocument(path, "module_doc"))
    candidates.extend(sorted(extra_documents, key=lambda document: (document.source_kind, str(document.path), document.required)))
    return _dedupe_candidates(candidates)


def _dedupe_candidates(candidates: list[RepositorySummaryDocument]) -> list[RepositorySummaryDocument]:
    by_key: dict[tuple[str, DocumentKind], RepositorySummaryDocument] = {}
    for candidate in candidates:
        raw_path = str(candidate.path).replace("\\", "/")
        key = (raw_path, candidate.source_kind)
        existing = by_key.get(key)
        if existing is None or candidate.required:
            by_key[key] = candidate
    return [by_key[key] for key in sorted(by_key)]


def _collect_documents(
    repository_root: Path,
    candidates: list[RepositorySummaryDocument],
    limits: RepositorySummaryCollectionLimits,
    warnings: _WarningCollector,
) -> tuple[list[_LoadedDocument], list[RepositorySummarySource]]:
    loaded: list[_LoadedDocument] = []
    sources: list[RepositorySummarySource] = []
    total_bytes = 0
    accepted_documents = 0
    for candidate in candidates:
        source_key = _document_source_key(str(candidate.path))
        resolved = _resolve_document(repository_root, candidate, warnings, source_key)
        if resolved is None:
            sources.append(_skipped_source(source_key, candidate.source_kind, _safe_candidate_path(candidate.path), 0, "outside_root_rejected"))
            continue
        if isinstance(resolved, _SkippedDocument):
            source_key = _document_source_key(resolved.relative_path)
            sources.append(_skipped_source(source_key, resolved.source_kind, resolved.relative_path, resolved.bytes_consumed, resolved.skip_reason))
            continue
        source_key = _document_source_key(resolved.relative_path)
        if accepted_documents >= limits.max_documents:
            sources.append(_skipped_source(source_key, resolved.source_kind, resolved.relative_path, 0, "document_count_exceeded"))
            warnings.add("document_count_exceeded", "Approved repository document count budget was exceeded.", source_key=source_key, severity="skipped")
            continue
        document = _read_document(repository_root, resolved, limits, total_bytes, warnings)
        if isinstance(document, RepositorySummarySource):
            sources.append(document)
            continue
        accepted_documents += 1
        total_bytes += document.bytes_consumed
        loaded.append(document)
        sources.append(
            RepositorySummarySource(
                document.source_key,
                document.source_kind,
                path=document.relative_path,
                bytes_consumed=document.bytes_consumed,
                truncated=document.truncated,
            )
        )
    return loaded, sources


def _resolve_document(
    repository_root: Path,
    candidate: RepositorySummaryDocument,
    warnings: _WarningCollector,
    source_key: str,
) -> _ResolvedDocument | _SkippedDocument | None:
    raw_path = str(candidate.path)
    if _is_forbidden_path_syntax(raw_path):
        warnings.add("outside_root_rejected", "Repository summary source path was outside the repository root.", source_key=source_key, severity="skipped")
        return None
    try:
        relative_path = repository_relative_posix_path(raw_path)
    except ValueError:
        warnings.add("outside_root_rejected", "Repository summary source path was outside the repository root.", source_key=source_key, severity="skipped")
        return None
    if _is_sensitive_or_protected(relative_path):
        warnings.add("sensitive_source_rejected", "Repository summary source path was rejected before reading.", source_key=_document_source_key(relative_path), severity="skipped")
        return _ResolvedDocument(relative_path, repository_root / relative_path, candidate.source_kind, candidate.required)
    path = repository_root / PurePosixPath(relative_path)
    if not path.exists():
        warnings.add("optional_source_missing", "Optional repository summary source was missing.", source_key=_document_source_key(relative_path), severity="skipped")
        return _ResolvedDocument(relative_path, path, candidate.source_kind, candidate.required)
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        warnings.add("outside_root_rejected", "Repository summary source path could not be resolved safely.", source_key=_document_source_key(relative_path), severity="skipped")
        return _SkippedDocument(relative_path, candidate.source_kind, "outside_root_rejected")
    if not _is_relative_to(resolved, repository_root):
        warnings.add("symlink_escape_rejected", "Repository summary source symlink escaped the repository root.", source_key=_document_source_key(relative_path), severity="skipped")
        return _SkippedDocument(relative_path, candidate.source_kind, "symlink_escape_rejected")
    return _ResolvedDocument(relative_path, resolved, candidate.source_kind, candidate.required)


def _read_document(
    repository_root: Path,
    document: _ResolvedDocument,
    limits: RepositorySummaryCollectionLimits,
    total_bytes: int,
    warnings: _WarningCollector,
) -> _LoadedDocument | RepositorySummarySource:
    source_key = _document_source_key(document.relative_path)
    if _is_sensitive_or_protected(document.relative_path):
        return _skipped_source(source_key, document.source_kind, document.relative_path, 0, "sensitive_source_rejected")
    if not document.absolute_path.exists():
        return _skipped_source(source_key, document.source_kind, document.relative_path, 0, "optional_source_missing")
    if document.absolute_path.is_dir() or not _is_supported_text_path(document.relative_path):
        warnings.add("unsupported_text_type", "Repository summary source was not an approved text document type.", source_key=source_key, severity="skipped")
        return _skipped_source(source_key, document.source_kind, document.relative_path, 0, "unsupported_text_type")
    remaining_total = max(0, limits.total_bytes - total_bytes)
    read_limit = min(limits.per_file_bytes, remaining_total)
    if read_limit <= 0:
        warnings.add("read_budget_exceeded", "Repository summary document read budget was exhausted.", source_key=source_key, severity="skipped")
        return _skipped_source(source_key, document.source_kind, document.relative_path, 0, "read_budget_exceeded")
    try:
        with document.absolute_path.open("rb") as handle:
            raw = handle.read(read_limit + 1)
    except OSError:
        warnings.add("outside_root_rejected", "Repository summary source could not be read safely.", source_key=source_key, severity="skipped")
        return _skipped_source(source_key, document.source_kind, document.relative_path, 0, "outside_root_rejected")
    truncated = len(raw) > read_limit
    bounded = raw[:read_limit]
    bytes_consumed = len(bounded)
    if b"\x00" in bounded:
        warnings.add("unsupported_binary", "Repository summary source looked like binary content.", source_key=source_key, severity="skipped")
        return _skipped_source(source_key, document.source_kind, document.relative_path, bytes_consumed, "unsupported_binary")
    try:
        content = bounded.decode("utf-8-sig")
    except UnicodeDecodeError:
        warnings.add("decode_failure", "Repository summary source could not be decoded as UTF-8.", source_key=source_key, severity="skipped")
        return _skipped_source(source_key, document.source_kind, document.relative_path, bytes_consumed, "decode_failure")
    if truncated:
        warnings.add("read_budget_exceeded", "Repository summary source was truncated by the read budget.", source_key=source_key)
    if not _is_relative_to(document.absolute_path.resolve(strict=False), repository_root):
        warnings.add("symlink_escape_rejected", "Repository summary source symlink escaped the repository root.", source_key=source_key, severity="skipped")
        return _skipped_source(source_key, document.source_kind, document.relative_path, 0, "symlink_escape_rejected")
    return _LoadedDocument(document.relative_path, source_key, document.source_kind, content, bytes_consumed, truncated)


def _build_sections(
    project_context: ProjectContext,
    repository_analysis: RepositoryAnalysis,
    documents: list[_LoadedDocument],
    limits: RepositorySummaryCollectionLimits,
    warnings: _WarningCollector,
) -> list[RepositorySummarySection]:
    sections = [
        RepositorySummarySection(
            "project_metadata",
            "Project metadata",
            "project_context",
            {
                "workspace_name": project_context.workspace_name,
                "languages": sorted(project_context.detected_languages),
                "frameworks": sorted(project_context.detected_frameworks),
                "important_paths": sorted(project_context.important_paths),
                "manifest_files": sorted(project_context.manifest_files),
            },
            ["project-context"],
        ),
        RepositorySummarySection(
            "repository_structure",
            "Repository structure",
            "repository_analysis",
            {
                "source_roots": sorted(repository_analysis.source_roots),
                "test_roots": sorted(repository_analysis.test_roots),
                "doc_roots": sorted(repository_analysis.doc_roots),
                "frontend_roots": sorted(repository_analysis.frontend_roots),
                "backend_roots": sorted(repository_analysis.backend_roots),
                "config_files": sorted(repository_analysis.config_files),
                "ci_files": sorted(repository_analysis.ci_files),
                "entry_points": sorted(repository_analysis.entry_points),
                "module_map": {key: sorted(value) for key, value in sorted(repository_analysis.module_map.items())},
            },
            ["repository-analysis"],
        ),
    ]
    if repository_analysis.likely_test_commands or project_context.likely_test_commands:
        sections.append(
            RepositorySummarySection(
                "test_commands",
                "Test commands",
                "test_command",
                sorted({*project_context.likely_test_commands, *repository_analysis.likely_test_commands}),
                ["project-context", "repository-analysis"],
            )
        )
    if project_context.warnings or repository_analysis.warnings:
        sections.append(
            RepositorySummarySection(
                "known_warnings",
                "Known warnings",
                "warnings",
                sorted({*project_context.warnings, *repository_analysis.warnings}),
                ["project-context", "repository-analysis"],
            )
        )
    for document in sorted(documents, key=lambda item: (item.source_kind, item.relative_path)):
        content, truncated = _truncate_text_by_utf8_bytes(document.content, limits.section_bytes)
        if truncated:
            warnings.add("section_truncated", "Repository summary section content was truncated.", source_key=document.source_key)
        sections.append(
            RepositorySummarySection(
                _document_section_key(document),
                _document_title(document),
                document.source_kind,
                content,
                [document.source_key],
                truncated=truncated or document.truncated,
            )
        )
    return sections


def _truncate_text_by_utf8_bytes(text: str, limit: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    bounded = encoded[: max(0, limit)]
    return bounded.decode("utf-8", errors="ignore"), True


def _document_source_key(path: str) -> str:
    try:
        safe = repository_relative_posix_path(path).replace("/", ":")
    except ValueError:
        safe = "invalid"
    return f"document:{safe}"


def _document_section_key(document: _LoadedDocument) -> str:
    prefix = {
        "project_instruction": "project_instruction",
        "project_map": "project_map",
        "module_doc": "module_doc",
    }[document.source_kind]
    return f"{prefix}:{document.relative_path.replace('/', ':')}"


def _document_title(document: _LoadedDocument) -> str:
    label = {
        "project_instruction": "Project instruction",
        "project_map": "Project map",
        "module_doc": "Module guidance",
    }[document.source_kind]
    return f"{label}: {document.relative_path}"


def _safe_candidate_path(path: str | Path) -> str | None:
    try:
        return repository_relative_posix_path(str(path))
    except ValueError:
        return None


def _skipped_source(source_key: str, source_kind: SourceKind, path: str | None, bytes_consumed: int, reason: str) -> RepositorySummarySource:
    return RepositorySummarySource(
        source_key,
        source_kind,
        path=path,
        bytes_consumed=bytes_consumed,
        skipped=True,
        skip_reason=reason,
    )


def _is_supported_text_path(path: str) -> bool:
    normalized = PurePosixPath(path)
    if normalized.suffix.lower() in SUPPORTED_TEXT_EXTENSIONS:
        return True
    return normalized.name in PROJECT_MANIFEST_NAMES or path == ".pp-echo/project-map.json"


def _is_sensitive_or_protected(path: str) -> bool:
    normalized = repository_relative_posix_path(path).lower()
    parts = normalized.split("/")
    if any(part in PROTECTED_PATH_PARTS for part in parts):
        return True
    name = parts[-1]
    if name == ".env" or name.startswith(".env."):
        return True
    if name.endswith(SENSITIVE_SUFFIXES):
        return True
    return any(marker in normalized for marker in SENSITIVE_NAME_MARKERS)


def _is_forbidden_path_syntax(path: str) -> bool:
    if path.startswith("\\\\") or path.startswith("//"):
        return True
    windows_path = PureWindowsPath(path)
    if windows_path.drive:
        return True
    posix_path = PurePosixPath(path.replace("\\", "/"))
    return posix_path.is_absolute()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
