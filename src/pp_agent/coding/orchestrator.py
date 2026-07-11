from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pp_agent.coding.impact import ChangeImpact, analyze_change_impact, change_impact_to_context_item
from pp_agent.coding.planner import TaskPlan, build_task_plan, task_plan_to_context_item
from pp_agent.coding.repository import RepositoryAnalysis, analyze_repository, repository_analysis_to_context_item
from pp_agent.coding.repository_summary import RepositorySummary, repository_summary_to_dict
from pp_agent.coding.repository_summary_collector import build_repository_summary
from pp_agent.coding.scope import TaskScope, build_task_scope, task_scope_to_context_item
from pp_agent.coding.testing import ValidationPlan, build_validation_plan, validation_plan_to_context_item
from pp_agent.context.project import ProjectContext, build_project_context, project_context_to_timeline_step


@dataclass
class CodingWorkflow:
    """Preparation-phase coding workflow for later execution surfaces.

    The workflow orchestrates ProjectContext, RepositoryAnalysis, TaskPlan, TaskScope, predicted
    ChangeImpact, and ValidationPlan without executing commands or editing files. Its
    `predicted_impact` is not actual impact; actual impact can be generated later from real
    structured changes by a future ExecutionOrchestrator, CLI/TUI, or Web flow.
    """

    task: str
    status: str
    project_context_summary: str | None
    repository_analysis: RepositoryAnalysis | None
    repository_summary: RepositorySummary | None
    task_plan: TaskPlan
    task_scope: TaskScope
    predicted_impact: ChangeImpact
    validation_plan: ValidationPlan
    timeline_blocks: list[Any] = field(default_factory=list)
    context_items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary_text: str = ""


def prepare_coding_workflow(
    task: str,
    workspace: Path | None = None,
    project_context: ProjectContext | None = None,
    repository_analysis: RepositoryAnalysis | None = None,
    manifest_excerpt: str | None = None,
    include_repository_summary: bool = True,
) -> CodingWorkflow:
    """Prepare a coding task workflow without executing shell commands or editing files.

    This is the preparation-stage orchestrator for future ExecutionOrchestrator, CLI/TUI, and
    Web consumers. It produces predicted impact only, not actual impact from file changes.
    """

    normalized_task = task.strip() or "Unspecified task"
    warnings: list[str] = []
    context = project_context or _build_project_context(workspace, warnings)
    analysis = repository_analysis or _build_repository_analysis(workspace, context, warnings)
    summary = _build_repository_summary(workspace, context, analysis, include_repository_summary)
    plan = _build_plan(normalized_task, context, analysis, manifest_excerpt, warnings)
    scope = _build_scope(plan, analysis, context, warnings)
    predicted_impact = analyze_change_impact(
        changed_paths=plan.likely_files_to_change,
        repository_analysis=analysis,
        task_plan=plan,
        task_scope=scope,
    )
    predicted_impact.reason = f"Predicted impact only. {predicted_impact.reason}"
    predicted_impact.summary_text = _predicted_impact_summary(predicted_impact)
    validation_plan = build_validation_plan(predicted_impact, analysis, plan)
    warnings = _unique([*warnings, *plan.warnings, *scope.warnings, *predicted_impact.warnings, *validation_plan.warnings])
    workflow = CodingWorkflow(
        task=normalized_task,
        status=_status(context, analysis, warnings),
        project_context_summary=context.summary_text if context is not None else None,
        repository_analysis=analysis,
        repository_summary=summary,
        task_plan=plan,
        task_scope=scope,
        predicted_impact=predicted_impact,
        validation_plan=validation_plan,
        warnings=warnings,
    )
    workflow.timeline_blocks = _build_timeline_blocks(workflow)
    workflow.context_items = _build_context_items(workflow, context)
    workflow.summary_text = _render_summary_text(workflow)
    return workflow


