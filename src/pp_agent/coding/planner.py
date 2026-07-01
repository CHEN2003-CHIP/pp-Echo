from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from pp_agent.coding.repository import RepositoryAnalysis
from pp_agent.context.item import ContextItem
from pp_agent.context.project import ProjectContext
from pp_agent.context.source_ref import SourceRef

PLAN_STATUSES = {"pending", "running", "done", "skipped", "failed"}
RISK_LEVELS = {"low", "medium", "high", "unknown"}


@dataclass
class PlanStep:
    """A rule-based coding-intelligence plan step for later TaskScope or execution orchestration."""

    id: str
    title: str
    rationale: str | None
    status: str
    related_paths: list[str] = field(default_factory=list)


@dataclass
class TaskPlan:
    """A rule-based MVP task plan bridging user intent to future TaskScope and ExecutionOrchestrator inputs."""

    task: str
    understanding: str
    plan_steps: list[PlanStep]
    files_to_inspect: list[str] = field(default_factory=list)
    likely_files_to_change: list[str] = field(default_factory=list)
    validation_commands: list[str] = field(default_factory=list)
    risk_level: str = "unknown"
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary_text: str = ""


def build_task_plan(
    task: str,
    project_context: ProjectContext | None = None,
    repository_analysis: RepositoryAnalysis | None = None,
    manifest_excerpt: str | None = None,
) -> TaskPlan:
    """Build a conservative rule-based TaskPlan without LLM calls or execution side effects."""

    normalized_task = task.strip() or "Unspecified task"
    task_text = normalized_task.lower()
    category = _detect_category(task_text)
    warnings: list[str] = []
    assumptions = _assumptions(project_context, repository_analysis, manifest_excerpt)
    files_to_inspect = _files_to_inspect(category, repository_analysis)
    validation_commands = _validation_commands(category, repository_analysis)
    risk_level = _risk_level(category, task_text)
    if category == "unknown":
        warnings.append("Task category was not confidently detected; generated a conservative generic plan.")
    understanding = _understanding(category)
    likely_files_to_change = _likely_files_to_change(category, files_to_inspect)
    plan_steps = _plan_steps(category, files_to_inspect)
    plan = TaskPlan(
        task=normalized_task,
        understanding=understanding,
        plan_steps=plan_steps,
        files_to_inspect=files_to_inspect,
        likely_files_to_change=likely_files_to_change,
        validation_commands=validation_commands,
        risk_level=risk_level,
        assumptions=assumptions,
        warnings=warnings,
    )
    plan.summary_text = _render_summary_text(plan)
    return plan


def task_plan_to_context_item(plan: TaskPlan, *, id: str = "task-plan") -> ContextItem:
    """Convert a TaskPlan into a context item for later TaskScope or ExecutionOrchestrator phases."""

    return ContextItem(
        id=id,
        type="project_context",
        title="Task plan",
        content=plan.summary_text,
        source_ref=SourceRef(source_type="project_context", source_id="task_plan", metadata=_plan_metadata(plan)),
        priority=58,
        metadata={"context_section": "project_context", "task_plan": _plan_metadata(plan)},
    )


def task_plan_to_dict(plan: TaskPlan) -> dict[str, object]:
    """Return a JSON-friendly TaskPlan payload for Web/TUI timeline and future orchestration surfaces."""

    return _plan_metadata(plan)


def _detect_category(task_text: str) -> str:
    checks = [
        ("sandbox", ("sandbox", "docker", "approval", "apply_patch", "structured_changes", "policy", "security")),
        ("ci", ("ci", "test", "pytest", "github actions", "fail", "failure")),
        ("observability", ("timeline", "trace", "observability")),
        ("context", ("context", "project context", "manifest", "runtime bridge")),
        ("coding", ("repository", "analyzer", "coding intelligence", "planner")),
        ("cli", ("cli", "command")),
        ("web", ("web", "frontend", "ui")),
        ("docs", ("docs", "readme", "documentation")),
    ]
    for category, keywords in checks:
        if any(keyword in task_text for keyword in keywords):
            return category
    return "unknown"


