from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Any, Iterable

from pp_agent.coding.planner import TaskPlan
from pp_agent.coding.repository import RepositoryAnalysis
from pp_agent.context.item import ContextItem
from pp_agent.context.project import ProjectContext
from pp_agent.context.source_ref import SourceRef

DEFAULT_DISALLOWED_PATHS = (
    ".env",
    ".env.*",
    ".git/**",
    ".pp-agent/**",
    "*.pem",
    "*.key",
    "node_modules/**",
    "__pycache__/**",
    ".pytest_cache/**",
    "dist/**",
    "build/**",
)


@dataclass
class TaskScope:
    """A task-level authorization boundary for future ToolPolicy and patch enforcement."""

    task: str
    allowed_paths: list[str] = field(default_factory=list)
    disallowed_paths: list[str] = field(default_factory=list)
    allow_edit: bool = True
    allow_shell: bool = True
    allow_delete: bool = False
    allow_network: bool = False
    max_files_changed: int | None = None
    risk_level: str = "unknown"
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    summary_text: str = ""


@dataclass
class ScopeCheckResult:
    """A single task-scope decision for future ToolPolicy, structured changes, and Web/TUI display."""

    allowed: bool
    action: str
    path: str | None
    reason: str
    matched_rule: str | None = None
    risk_level: str | None = None


def build_task_scope(
    plan: TaskPlan,
    repository_analysis: RepositoryAnalysis | None = None,
    project_context: ProjectContext | None = None,
) -> TaskScope:
    """Build a rule-based task scope contract without changing sandbox or approval behavior."""

    warnings = list(plan.warnings)
    if repository_analysis is None:
        warnings.append("RepositoryAnalysis was not provided; scope uses conservative plan-derived paths.")
    if project_context is None:
        warnings.append("ProjectContext was not provided; scope reason omits project bootstrap context.")
    if plan.risk_level == "unknown":
        warnings.append("Task scope is conservative because the task category is unknown.")

    allowed_paths = _allowed_paths_from_plan(plan, repository_analysis, warnings)
    risk_level = _scope_risk(plan)
    allow_edit = not _is_read_only_plan(plan)
    max_files_changed = _max_files_changed(plan, risk_level)
    scope = TaskScope(
        task=plan.task,
        allowed_paths=allowed_paths,
        disallowed_paths=list(DEFAULT_DISALLOWED_PATHS),
        allow_edit=allow_edit,
        allow_shell=True,
        allow_delete=False,
        allow_network=False,
        max_files_changed=max_files_changed,
        risk_level=risk_level,
        reason=_reason(plan, allowed_paths),
        warnings=_unique(warnings),
    )
    scope.summary_text = _render_summary_text(scope)
    return scope


def check_path_in_scope(scope: TaskScope, path: str | None, action: str = "edit") -> ScopeCheckResult:
    """Check one path/action against a task-level scope contract before future enforcement."""

    normalized, error = _normalize_path(path)
    if error:
        return ScopeCheckResult(False, action, path, error, risk_level=scope.risk_level)
    assert normalized is not None

    disallowed = _matched_rule(normalized, scope.disallowed_paths)
    if disallowed:
        return ScopeCheckResult(False, action, normalized, "Path is explicitly disallowed by task scope.", disallowed, scope.risk_level)

    action_allowed, reason = _action_allowed(scope, action)
    if not action_allowed:
        return ScopeCheckResult(False, action, normalized, reason, risk_level=scope.risk_level)

    if action == "read":
        return ScopeCheckResult(True, action, normalized, "Read is allowed outside explicit write scope unless path is disallowed.", risk_level=scope.risk_level)

    if not scope.allowed_paths:
        return ScopeCheckResult(False, action, normalized, "No allowed paths are defined for write-like actions.", risk_level=scope.risk_level)

    allowed = _matched_rule(normalized, scope.allowed_paths)
    if not allowed:
        return ScopeCheckResult(False, action, normalized, "Path is outside allowed task scope.", risk_level=scope.risk_level)
    return ScopeCheckResult(True, action, normalized, "Path is within allowed task scope.", allowed, scope.risk_level)