def coding_workflow_to_context_item(workflow: CodingWorkflow) -> dict[str, Any]:
    """Convert a prepared coding workflow into a JSON-friendly context item.

    The returned item is for future orchestration context injection only; it does not execute
    commands, edit files, or treat predicted impact as actual impact.
    """

    payload = _workflow_details(workflow)
    return {
        "id": "coding-workflow",
        "type": "project_context",
        "title": "Coding workflow",
        "content": workflow.summary_text,
        "source_ref": {"source_type": "project_context", "source_id": "coding_workflow", "metadata": payload},
        "priority": 54,
        "metadata": {"context_section": "project_context", "coding_workflow": payload},
    }


def coding_workflow_to_timeline_blocks(workflow: CodingWorkflow) -> list[Any]:
    """Return prepared workflow timeline blocks without running validation commands."""

    return list(workflow.timeline_blocks)


def coding_workflow_to_block(workflow: CodingWorkflow) -> Any:
    """Build one coding workflow preparation block without executing or editing anything."""

    from pp_agent.observability.timeline import TimelineBlock, to_jsonable

    return TimelineBlock(
        id="coding-workflow",
        run_id=None,
        type="coding_workflow",
        status=workflow.status,
        title="Prepared coding workflow",
        content=workflow.summary_text,
        details=to_jsonable(_workflow_details(workflow)),
        children=[],
        artifact_ids=[command.command for command in workflow.validation_plan.commands],
    )


def _build_project_context(workspace: Path | None, warnings: list[str]) -> ProjectContext | None:
    if workspace is None:
        warnings.append("ProjectContext was not provided and no workspace was available.")
        return None
    try:
        return build_project_context(workspace)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"ProjectContext build failed: {exc.__class__.__name__}.")
        return None


def _build_repository_analysis(workspace: Path | None, context: ProjectContext | None, warnings: list[str]) -> RepositoryAnalysis | None:
    if workspace is None:
        warnings.append("RepositoryAnalysis was not provided and no workspace was available.")
        return None
    try:
        return analyze_repository(workspace, context)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"RepositoryAnalysis build failed: {exc.__class__.__name__}.")
        return None


def _build_repository_summary(
    workspace: Path | None,
    context: ProjectContext | None,
    analysis: RepositoryAnalysis | None,
    include_repository_summary: bool,
) -> RepositorySummary | None:
    if not include_repository_summary or context is None or analysis is None:
        return None
    repository_root = Path(workspace) if workspace is not None else Path(context.workspace_path)
    return build_repository_summary(
        project_context=context,
        repository_analysis=analysis,
        repository_root=repository_root,
    )


def _build_plan(
    task: str,
    context: ProjectContext | None,
    analysis: RepositoryAnalysis | None,
    manifest_excerpt: str | None,
    warnings: list[str],
) -> TaskPlan:
    try:
        return build_task_plan(task, context, analysis, manifest_excerpt)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"TaskPlan build failed: {exc.__class__.__name__}; using a generic fallback plan.")
        return TaskPlan(
            task=task,
            understanding="Task planning failed; generated a generic fallback plan.",
            plan_steps=[],
            risk_level="unknown",
            warnings=["TaskPlan build failed; fallback plan is conservative."],
            summary_text=f"Task Plan:\n- Task: {task}\n- Risk: unknown",
        )


def _build_scope(plan: TaskPlan, analysis: RepositoryAnalysis | None, context: ProjectContext | None, warnings: list[str]) -> TaskScope:
    try:
        return build_task_scope(plan, analysis, context)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"TaskScope build failed: {exc.__class__.__name__}; using a read-only fallback scope.")
        scope = TaskScope(
            task=plan.task,
            allow_edit=False,
            allow_shell=False,
            allow_delete=False,
            allow_network=False,
            risk_level="unknown",
            reason="Fallback scope after TaskScope build failure.",
            warnings=["TaskScope build failed; fallback scope denies edit and shell."],
        )
        scope.summary_text = "Task Scope:\n- Fallback read-only scope\n- Risk: unknown"
        return scope


def _build_timeline_blocks(workflow: CodingWorkflow) -> list[Any]:
    from pp_agent.observability.timeline import (
        change_impact_to_block,
        repository_analysis_to_block,
        task_plan_to_block,
        task_scope_to_block,
        validation_plan_to_block,
    )

    blocks: list[Any] = []
    if workflow.repository_analysis is not None:
        blocks.append(repository_analysis_to_block(workflow.repository_analysis))
    blocks.extend(
        [
            task_plan_to_block(workflow.task_plan),
            task_scope_to_block(workflow.task_scope),
            change_impact_to_block(workflow.predicted_impact),
            validation_plan_to_block(workflow.validation_plan),
        ]
    )
    return blocks