def _files_to_inspect(category: str, analysis: RepositoryAnalysis | None) -> list[str]:
    module_map = analysis.module_map if analysis else {}
    config_files = analysis.config_files if analysis else []
    ci_files = analysis.ci_files if analysis else []
    test_roots = analysis.test_roots if analysis else []
    source_roots = analysis.source_roots if analysis else []
    doc_roots = analysis.doc_roots if analysis else []
    files_by_category: dict[str, list[str]] = {
        "ci": [*ci_files, *test_roots, "tests/", *_existing("pyproject.toml", config_files)],
        "sandbox": [
            *module_map.get("sandbox", ["src/pp_agent/sandbox"]),
            *module_map.get("tools", ["src/pp_agent/tools"]),
            "tests/tools/test_shell_sandbox_executor.py",
            "docs/sandbox.md",
        ],
        "observability": [*module_map.get("observability", ["src/pp_agent/observability"]), "tests/observability", "docs/timeline.md"],
        "context": ["src/pp_agent/context", "tests/context", "docs/project-context.md"],
        "coding": ["src/pp_agent/coding", "tests/coding", "docs/coding-intelligence.md"],
        "cli": [*module_map.get("cli", ["src/pp_agent/cli"]), "tests/cli"],
        "web": ["web/"],
        "docs": [*(doc_roots or ["docs/"]), "README.md"],
        "unknown": [*source_roots[:3], *test_roots[:2]],
    }
    return _unique(files_by_category.get(category, []))


def _validation_commands(category: str, analysis: RepositoryAnalysis | None) -> list[str]:
    likely = analysis.likely_test_commands if analysis else []
    config_files = analysis.config_files if analysis else []
    commands_by_category = {
        "ci": likely[:4] or ["python -m pytest -q"],
        "sandbox": ["python -m pytest tests/tools/test_shell_sandbox_executor.py tests/tools -q"],
        "observability": ["python -m pytest tests/observability -q"],
        "context": ["python -m pytest tests/context -q"],
        "coding": ["python -m pytest tests/coding -q"],
        "cli": ["python -m pytest tests/cli -q"],
        "web": _web_commands(config_files),
        "docs": [],
        "unknown": likely[:3],
    }
    return _unique(commands_by_category.get(category, []))


def _risk_level(category: str, task_text: str) -> str:
    if category == "sandbox" or any(keyword in task_text for keyword in ("security", "approval", "permission", "policy")):
        return "high"
    if category in {"ci", "observability", "context", "coding", "cli", "web"}:
        return "medium"
    if category == "docs":
        return "low"
    return "unknown"


def _understanding(category: str) -> str:
    return {
        "ci": "CI/test-related task detected. Inspect CI, tests, and related source modules before making changes.",
        "sandbox": "Sandbox, approval, policy, or security-sensitive task detected. Inspect governance and tool boundaries before making changes.",
        "observability": "Timeline, trace, or observability task detected. Preserve JSON-friendly contracts and trace-safe metadata.",
        "context": "Context, manifest, or runtime bridge task detected. Preserve context pipeline boundaries and source provenance.",
        "coding": "Coding intelligence task detected. Keep planning and repository analysis lightweight and rule-based.",
        "cli": "CLI task detected. Inspect command entrypoints and focused CLI tests before making changes.",
        "web": "Web/frontend task detected. Inspect the web surface and use frontend validation when available.",
        "docs": "Documentation task detected. Keep edits scoped to public docs and avoid runtime behavior changes.",
        "unknown": "Task category is unclear. Use repository structure to inspect likely source and test roots before changing code.",
    }[category]