def check_structured_changes_in_scope(scope: TaskScope, structured_changes: list[Any]) -> ScopeCheckResult:
    """Check structured file changes against TaskScope before future apply_patch_candidate enforcement."""

    paths: list[str] = []
    for change in structured_changes or []:
        path = _change_path(change)
        action = "delete" if _change_is_delete(change) else "edit"
        result = check_path_in_scope(scope, path, action=action)
        if not result.allowed:
            return result
        if result.path:
            paths.append(result.path)
    changed_count = len(set(paths))
    if scope.max_files_changed is not None and changed_count > scope.max_files_changed:
        return ScopeCheckResult(
            False,
            "apply_patch",
            None,
            f"Structured changes touch {changed_count} files, exceeding scope limit {scope.max_files_changed}.",
            "max_files_changed",
            scope.risk_level,
        )
    return ScopeCheckResult(True, "apply_patch", None, "Structured changes are within task scope.", risk_level=scope.risk_level)


def task_scope_to_context_item(scope: TaskScope, *, id: str = "task-scope") -> ContextItem:
    """Convert TaskScope into context for later ToolPolicy or ExecutionOrchestrator phases."""

    return ContextItem(
        id=id,
        type="project_context",
        title="Task scope",
        content=scope.summary_text,
        source_ref=SourceRef(source_type="project_context", source_id="task_scope", metadata=task_scope_to_dict(scope)),
        priority=57,
        metadata={"context_section": "project_context", "task_scope": task_scope_to_dict(scope)},
    )


def task_scope_to_dict(scope: TaskScope) -> dict[str, object]:
    """Return a JSON-friendly TaskScope payload for Web/TUI timeline and future enforcement."""

    return {
        "task": scope.task,
        "allowed_paths": list(scope.allowed_paths),
        "disallowed_paths": list(scope.disallowed_paths),
        "allow_edit": scope.allow_edit,
        "allow_shell": scope.allow_shell,
        "allow_delete": scope.allow_delete,
        "allow_network": scope.allow_network,
        "max_files_changed": scope.max_files_changed,
        "risk_level": scope.risk_level,
        "reason": scope.reason,
        "warnings": list(scope.warnings),
    }


def task_scope_to_write_scope(scope: TaskScope):
    """Adapt TaskScope to the runtime WriteScope contract without making runtime import coding.

    WriteScope is the minimal apply-path boundary consumed by tools; it does not replace TaskScope,
    approval, or sandbox enforcement.
    """

    from pp_agent.runtime.scope_contract import WriteScope

    return WriteScope(
        allowed_paths=list(scope.allowed_paths),
        disallowed_paths=list(scope.disallowed_paths),
        allow_delete=scope.allow_delete,
        max_files_changed=scope.max_files_changed,
        risk_level=scope.risk_level,
        source="task_scope",
    )


def _allowed_paths_from_plan(plan: TaskPlan, analysis: RepositoryAnalysis | None, warnings: list[str]) -> list[str]:
    task_text = plan.task.lower()
    candidates = [*plan.likely_files_to_change, *plan.files_to_inspect]
    if _is_docs_plan(plan):
        candidates.extend(["docs/**", "README.md"])
    if any(keyword in task_text for keyword in ("web", "frontend", "ui")):
        candidates.append("web/**")
    if plan.risk_level == "unknown" and not candidates:
        if analysis is not None:
            candidates.extend(analysis.source_roots[:3])
        warnings.append("Task scope is conservative because the task category is unknown.")
    return _unique(_scope_pattern(path) for path in candidates if path)


def _scope_pattern(path: str) -> str:
    normalized = path.strip().replace("\\", "/").rstrip("/")
    if not normalized:
        return ""
    if normalized.endswith("/**") or "*" in normalized:
        return normalized
    if normalized.endswith("/"):
        return f"{normalized}**"
    suffix = PurePosixPath(normalized).suffix
    if suffix:
        return normalized
    return f"{normalized}/**"


def _normalize_path(path: str | None) -> tuple[str | None, str | None]:
    if path is None or not str(path).strip():
        return None, "Path is required for this scope check."
    raw = str(path).strip().replace("\\", "/")
    if raw.startswith("//"):
        return None, "UNC paths are outside task scope."
    if raw.startswith("/") or raw.startswith("\\"):
        return None, "Absolute paths are outside task scope."
    if len(raw) >= 2 and raw[1] == ":":
        return None, "Drive-qualified paths are outside task scope."
    parts = PurePosixPath(raw).parts
    if ".." in parts:
        return None, "Parent traversal is outside task scope."
    return "/".join(parts), None


