from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Any, Mapping


@dataclass
class WriteScope:
    """A minimal runtime/apply-path write boundary that keeps tools from depending on coding.

    WriteScope is not a full TaskScope replacement, approval policy, or sandbox. It is the
    JSON-friendly contract consumed by apply paths. Legacy flows without a WriteScope are skipped.
    """

    allowed_paths: list[str] = field(default_factory=list)
    disallowed_paths: list[str] = field(default_factory=list)
    allow_delete: bool = False
    max_files_changed: int | None = None
    risk_level: str | None = None
    source: str | None = None


@dataclass
class WriteScopeCheckResult:
    """A runtime write-scope decision for apply paths.

    `allowed=True` means checked and allowed, `False` means checked and blocked, and `None`
    means no WriteScope was provided so legacy behavior can continue.
    """

    allowed: bool | None
    reason: str
    failed_path: str | None = None
    matched_rule: str | None = None
    checked_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def write_scope_to_dict(scope: WriteScope) -> dict[str, Any]:
    """Serialize WriteScope for pending action payloads without importing coding contracts."""

    return {
        "allowed_paths": list(scope.allowed_paths),
        "disallowed_paths": list(scope.disallowed_paths),
        "allow_delete": bool(scope.allow_delete),
        "max_files_changed": scope.max_files_changed,
        "risk_level": scope.risk_level,
        "source": scope.source,
    }


def write_scope_from_dict(data: Mapping[str, Any] | None) -> WriteScope | None:
    """Deserialize a JSON-friendly WriteScope, returning None for legacy/skipped flows."""

    if data is None or not isinstance(data, Mapping):
        return None
    return WriteScope(
        allowed_paths=_list_of_strings(data.get("allowed_paths")),
        disallowed_paths=_list_of_strings(data.get("disallowed_paths")),
        allow_delete=bool(data.get("allow_delete")),
        max_files_changed=_int_or_none(data.get("max_files_changed")),
        risk_level=_string_or_none(data.get("risk_level")),
        source=_string_or_none(data.get("source")),
    )


def write_scope_check_to_dict(result: WriteScopeCheckResult) -> dict[str, Any]:
    """Serialize a WriteScopeCheckResult for approval details, traces, and Web/TUI."""

    return {
        "allowed": result.allowed,
        "reason": result.reason,
        "failed_path": result.failed_path,
        "matched_rule": result.matched_rule,
        "checked_paths": list(result.checked_paths),
        "warnings": list(result.warnings),
    }


def check_path_against_write_scope(scope: WriteScope | None, path: str, action: str = "edit") -> WriteScopeCheckResult:
    """Check one path against the runtime WriteScope before workspace writes.

    This contract sits in runtime so tools can consume it without a tools -> coding dependency.
    It does not replace approval, sandbox, or TaskScope.
    """

    if scope is None:
        return WriteScopeCheckResult(
            allowed=None,
            reason="No write scope was provided; scope check was skipped.",
            checked_paths=[str(path)] if str(path or "").strip() else [],
            warnings=["Write scope check skipped."],
        )
    normalized, error = _normalize_path(path)
    if error:
        return WriteScopeCheckResult(False, error, failed_path=path, checked_paths=[str(path)] if path else [])
    assert normalized is not None
    disallowed = _matched_rule(normalized, scope.disallowed_paths)
    if disallowed:
        return WriteScopeCheckResult(False, "Path is explicitly disallowed by write scope.", normalized, disallowed, [normalized])
    if action == "delete" and not scope.allow_delete:
        return WriteScopeCheckResult(False, "Delete is denied by write scope.", normalized, None, [normalized])
    if not scope.allowed_paths:
        return WriteScopeCheckResult(False, "No allowed paths are defined by write scope.", normalized, None, [normalized])
    allowed = _matched_rule(normalized, scope.allowed_paths)
    if not allowed:
        return WriteScopeCheckResult(False, "Path is outside allowed write scope.", normalized, None, [normalized])
    return WriteScopeCheckResult(True, "Path is within write scope.", checked_paths=[normalized], matched_rule=allowed)


def check_structured_changes_against_write_scope(scope: WriteScope | None, structured_changes: list[Any]) -> WriteScopeCheckResult:
    """Check structured changes against WriteScope before apply_patch_candidate writes.

    The check reads no file contents and leaves binary/truncated handling to existing apply logic.
    """

    paths = _structured_change_paths(structured_changes)
    if scope is None:
        return WriteScopeCheckResult(
            allowed=None,
            reason="No write scope was provided; scope check was skipped.",
            checked_paths=paths,
            warnings=["Write scope check skipped."],
        )
    for change in structured_changes or []:
        path = _change_path(change)
        action = "delete" if _change_is_delete(change) else "edit"
        result = check_path_against_write_scope(scope, path or "", action=action)
        if result.allowed is False:
            result.checked_paths = paths
            return result
    changed_count = len(set(paths))
    if scope.max_files_changed is not None and changed_count > scope.max_files_changed:
        return WriteScopeCheckResult(
            False,
            f"Structured changes touch {changed_count} files, exceeding write scope limit {scope.max_files_changed}.",
            matched_rule="max_files_changed",
            checked_paths=paths,
        )
    return WriteScopeCheckResult(True, "Structured changes are within write scope.", checked_paths=paths)


def _normalize_path(path: str | None) -> tuple[str | None, str | None]:
    raw = str(path or "").strip().replace("\\", "/")
    if not raw:
        return None, "Path is required for write scope check."
    if raw.startswith("//"):
        return None, "UNC paths are outside write scope."
    if raw.startswith("/") or raw.startswith("\\"):
        return None, "Absolute paths are outside write scope."
    if len(raw) >= 2 and raw[1] == ":":
        return None, "Drive-qualified paths are outside write scope."
    parts = PurePosixPath(raw).parts
    if ".." in parts:
        return None, "Parent traversal is outside write scope."
    return "/".join(parts), None


def _matched_rule(path: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        candidate = pattern.replace("\\", "/")
        if fnmatchcase(path, candidate):
            return candidate
        if candidate.endswith("/**") and (path == candidate[:-3].rstrip("/") or path.startswith(candidate[:-2])):
            return candidate
    return None


def _structured_change_paths(structured_changes: list[Any]) -> list[str]:
    return _unique([str(_change_path(change) or "").replace("\\", "/") for change in structured_changes or []])


def _change_path(change: Any) -> str | None:
    if is_dataclass(change):
        change = asdict(change)
    if isinstance(change, Mapping):
        return str(change.get("path") or "") or None
    return str(getattr(change, "path", "") or "") or None


def _change_is_delete(change: Any) -> bool:
    if is_dataclass(change):
        change = asdict(change)
    if isinstance(change, Mapping):
        raw = str(change.get("change_type") or change.get("operation") or change.get("status") or "").lower()
    else:
        raw = str(getattr(change, "change_type", "") or getattr(change, "operation", "") or getattr(change, "status", "")).lower()
    return raw in {"delete", "deleted", "removed"}


def _list_of_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return []


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique
