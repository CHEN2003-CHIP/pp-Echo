from __future__ import annotations

from pp_agent.coding import (
    ValidationCommand,
    ValidationPlan,
    analyze_change_impact,
    build_validation_plan,
    validation_plan_to_context_item,
)
from pp_agent.coding.repository import RepositoryAnalysis
from pp_agent.observability import timeline_to_jsonable, validation_plan_to_block, validation_plan_to_timeline_step


def _analysis(*, web: bool = False, likely: list[str] | None = None) -> RepositoryAnalysis:
    return RepositoryAnalysis(
        workspace_path=".",
        workspace_name="demo",
        project_type="Python package",
        frontend_roots=["web"] if web else [],
        config_files=["web/package.json"] if web else [],
        likely_test_commands=likely or ["python -m pytest -q"],
    )


def _commands(plan: ValidationPlan) -> list[str]:
    return [command.command for command in plan.commands]


def test_validation_plan_for_coding_changes() -> None:
    plan = build_validation_plan(analyze_change_impact(["src/pp_agent/coding/impact.py"]))

    assert _commands(plan) == ["python -m pytest tests/coding -q"]


def test_validation_plan_for_context_changes() -> None:
    plan = build_validation_plan(analyze_change_impact(["src/pp_agent/context/project.py"]))

    assert _commands(plan) == ["python -m pytest tests/context -q"]


def test_validation_plan_for_observability_changes() -> None:
    plan = build_validation_plan(analyze_change_impact(["src/pp_agent/observability/timeline.py"]))

    assert _commands(plan) == ["python -m pytest tests/observability -q"]


def test_validation_plan_for_sandbox_changes() -> None:
    plan = build_validation_plan(analyze_change_impact(["src/pp_agent/sandbox/executor.py"]))

    assert "python -m pytest tests/tools/test_shell_sandbox_executor.py -q" in _commands(plan)
    assert "python -m pytest -q" in _commands(plan)


def test_validation_plan_for_runtime_changes() -> None:
    plan = build_validation_plan(analyze_change_impact(["src/pp_agent/runtime/runtime.py"]))

    assert _commands(plan) == ["python -m pytest tests/runtime -q"]


def test_validation_plan_for_web_changes() -> None:
    plan = build_validation_plan(analyze_change_impact(["web/src/App.tsx"]), _analysis(web=True))

    assert _commands(plan) == ["cd web && npm test", "cd web && npm run build"]


def test_validation_plan_adds_full_validation_for_high_risk() -> None:
    plan = build_validation_plan(analyze_change_impact(["src/pp_agent/tools/approval_policy.py"]), _analysis(likely=["python -m pytest -q"]))

    assert plan.commands[-1].priority == "full"
    assert plan.commands[-1].command == "python -m pytest -q"


def test_validation_plan_falls_back_to_repository_likely_commands() -> None:
    plan = build_validation_plan(analyze_change_impact(["unknown/file.txt"]), _analysis(likely=["python -m pytest tests/custom -q"]))

    assert _commands(plan) == ["python -m pytest tests/custom -q"]
    assert plan.commands[0].priority == "fallback"


def test_validation_plan_deduplicates_commands() -> None:
    impact = analyze_change_impact(["src/pp_agent/sandbox/executor.py"])
    plan = build_validation_plan(impact, _analysis(likely=["python -m pytest tests/tools/test_shell_sandbox_executor.py -q"]))

    assert _commands(plan) == ["python -m pytest tests/tools/test_shell_sandbox_executor.py -q"]


def test_validation_plan_summary_is_stable() -> None:
    impact = analyze_change_impact(["src/pp_agent/coding/testing.py"])

    first = build_validation_plan(impact)
    second = build_validation_plan(impact)

    assert first.summary_text == second.summary_text


def test_validation_plan_to_context_item() -> None:
    plan = build_validation_plan(analyze_change_impact(["src/pp_agent/coding/testing.py"]))

    item = validation_plan_to_context_item(plan)

    assert item.title == "Validation plan"
    assert item.metadata["validation_plan"]["risk_level"] == "medium"  # type: ignore[index]


def test_validation_plan_to_timeline_step() -> None:
    plan = build_validation_plan(analyze_change_impact(["src/pp_agent/coding/testing.py"]))

    payload = timeline_to_jsonable(validation_plan_to_timeline_step(plan))

    assert payload["type"] == "validation_plan"
    assert payload["details"]["commands"][0]["priority"] == "focused"


def test_validation_plan_to_block() -> None:
    plan = build_validation_plan(analyze_change_impact(["src/pp_agent/coding/testing.py"]))

    payload = timeline_to_jsonable(validation_plan_to_block(plan))

    assert payload["type"] == "validation_plan"
    assert payload["title"] == "Generated validation plan"


def test_validation_plan_public_models_have_docstrings() -> None:
    assert ValidationCommand.__doc__
    assert ValidationPlan.__doc__


def test_validation_plan_public_helpers_have_docstrings() -> None:
    assert build_validation_plan.__doc__
    assert validation_plan_to_context_item.__doc__
    assert validation_plan_to_timeline_step.__doc__
    assert validation_plan_to_block.__doc__
