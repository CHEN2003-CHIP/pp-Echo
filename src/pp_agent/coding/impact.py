from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from pp_agent.coding.planner import TaskPlan
from pp_agent.coding.repository import RepositoryAnalysis
from pp_agent.coding.scope import TaskScope
from pp_agent.context.item import ContextItem
from pp_agent.context.source_ref import SourceRef

MODULE_TESTS = {
    "runtime": ["tests/runtime"],
    "tools": ["tests/tools"],
    "sandbox": ["tests/tools/test_shell_sandbox_executor.py"],
    "observability": ["tests/observability"],
    "context": ["tests/context"],
    "coding": ["tests/coding"],
    "config": ["tests/config"],
    "storage": ["tests/storage"],
    "cli": ["tests/cli"],
    "ci": ["tests"],
}
RISK_ORDER = {"unknown": 0, "low": 1, "medium": 2, "high": 3}


@dataclass
class ChangeImpact:
    """A rule-based changed-path impact summary for future validation and orchestration."""

    changed_paths: list[str] = field(default_factory=list)
    impacted_modules: list[str] = field(default_factory=list)
    impacted_tests: list[str] = field(default_factory=list)
    impacted_docs: list[str] = field(default_factory=list)
    risk_level: str = "unknown"
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    summary_text: str = ""


def analyze_change_impact(
    changed_paths: list[str],
    repository_analysis: RepositoryAnalysis | None = None,
    task_plan: TaskPlan | None = None,
    task_scope: TaskScope | None = None,
) -> ChangeImpact:
    """Analyze changed paths into impacted modules and tests without reading files or running commands."""

    warnings: list[str] = []
    paths = _normalize_paths(changed_paths)
    if not paths and task_plan is not None:
        paths = _normalize_paths(task_plan.likely_files_to_change)
    if not paths and task_scope is not None:
        paths = _paths_from_scope(task_scope.allowed_paths)
        warnings.append("Changed paths were inferred from TaskScope allowed paths; impact is conservative.")
    if not paths:
        warnings.append("No changed paths were provided; generated an unknown impact summary.")

    modules = _impacted_modules(paths)
    tests = _impacted_tests(modules, repository_analysis)
    docs = _impacted_docs(paths, modules)
    risk_level = _risk_level(paths, modules, task_plan, task_scope)
    impact = ChangeImpact(
        changed_paths=paths,
        impacted_modules=modules,
        impacted_tests=tests,
        impacted_docs=docs,
        risk_level=risk_level,
        reason=_reason(paths, modules),
        warnings=_unique(warnings),
    )
    impact.summary_text = _render_summary_text(impact)
    return impact


def change_impact_to_context_item(impact: ChangeImpact, *, id: str = "change-impact") -> ContextItem:
    """Convert ChangeImpact into context for future ExecutionOrchestrator validation strategy."""

    return ContextItem(
        id=id,
        type="project_context",
        title="Change impact",
        content=impact.summary_text,
        source_ref=SourceRef(source_type="project_context", source_id="change_impact", metadata=change_impact_to_dict(impact)),
        priority=56,
        metadata={"context_section": "project_context", "change_impact": change_impact_to_dict(impact)},
    )


def change_impact_to_dict(impact: ChangeImpact) -> dict[str, object]:
    """Return a JSON-friendly ChangeImpact payload for Web/TUI and validation planning."""

    return {
        "changed_paths": list(impact.changed_paths),
        "impacted_modules": list(impact.impacted_modules),
        "impacted_tests": list(impact.impacted_tests),
        "impacted_docs": list(impact.impacted_docs),
        "risk_level": impact.risk_level,
        "reason": impact.reason,
        "warnings": list(impact.warnings),
        "summary_text": impact.summary_text,
    }