def _plan_steps(category: str, files_to_inspect: list[str]) -> list[PlanStep]:
    titles = {
        "ci": ["Inspect failing test or CI context", "Locate related imports or modules", "Make minimal fix", "Run focused validation"],
        "sandbox": ["Inspect sandbox and approval boundaries", "Locate policy or tool-surface impact", "Make minimal guarded change", "Run sandbox and tool validation"],
        "observability": ["Inspect timeline or trace contract", "Locate frontend-safe payload shape", "Make additive contract change", "Run observability validation"],
        "context": ["Inspect context and manifest flow", "Locate source-ref and budget impact", "Make minimal context change", "Run context validation"],
        "coding": ["Inspect coding intelligence module", "Update planner or repository helpers", "Keep implementation rule-based", "Run coding tests"],
        "cli": ["Inspect CLI command flow", "Locate command parser or renderer impact", "Make minimal CLI change", "Run CLI validation"],
        "web": ["Inspect web entrypoint", "Locate relevant UI state or API usage", "Make focused frontend change", "Run web validation"],
        "docs": ["Inspect relevant docs", "Update documentation text", "Check examples stay accurate", "Run doc-adjacent validation if available"],
        "unknown": ["Inspect repository structure", "Identify owning module", "Make the smallest scoped change", "Run likely validation"],
    }[category]
    return [
        PlanStep(
            id=f"step-{index}",
            title=title,
            rationale=_step_rationale(category, title),
            status="pending",
            related_paths=files_to_inspect[:4],
        )
        for index, title in enumerate(titles, start=1)
    ]


def _step_rationale(category: str, title: str) -> str:
    return f"{title} is part of the rule-based {category} planning path."


def _likely_files_to_change(category: str, files_to_inspect: list[str]) -> list[str]:
    if category in {"docs", "coding", "context", "observability"}:
        return [path for path in files_to_inspect if not path.startswith("tests/")][:3]
    return []


def _assumptions(
    project_context: ProjectContext | None,
    analysis: RepositoryAnalysis | None,
    manifest_excerpt: str | None,
) -> list[str]:
    assumptions: list[str] = []
    if project_context is None:
        assumptions.append("ProjectContext was not provided; using repository analysis or generic defaults.")
    if analysis is None:
        assumptions.append("RepositoryAnalysis was not provided; generated a conservative generic plan.")
    if manifest_excerpt:
        assumptions.append("Manifest excerpt was provided and treated as project guidance, not executable content.")
    return assumptions


def _render_summary_text(plan: TaskPlan) -> str:
    lines = [
        "Task Plan:",
        f"- Task: {plan.task}",
        f"- Understanding: {plan.understanding}",
        "- Steps:",
    ]
    lines.extend(f"  {index}. {step.title}" for index, step in enumerate(plan.plan_steps, start=1))
    if plan.files_to_inspect:
        lines.append("- Files to inspect:")
        lines.extend(f"  - {path}" for path in plan.files_to_inspect)
    if plan.likely_files_to_change:
        lines.append("- Likely files to change:")
        lines.extend(f"  - {path}" for path in plan.likely_files_to_change)
    if plan.validation_commands:
        lines.append("- Validation:")
        lines.extend(f"  - {command}" for command in plan.validation_commands)
    lines.append(f"- Risk: {plan.risk_level}")
    if plan.assumptions:
        lines.append("- Assumptions:")
        lines.extend(f"  - {assumption}" for assumption in plan.assumptions)
    if plan.warnings:
        lines.append("- Warnings:")
        lines.extend(f"  - {warning}" for warning in plan.warnings)
    return "\n".join(lines).strip()


def _plan_metadata(plan: TaskPlan) -> dict[str, object]:
    return {
        "task": plan.task,
        "understanding": plan.understanding,
        "plan_steps": [
            {
                "id": step.id,
                "title": step.title,
                "rationale": step.rationale,
                "status": step.status,
                "related_paths": list(step.related_paths),
            }
            for step in plan.plan_steps
        ],
        "files_to_inspect": list(plan.files_to_inspect),
        "likely_files_to_change": list(plan.likely_files_to_change),
        "validation_commands": list(plan.validation_commands),
        "risk_level": plan.risk_level,
        "assumptions": list(plan.assumptions),
        "warnings": list(plan.warnings),
    }


def _web_commands(config_files: list[str]) -> list[str]:
    if "web/package.json" not in config_files:
        return []
    return ["cd web && npm test", "cd web && npm run build"]


def _existing(path: str, values: Iterable[str]) -> list[str]:
    return [path] if path in values else []


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