def _matched_rule(path: str, patterns: Iterable[str]) -> str | None:
    for pattern in patterns:
        candidate = pattern.replace("\\", "/")
        if fnmatchcase(path, candidate):
            return candidate
        if candidate.endswith("/**") and (path == candidate[:-3].rstrip("/") or path.startswith(candidate[:-2])):
            return candidate
    return None


def _action_allowed(scope: TaskScope, action: str) -> tuple[bool, str]:
    if action in {"edit", "apply_patch"} and not scope.allow_edit:
        return False, "Edit-like actions are denied by task scope."
    if action == "delete" and not scope.allow_delete:
        return False, "Delete is denied by task scope."
    if action == "shell" and not scope.allow_shell:
        return False, "Shell is denied by task scope."
    if action == "network" and not scope.allow_network:
        return False, "Network is denied by task scope."
    return True, "Action is allowed by task scope flags."


def _change_path(change: Any) -> str | None:
    if isinstance(change, dict):
        return str(change.get("path") or "") or None
    return str(getattr(change, "path", "") or "") or None


def _change_is_delete(change: Any) -> bool:
    if isinstance(change, dict):
        raw = str(change.get("change_type") or change.get("operation") or change.get("status") or "").lower()
    else:
        raw = str(getattr(change, "change_type", "") or getattr(change, "operation", "") or getattr(change, "status", "")).lower()
    return raw in {"delete", "deleted", "removed"}


def _scope_risk(plan: TaskPlan) -> str:
    text = plan.task.lower()
    if plan.risk_level == "high" or any(keyword in text for keyword in ("approval", "policy", "sandbox", "network", "security")):
        return "high"
    return plan.risk_level


def _max_files_changed(plan: TaskPlan, risk_level: str) -> int | None:
    if _is_docs_plan(plan) or _is_tests_only_plan(plan):
        return 10
    return {"low": 4, "medium": 8, "high": 4, "unknown": 2}.get(risk_level)


def _is_docs_plan(plan: TaskPlan) -> bool:
    text = plan.task.lower()
    return plan.risk_level == "low" or "docs" in text or "readme" in text


def _is_tests_only_plan(plan: TaskPlan) -> bool:
    return bool(plan.files_to_inspect) and all(path.startswith("tests") for path in plan.files_to_inspect)


def _is_read_only_plan(plan: TaskPlan) -> bool:
    text = plan.task.lower()
    return any(keyword in text for keyword in ("read-only", "readonly", "inspect only", "analyze only", "plan only"))


def _reason(plan: TaskPlan, allowed_paths: list[str]) -> str:
    if allowed_paths:
        return "Scope was derived from TaskPlan files_to_inspect and likely_files_to_change."
    return "Scope has no write paths because the TaskPlan did not identify safe task-local files."


def _render_summary_text(scope: TaskScope) -> str:
    lines = [
        "Task Scope:",
        f"- Task: {scope.task}",
        "- Allowed paths:",
    ]
    lines.extend(f"  - {path}" for path in scope.allowed_paths) if scope.allowed_paths else lines.append("  - None")
    lines.append("- Disallowed paths:")
    lines.extend(f"  - {path}" for path in scope.disallowed_paths[:6])
    lines.extend(
        [
            "- Permissions:",
            f"  - edit: {'allowed' if scope.allow_edit else 'denied'}",
            f"  - shell: {'allowed with existing approval/policy' if scope.allow_shell else 'denied'}",
            f"  - delete: {'allowed' if scope.allow_delete else 'denied'}",
            f"  - network: {'allowed' if scope.allow_network else 'denied'}",
            f"- Max files changed: {scope.max_files_changed if scope.max_files_changed is not None else 'unlimited'}",
            f"- Risk: {scope.risk_level}",
        ]
    )
    if scope.warnings:
        lines.append("- Warnings:")
        lines.extend(f"  - {warning}" for warning in scope.warnings)
    return "\n".join(lines).strip()


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique
