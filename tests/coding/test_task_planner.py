from __future__ import annotations

from pathlib import Path

from pp_agent.coding import (
    PlanStep,
    TaskPlan,
    analyze_repository,
    build_task_plan,
    task_plan_to_context_item,
)
from pp_agent.context import build_project_context
from pp_agent.observability import task_plan_to_block, task_plan_to_timeline_step, timeline_to_jsonable


def _analysis(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src" / "pp_agent" / "sandbox").mkdir(parents=True)
    (tmp_path / "src" / "pp_agent" / "tools").mkdir(parents=True)
    (tmp_path / "src" / "pp_agent" / "observability").mkdir(parents=True)
    (tmp_path / "src" / "pp_agent" / "context").mkdir(parents=True)
    (tmp_path / "src" / "pp_agent" / "coding").mkdir(parents=True)
    (tmp_path / "src" / "pp_agent" / "cli").mkdir(parents=True)
    (tmp_path / "tests" / "observability").mkdir(parents=True)
    (tmp_path / "tests" / "context").mkdir(parents=True)
    (tmp_path / "tests" / "coding").mkdir(parents=True)
    (tmp_path / "tests" / "runtime").mkdir(parents=True)
    (tmp_path / "tests" / "tools").mkdir(parents=True)
    (tmp_path / "tests" / "cli").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text('{"name":"web"}', encoding="utf-8")
    workflow = tmp_path / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    project_context = build_project_context(tmp_path)
    return project_context, analyze_repository(tmp_path, project_context)


def test_task_planner_builds_generic_plan(tmp_path: Path) -> None:
    plan = build_task_plan("make it better")

    assert plan.risk_level == "unknown"
    assert plan.warnings == ["Task category was not confidently detected; generated a conservative generic plan."]
    assert plan.plan_steps[0].title == "Inspect repository structure"


def test_task_planner_uses_repository_analysis_validation_commands(tmp_path: Path) -> None:
    project_context, analysis = _analysis(tmp_path)

    plan = build_task_plan("fix pytest failure", project_context, analysis)

    assert plan.validation_commands[0] == "python -m pytest -q"


def test_task_planner_detects_ci_or_test_task(tmp_path: Path) -> None:
    project_context, analysis = _analysis(tmp_path)

    plan = build_task_plan("fix GitHub Actions test failure", project_context, analysis)

    assert plan.risk_level == "medium"
    assert ".github/workflows/ci.yml" in plan.files_to_inspect
    assert "Inspect failing test or CI context" in plan.summary_text


def test_task_planner_detects_sandbox_task(tmp_path: Path) -> None:
    project_context, analysis = _analysis(tmp_path)

    plan = build_task_plan("change sandbox approval policy", project_context, analysis)

    assert plan.risk_level == "high"
    assert "src/pp_agent/sandbox" in plan.files_to_inspect
    assert any("sandbox" in command for command in plan.validation_commands)


def test_task_planner_detects_observability_task(tmp_path: Path) -> None:
    project_context, analysis = _analysis(tmp_path)

    plan = build_task_plan("add timeline trace block", project_context, analysis)

    assert plan.risk_level == "medium"
    assert "src/pp_agent/observability" in plan.files_to_inspect
    assert "python -m pytest tests/observability -q" in plan.validation_commands


def test_task_planner_detects_context_task(tmp_path: Path) -> None:
    project_context, analysis = _analysis(tmp_path)

    plan = build_task_plan("update project context manifest runtime bridge", project_context, analysis)

    assert "src/pp_agent/context" in plan.files_to_inspect
    assert "python -m pytest tests/context -q" in plan.validation_commands


def test_task_planner_detects_coding_task(tmp_path: Path) -> None:
    project_context, analysis = _analysis(tmp_path)

    plan = build_task_plan("extend coding intelligence planner", project_context, analysis)

    assert "src/pp_agent/coding" in plan.files_to_inspect
    assert "python -m pytest tests/coding -q" in plan.validation_commands


def test_task_planner_detects_cli_task(tmp_path: Path) -> None:
    project_context, analysis = _analysis(tmp_path)

    plan = build_task_plan("add cli command", project_context, analysis)

    assert "src/pp_agent/cli" in plan.files_to_inspect
    assert "python -m pytest tests/cli -q" in plan.validation_commands


def test_task_planner_detects_web_task(tmp_path: Path) -> None:
    project_context, analysis = _analysis(tmp_path)

    plan = build_task_plan("update web frontend ui", project_context, analysis)

    assert "web/" in plan.files_to_inspect
    assert "cd web && npm test" in plan.validation_commands
    assert "cd web && npm run build" in plan.validation_commands


def test_task_planner_detects_docs_task(tmp_path: Path) -> None:
    project_context, analysis = _analysis(tmp_path)

    plan = build_task_plan("update README docs", project_context, analysis)

    assert plan.risk_level == "low"
    assert "docs" in plan.files_to_inspect
    assert "README.md" in plan.files_to_inspect


def test_task_planner_sets_high_risk_for_security_or_approval_task(tmp_path: Path) -> None:
    project_context, analysis = _analysis(tmp_path)

    plan = build_task_plan("review approval security behavior", project_context, analysis)

    assert plan.risk_level == "high"


def test_task_plan_summary_is_stable(tmp_path: Path) -> None:
    project_context, analysis = _analysis(tmp_path)

    first = build_task_plan("fix pytest failure", project_context, analysis)
    second = build_task_plan("fix pytest failure", project_context, analysis)

    assert first.summary_text == second.summary_text


def test_task_plan_to_timeline_step(tmp_path: Path) -> None:
    project_context, analysis = _analysis(tmp_path)
    plan = build_task_plan("fix pytest failure", project_context, analysis)

    payload = timeline_to_jsonable(task_plan_to_timeline_step(plan))

    assert payload["type"] == "plan"
    assert payload["title"] == "Generated task plan"
    assert payload["details"]["risk_level"] == "medium"


def test_task_plan_to_timeline_block(tmp_path: Path) -> None:
    project_context, analysis = _analysis(tmp_path)
    plan = build_task_plan("fix pytest failure", project_context, analysis)

    payload = timeline_to_jsonable(task_plan_to_block(plan))

    assert payload["type"] == "plan"
    assert payload["details"]["task"] == "fix pytest failure"


def test_task_plan_to_context_item_if_implemented(tmp_path: Path) -> None:
    project_context, analysis = _analysis(tmp_path)
    plan = build_task_plan("fix pytest failure", project_context, analysis)

    item = task_plan_to_context_item(plan)

    assert item.title == "Task plan"
    assert item.metadata["task_plan"]["risk_level"] == "medium"  # type: ignore[index]


def test_task_planner_public_models_have_docstrings() -> None:
    assert PlanStep.__doc__
    assert TaskPlan.__doc__


def test_task_planner_public_helpers_have_docstrings() -> None:
    assert build_task_plan.__doc__
    assert task_plan_to_context_item.__doc__
    assert task_plan_to_timeline_step.__doc__
    assert task_plan_to_block.__doc__
