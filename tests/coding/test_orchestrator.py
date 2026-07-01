from __future__ import annotations

from pathlib import Path

from pp_agent.coding import (
    CodingWorkflow,
    RepositoryAnalysis,
    analyze_repository,
    coding_workflow_to_block,
    coding_workflow_to_context_item,
    coding_workflow_to_timeline_blocks,
    prepare_coding_workflow,
)
from pp_agent.context import ProjectContext, build_project_context
from pp_agent.observability import timeline_to_jsonable


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src" / "pp_agent" / "coding").mkdir(parents=True)
    (tmp_path / "tests" / "coding").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    return tmp_path


def test_prepare_coding_workflow_builds_full_workflow(tmp_path: Path) -> None:
    workflow = prepare_coding_workflow("extend coding intelligence planner", workspace=_workspace(tmp_path))

    assert workflow.status == "prepared"
    assert workflow.repository_analysis is not None
    assert workflow.task_plan.task == "extend coding intelligence planner"
    assert workflow.task_scope.task == "extend coding intelligence planner"
    assert workflow.predicted_impact.impacted_modules == ["docs", "coding"]
    assert workflow.validation_plan.commands[0].command == "python -m pytest tests/coding -q"


def test_prepare_coding_workflow_uses_passed_project_context_and_repository_analysis(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    context = build_project_context(workspace)
    analysis = analyze_repository(workspace, context)

    workflow = prepare_coding_workflow("extend coding intelligence planner", project_context=context, repository_analysis=analysis)

    assert workflow.project_context_summary == context.summary_text
    assert workflow.repository_analysis is analysis
    assert workflow.status == "prepared"


def test_prepare_coding_workflow_builds_project_context_from_workspace(tmp_path: Path) -> None:
    workflow = prepare_coding_workflow("extend coding intelligence planner", workspace=_workspace(tmp_path))

    assert workflow.project_context_summary is not None
    assert "Project Context:" in workflow.project_context_summary


def test_prepare_coding_workflow_falls_back_without_workspace() -> None:
    workflow = prepare_coding_workflow("make it better")

    assert workflow.status == "partial"
    assert workflow.repository_analysis is None
    assert any("no workspace" in warning.lower() for warning in workflow.warnings)


def test_prepare_coding_workflow_includes_task_plan(tmp_path: Path) -> None:
    workflow = prepare_coding_workflow("extend coding intelligence planner", workspace=_workspace(tmp_path))

    assert workflow.task_plan.summary_text.startswith("Task Plan:")


def test_prepare_coding_workflow_includes_task_scope(tmp_path: Path) -> None:
    workflow = prepare_coding_workflow("extend coding intelligence planner", workspace=_workspace(tmp_path))

    assert "src/pp_agent/coding/**" in workflow.task_scope.allowed_paths


def test_prepare_coding_workflow_includes_predicted_impact(tmp_path: Path) -> None:
    workflow = prepare_coding_workflow("extend coding intelligence planner", workspace=_workspace(tmp_path))

    assert workflow.predicted_impact.summary_text.startswith("Predicted Change Impact:")
    assert "not actual impact" in workflow.predicted_impact.summary_text


def test_prepare_coding_workflow_includes_validation_plan(tmp_path: Path) -> None:
    workflow = prepare_coding_workflow("extend coding intelligence planner", workspace=_workspace(tmp_path))

    assert workflow.validation_plan.summary_text.startswith("Validation Plan:")


def test_prepare_coding_workflow_includes_timeline_blocks_in_stable_order(tmp_path: Path) -> None:
    workflow = prepare_coding_workflow("extend coding intelligence planner", workspace=_workspace(tmp_path))

    assert [block.type for block in workflow.timeline_blocks] == [
        "repository_analysis",
        "plan",
        "task_scope",
        "change_impact",
        "validation_plan",
    ]


def test_prepare_coding_workflow_includes_context_items(tmp_path: Path) -> None:
    workflow = prepare_coding_workflow("extend coding intelligence planner", workspace=_workspace(tmp_path))

    assert [item["title"] for item in workflow.context_items] == [
        "Project context",
        "Repository analysis",
        "Task plan",
        "Task scope",
        "Change impact",
        "Validation plan",
    ]


def test_prepare_coding_workflow_summary_is_stable(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    first = prepare_coding_workflow("extend coding intelligence planner", workspace=workspace)
    second = prepare_coding_workflow("extend coding intelligence planner", workspace=workspace)

    assert first.summary_text == second.summary_text


def test_coding_workflow_to_context_item(tmp_path: Path) -> None:
    workflow = prepare_coding_workflow("extend coding intelligence planner", workspace=_workspace(tmp_path))

    item = coding_workflow_to_context_item(workflow)

    assert item["title"] == "Coding workflow"
    assert item["metadata"]["coding_workflow"]["predicted_impact_not_actual"] is True


def test_coding_workflow_to_timeline_blocks(tmp_path: Path) -> None:
    workflow = prepare_coding_workflow("extend coding intelligence planner", workspace=_workspace(tmp_path))

    blocks = coding_workflow_to_timeline_blocks(workflow)

    assert blocks is not workflow.timeline_blocks
    assert [block.type for block in blocks][-1] == "validation_plan"


def test_coding_workflow_to_block(tmp_path: Path) -> None:
    workflow = prepare_coding_workflow("extend coding intelligence planner", workspace=_workspace(tmp_path))

    payload = timeline_to_jsonable(coding_workflow_to_block(workflow))

    assert payload["type"] == "coding_workflow"
    assert payload["details"]["impacted_modules"] == ["docs", "coding"]


def test_coding_workflow_public_models_have_docstrings() -> None:
    assert CodingWorkflow.__doc__
    assert ProjectContext.__doc__
    assert RepositoryAnalysis.__doc__


def test_coding_workflow_public_helpers_have_docstrings() -> None:
    assert prepare_coding_workflow.__doc__
    assert coding_workflow_to_context_item.__doc__
    assert coding_workflow_to_timeline_blocks.__doc__
    assert coding_workflow_to_block.__doc__