def _normalize_paths(paths: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for path in paths or []:
        item = str(path).strip().replace("\\", "/").rstrip("/")
        if item:
            normalized.append(item)
    return sorted(set(normalized))


def _paths_from_scope(allowed_paths: Iterable[str]) -> list[str]:
    paths: list[str] = []
    for path in allowed_paths:
        item = str(path).replace("\\", "/").rstrip("/")
        if item.endswith("/**"):
            item = item[:-3].rstrip("/")
        if "*" not in item and item:
            paths.append(item)
    return _normalize_paths(paths)


def _impacted_modules(paths: list[str]) -> list[str]:
    modules: list[str] = []
    for path in paths:
        module = _module_for_path(path)
        if module:
            modules.append(module)
        if path.startswith("tests/"):
            modules.append("tests")
    return _unique(modules)


def _module_for_path(path: str) -> str | None:
    mapping = (
        ("src/pp_agent/runtime/", "runtime"),
        ("src/pp_agent/tools/", "tools"),
        ("src/pp_agent/sandbox/", "sandbox"),
        ("src/pp_agent/observability/", "observability"),
        ("src/pp_agent/context/", "context"),
        ("src/pp_agent/coding/", "coding"),
        ("src/pp_agent/config/", "config"),
        ("src/pp_agent/storage/", "storage"),
        ("src/pp_agent/cli/", "cli"),
        ("web/", "web"),
        ("docs/", "docs"),
        ("tests/", "tests"),
        (".github/workflows/", "ci"),
    )
    for prefix, module in mapping:
        root = prefix.rstrip("/")
        if path == root or path.startswith(prefix):
            return module
    if path == "README.md":
        return "docs"
    return None


def _impacted_tests(modules: list[str], analysis: RepositoryAnalysis | None) -> list[str]:
    tests: list[str] = []
    _ = analysis
    for module in modules:
        for candidate in MODULE_TESTS.get(module, []):
            tests.append(candidate)
    return _unique(tests)


def _impacted_docs(paths: list[str], modules: list[str]) -> list[str]:
    docs = [path for path in paths if path.startswith("docs/") or path == "README.md"]
    if "docs" in modules and not docs:
        docs.append("docs")
    return _unique(docs)


def _risk_level(
    paths: list[str],
    modules: list[str],
    task_plan: TaskPlan | None,
    task_scope: TaskScope | None,
) -> str:
    text = " ".join([*paths, task_plan.task if task_plan else ""]).lower()
    if any(keyword in text for keyword in ("approval", "policy", "sandbox", "network", "security", "apply_patch")):
        return "high"
    if "sandbox" in modules:
        return "high"
    base = "unknown"
    if modules and all(module in {"docs"} for module in modules):
        base = "low"
    elif modules and all(module == "tests" for module in modules):
        base = "low"
    elif modules and any(module in {"coding", "context", "observability", "runtime", "tools", "config", "storage", "cli", "web", "ci"} for module in modules):
        base = "medium"
    if task_scope is not None:
        base = _higher_risk(base, task_scope.risk_level)
    if task_plan is not None:
        base = _higher_risk(base, task_plan.risk_level)
    return base


def _higher_risk(left: str, right: str) -> str:
    if left == "unknown":
        return right
    if right == "unknown":
        return left
    return left if RISK_ORDER.get(left, 0) >= RISK_ORDER.get(right, 0) else right


def _reason(paths: list[str], modules: list[str]) -> str:
    if not paths:
        return "No changed paths were available for impact analysis."
    if modules:
        return "Impact was inferred from changed path prefixes and repository module conventions."
    return "Changed paths did not match known repository module prefixes."


def _render_summary_text(impact: ChangeImpact) -> str:
    lines = [
        "Change Impact:",
        "- Changed paths:",
    ]
    lines.extend(f"  - {path}" for path in impact.changed_paths) if impact.changed_paths else lines.append("  - None")
    if impact.impacted_modules:
        lines.append("- Impacted modules:")
        lines.extend(f"  - {module}" for module in impact.impacted_modules)
    if impact.impacted_tests:
        lines.append("- Impacted tests:")
        lines.extend(f"  - {test}" for test in impact.impacted_tests)
    if impact.impacted_docs:
        lines.append("- Impacted docs:")
        lines.extend(f"  - {doc}" for doc in impact.impacted_docs)
    lines.append(f"- Risk: {impact.risk_level}")
    if impact.warnings:
        lines.append("- Warnings:")
        lines.extend(f"  - {warning}" for warning in impact.warnings)
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