def _build_context_items(workflow: CodingWorkflow, context: ProjectContext | None) -> list[dict[str, Any]]:
    items: list[Any] = []
    if context is not None:
        items.append(project_context_to_timeline_step(context))
    if workflow.repository_analysis is not None:
        items.append(repository_analysis_to_context_item(workflow.repository_analysis))
    items.extend(
        [
            task_plan_to_context_item(workflow.task_plan),
            task_scope_to_context_item(workflow.task_scope),
            change_impact_to_context_item(workflow.predicted_impact),
            validation_plan_to_context_item(workflow.validation_plan),
        ]
    )
    return [_jsonable(item) for item in items]


def _jsonable(value: Any) -> Any:
    from pp_agent.observability.timeline import to_jsonable

    return to_jsonable(value)


def _workflow_details(workflow: CodingWorkflow) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task": workflow.task,
        "status": workflow.status,
        "risk_level": workflow.task_plan.risk_level,
        "scope_risk_level": workflow.task_scope.risk_level,
        "impact_risk_level": workflow.predicted_impact.risk_level,
        "impacted_modules": list(workflow.predicted_impact.impacted_modules),
        "validation_commands": [command.command for command in workflow.validation_plan.commands],
        "warnings": list(workflow.warnings),
        "predicted_impact_not_actual": True,
    }
    if workflow.repository_summary is not None:
        payload["repository_summary"] = repository_summary_to_dict(workflow.repository_summary)
    return payload


def _status(context: ProjectContext | None, analysis: RepositoryAnalysis | None, warnings: list[str]) -> str:
    if context is None or analysis is None:
        return "partial"
    if any("failed" in warning.lower() for warning in warnings):
        return "partial"
    return "prepared"


def _predicted_impact_summary(impact: ChangeImpact) -> str:
    lines = [
        "Predicted Change Impact:",
        "- This is predicted impact, not actual impact from structured changes.",
        "- Changed paths:",
    ]
    lines.extend(f"  - {path}" for path in impact.changed_paths) if impact.changed_paths else lines.append("  - None")
    if impact.impacted_modules:
        lines.append("- Impacted modules:")
        lines.extend(f"  - {module}" for module in impact.impacted_modules)
    if impact.impacted_tests:
        lines.append("- Impacted tests:")
        lines.extend(f"  - {test}" for test in impact.impacted_tests)
    lines.append(f"- Risk: {impact.risk_level}")
    if impact.warnings:
        lines.append("- Warnings:")
        lines.extend(f"  - {warning}" for warning in impact.warnings)
    return "\n".join(lines).strip()


def _render_summary_text(workflow: CodingWorkflow) -> str:
    lines = [
        "Coding Workflow:",
        f"- Task: {workflow.task}",
        f"- Status: {workflow.status}",
        f"- Plan risk: {workflow.task_plan.risk_level}",
        "- Scope:",
        f"  - edit: {'allowed' if workflow.task_scope.allow_edit else 'denied'}",
        f"  - shell: {'allowed with existing approval/policy' if workflow.task_scope.allow_shell else 'denied'}",
        f"  - delete: {'allowed' if workflow.task_scope.allow_delete else 'denied'}",
        f"  - network: {'allowed' if workflow.task_scope.allow_network else 'denied'}",
        "- Predicted impact (not actual impact):",
    ]
    lines.extend(f"  - {module}" for module in workflow.predicted_impact.impacted_modules) if workflow.predicted_impact.impacted_modules else lines.append("  - unknown")
    lines.append("- Validation:")
    lines.extend(f"  - {command.command}" for command in workflow.validation_plan.commands) if workflow.validation_plan.commands else lines.append("  - None")
    if workflow.warnings:
        lines.append("- Warnings:")
        lines.extend(f"  - {warning}" for warning in workflow.warnings)
    return "\n".join(lines).strip()


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique
