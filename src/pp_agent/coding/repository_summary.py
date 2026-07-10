from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


REPOSITORY_SUMMARY_SCHEMA_VERSION = "repository_summary.v1"

SourceKind = Literal["project_context", "repository_analysis", "project_instruction", "project_map", "module_doc", "entrypoint", "test_command", "manual"]
WarningSeverity = Literal["warning", "skipped"]


@dataclass
class RepositorySummarySource:
    """A bounded repository-summary source reference with no filesystem access."""

    source_key: str
    source_kind: SourceKind
    path: str | None = None
    symbol: str | None = None
    bytes_consumed: int = 0
    truncated: bool = False
    skipped: bool = False
    skip_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-friendly source payload."""

        payload: dict[str, object] = {
            "source_key": _required_text(self.source_key, "source_key"),
            "source_kind": self.source_kind,
            "bytes_consumed": _non_negative_int(self.bytes_consumed, "bytes_consumed"),
            "truncated": bool(self.truncated),
            "skipped": bool(self.skipped),
        }
        if self.path is not None:
            payload["path"] = repository_relative_posix_path(self.path)
        if self.symbol:
            payload["symbol"] = str(self.symbol)
        if self.skip_reason:
            payload["skip_reason"] = str(self.skip_reason)
        return payload


@dataclass
class RepositorySummarySection:
    """A small deterministic section in a repository summary."""

    section_key: str
    title: str
    kind: str
    content: str | list[str] | dict[str, object] = ""
    source_keys: list[str] = field(default_factory=list)
    truncated: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-friendly section payload."""

        return {
            "section_key": _required_text(self.section_key, "section_key"),
            "title": _required_text(self.title, "title"),
            "kind": _required_text(self.kind, "kind"),
            "content": _json_friendly_content(self.content),
            "source_keys": sorted({_required_text(key, "source_keys") for key in self.source_keys}),
            "truncated": bool(self.truncated),
        }


@dataclass
class RepositorySummaryWarning:
    """A stable repository-summary warning or skipped-source notice."""

    code: str
    message: str
    severity: WarningSeverity = "warning"
    source_key: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-friendly warning payload."""

        payload: dict[str, object] = {
            "code": _required_text(self.code, "code"),
            "severity": self.severity,
            "message": _required_text(self.message, "message"),
        }
        if self.source_key:
            payload["source_key"] = str(self.source_key)
        return payload


@dataclass
class RepositorySummary:
    """A deterministic repository-summary contract for runtime/context use."""

    workspace_name: str
    project_type: str = "unknown"
    sections: list[RepositorySummarySection] = field(default_factory=list)
    sources: list[RepositorySummarySource] = field(default_factory=list)
    warnings: list[RepositorySummaryWarning] = field(default_factory=list)
    schema_version: str = REPOSITORY_SUMMARY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        """Return a canonical JSON-friendly summary payload."""

        return {
            "schema_version": _required_text(self.schema_version, "schema_version"),
            "workspace_name": _required_text(self.workspace_name, "workspace_name"),
            "project_type": _required_text(self.project_type, "project_type"),
            "sections": _canonical_sections(self.sections),
            "sources": _canonical_sources(self.sources),
            "warnings": _canonical_warnings(self.warnings),
        }


def repository_relative_posix_path(path: str) -> str:
    """Normalize a repository-relative path into POSIX form without filesystem access."""

    normalized = _required_text(str(path), "path").replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("//"):
        raise ValueError("repository summary paths must be relative")
    if len(normalized) >= 2 and normalized[1] == ":":
        raise ValueError("repository summary paths must not be drive-qualified")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise ValueError("repository summary paths must not contain parent traversal")
    return "/".join(parts)


def repository_summary_to_dict(summary: RepositorySummary) -> dict[str, object]:
    """Return the canonical JSON-friendly form of a repository summary."""

    return summary.to_dict()


def _canonical_sections(sections: list[RepositorySummarySection]) -> list[dict[str, object]]:
    by_key: dict[str, dict[str, object]] = {}
    for section in sections:
        payload = section.to_dict()
        key = str(payload["section_key"])
        if key in by_key:
            raise ValueError(f"duplicate repository summary section: {key}")
        by_key[key] = payload
    return [by_key[key] for key in sorted(by_key)]


def _canonical_sources(sources: list[RepositorySummarySource]) -> list[dict[str, object]]:
    by_key: dict[str, dict[str, object]] = {}
    for source in sources:
        payload = source.to_dict()
        key = str(payload["source_key"])
        existing = by_key.get(key)
        if existing is not None and existing != payload:
            raise ValueError(f"conflicting repository summary source: {key}")
        by_key[key] = payload
    return [by_key[key] for key in sorted(by_key)]


def _canonical_warnings(warnings: list[RepositorySummaryWarning]) -> list[dict[str, object]]:
    payloads = [warning.to_dict() for warning in warnings]
    return sorted(
        payloads,
        key=lambda item: (
            str(item.get("code", "")),
            str(item.get("source_key", "")),
            str(item.get("severity", "")),
            str(item.get("message", "")),
        ),
    )


def _json_friendly_content(value: str | list[str] | dict[str, object]) -> object:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_scalar_or_sequence(value[key]) for key in sorted(value)}
    raise TypeError("repository summary content must be a string, list of strings, or mapping")


def _json_scalar_or_sequence(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, tuple):
        return [_json_scalar_or_sequence(item) for item in value]
    if isinstance(value, list):
        return [_json_scalar_or_sequence(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_scalar_or_sequence(value[key]) for key in sorted(value)}
    raise TypeError(f"repository summary content is not JSON-friendly: {type(value).__name__}")


def _required_text(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"repository summary {field_name} is required")
    return normalized


def _non_negative_int(value: int, field_name: str) -> int:
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"repository summary {field_name} must be non-negative")
    return normalized
