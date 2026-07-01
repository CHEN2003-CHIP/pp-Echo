from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pp_agent.coding.scope import TaskScope, check_path_in_scope, check_structured_changes_in_scope


@dataclass
class ScopeEnforcementResult:
    """A task-level scope enforcement result for apply_patch_candidate, ToolPolicy, and Web/TUI surfaces.

    This is not sandbox enforcement and it is not approval policy. It reuses TaskScope as a task-level
    boundary. `allowed=None` means legacy or skipped flow where no TaskScope was provided.
    """

    allowed: bool | None
    action: str
    reason: str
    risk_level: str | None = None
    failed_path: str | None = None
    matched_rule: str | None = None
    checked_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary_text: str = ""


def enforce_structured_changes_scope(
    scope: TaskScope | None,
    structured_changes: list[Any],
    action: str = "apply_patch",
) -> ScopeEnforcementResult:
    """Check structured changes against TaskScope without replacing sandbox or approval behavior.

    When no TaskScope is provided, `allowed=None` preserves legacy apply_patch_candidate behavior and
    records that scope enforcement was skipped.
    """

    checked_paths = _structured_change_paths(structured_changes)
    if scope is None:
        return _with_summary(
            ScopeEnforcementResult(
                allowed=None,
                action=action,
                reason="No task scope was provided; scope enforcement was not applied.",
                checked_paths=checked_paths,
                warnings=["Scope enforcement skipped."],
            )
        )
    result = check_structured_changes_in_scope(scope, structured_changes)
    return _with_summary(
        ScopeEnforcementResult(
            allowed=result.allowed,
            action=action,
            reason=result.reason,
            risk_level=result.risk_level,
            failed_path=result.path if not result.allowed else None,
            matched_rule=result.matched_rule,
            checked_paths=checked_paths,
            warnings=[],
        )
    )


def enforce_path_scope(scope: TaskScope | None, path: str | None, action: str) -> ScopeEnforcementResult:
    """Check one path/action against TaskScope for future ToolPolicy and file operation hooks.

    This helper is task-level enforcement only. It skips with `allowed=None` when legacy callers do not
    provide TaskScope, and it does not invoke sandbox or approval systems.
    """

    checked_paths = [path] if path else []
    if scope is None:
        return _with_summary(
            ScopeEnforcementResult(
                allowed=None,
                action=action or "unknown",
                reason="No task scope was provided; scope enforcement was not applied.",
                checked_paths=checked_paths,
                warnings=["Scope enforcement skipped."],
            )
        )
    result = check_path_in_scope(scope, path, action=action)
    return _with_summary(
        ScopeEnforcementResult(
            allowed=result.allowed,
            action=action or "unknown",
            reason=result.reason,
            risk_level=result.risk_level,
            failed_path=result.path if not result.allowed else None,
            matched_rule=result.matched_rule,
            checked_paths=checked_paths,
            warnings=[],
        )
    )


def scope_enforcement_to_context_item(result: ScopeEnforcementResult) -> dict[str, Any]:
    """Convert scope enforcement into a JSON-friendly context item for future orchestration.

    The item can be attached to apply_patch_candidate, ToolPolicy, or Web/TUI details without changing
    sandbox or approval semantics.
    """

    details = scope_enforcement_to_details(result)
    return {
        "id": "scope-enforcement",
        "type": "project_context",
        "title": "Scope enforcement",
        "content": result.summary_text,
        "source_ref": {"source_type": "project_context", "source_id": "scope_enforcement", "metadata": details},
        "priority": 53,
        "metadata": {"context_section": "project_context", "scope_enforcement": details},
    }


def scope_enforcement_to_details(result: ScopeEnforcementResult) -> dict[str, Any]:
    """Return JSON-friendly scope enforcement details for approvals and timeline blocks."""

    return {
        "allowed": result.allowed,
        "action": result.action,
        "reason": result.reason,
        "risk_level": result.risk_level,
        "failed_path": result.failed_path,
        "matched_rule": result.matched_rule,
        "checked_paths": list(result.checked_paths),
        "warnings": list(result.warnings),
        "summary_text": result.summary_text,
    }


def _structured_change_paths(structured_changes: list[Any]) -> list[str]:
    paths: list[str] = []
    for change in structured_changes or []:
        path = None
        if isinstance(change, dict):
            path = change.get("path")
        else:
            path = getattr(change, "path", None)
        item = str(path or "").strip().replace("\\", "/")
        if item:
            paths.append(item)
    return _unique(paths)


def _with_summary(result: ScopeEnforcementResult) -> ScopeEnforcementResult:
    result.summary_text = _render_summary_text(result)
    return result


def _render_summary_text(result: ScopeEnforcementResult) -> str:
    state = "skipped" if result.allowed is None else "allowed" if result.allowed else "blocked"
    lines = [
        "Scope Enforcement:",
        f"- Action: {result.action}",
        f"- Result: {state}",
    ]
    if result.checked_paths:
        lines.append("- Checked paths:")
        lines.extend(f"  - {path}" for path in result.checked_paths)
    if result.failed_path:
        lines.append(f"- Failed path: {result.failed_path}")
    if result.matched_rule:
        lines.append(f"- Matched rule: {result.matched_rule}")
    lines.append(f"- Reason: {result.reason}")
    if result.risk_level:
        lines.append(f"- Risk: {result.risk_level}")
    if result.warnings:
        lines.append("- Warnings:")
        lines.extend(f"  - {warning}" for warning in result.warnings)
    return "\n".join(lines).strip()


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
