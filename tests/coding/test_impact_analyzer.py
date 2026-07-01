from __future__ import annotations

from pp_agent.coding import (
    ChangeImpact,
    TaskPlan,
    TaskScope,
    analyze_change_impact,
    change_impact_to_context_item,
)
from pp_agent.observability import change_impact_to_block, change_impact_to_timeline_step, timeline_to_jsonable


def test_analyze_change_impact_detects_coding_module() -> None:
    impact = analyze_change_impact(["src/pp_agent/coding/impact.py"])

    assert impact.impacted_modules == ["coding"]
    assert impact.impacted_tests == ["tests/coding"]
    assert impact.risk_level == "medium"


def test_analyze_change_impact_detects_context_module() -> None:
    impact = analyze_change_impact(["src/pp_agent/context/project.py"])

    assert impact.impacted_modules == ["context"]
    assert impact.impacted_tests == ["tests/context"]


def test_analyze_change_impact_detects_observability_module() -> None:
    impact = analyze_change_impact(["src/pp_agent/observability/timeline.py"])

    assert impact.impacted_modules == ["observability"]
    assert impact.impacted_tests == ["tests/observability"]


def test_analyze_change_impact_detects_sandbox_high_risk() -> None:
    impact = analyze_change_impact(["src/pp_agent/sandbox/executor.py"])

    assert impact.impacted_modules == ["sandbox"]
    assert impact.impacted_tests == ["tests/tools/test_shell_sandbox_executor.py"]
    assert impact.risk_level == "high"


def test_analyze_change_impact_detects_docs_low_risk() -> None:
    impact = analyze_change_impact(["docs/coding-intelligence.md"])

    assert impact.impacted_modules == ["docs"]
    assert impact.impacted_docs == ["docs/coding-intelligence.md"]
    assert impact.risk_level == "low"


def test_analyze_change_impact_detects_tests_low_risk() -> None:
    impact = analyze_change_impact(["tests/coding/test_impact_analyzer.py"])

    assert impact.impacted_modules == ["tests"]
    assert impact.risk_level == "low"


def test_analyze_change_impact_falls_back_to_task_plan() -> None:
    plan = TaskPlan(task="x", understanding="x", plan_steps=[], likely_files_to_change=["src/pp_agent/context/project.py"])

    impact = analyze_change_impact([], task_plan=plan)

    assert impact.changed_paths == ["src/pp_agent/context/project.py"]
    assert impact.impacted_modules == ["context"]


def test_analyze_change_impact_falls_back_to_task_scope_with_warning() -> None:
    scope = TaskScope(task="x", allowed_paths=["src/pp_agent/coding/**"], risk_level="high")

    impact = analyze_change_impact([], task_scope=scope)

    assert impact.changed_paths == ["src/pp_agent/coding"]
    assert impact.risk_level == "high"
    assert impact.warnings == ["Changed paths were inferred from TaskScope allowed paths; impact is conservative."]


def test_change_impact_summary_is_stable() -> None:
    first = analyze_change_impact(["src/pp_agent/coding/testing.py", "src/pp_agent/coding/impact.py"])
    second = analyze_change_impact(["src/pp_agent/coding/impact.py", "src/pp_agent/coding/testing.py"])

    assert first.summary_text == second.summary_text


def test_change_impact_to_context_item() -> None:
    impact = analyze_change_impact(["src/pp_agent/coding/impact.py"])

    item = change_impact_to_context_item(impact)

    assert item.title == "Change impact"
    assert item.metadata["change_impact"]["risk_level"] == "medium"  # type: ignore[index]


def test_change_impact_to_timeline_step() -> None:
    impact = analyze_change_impact(["src/pp_agent/coding/impact.py"])

    payload = timeline_to_jsonable(change_impact_to_timeline_step(impact))

    assert payload["type"] == "change_impact"
    assert payload["details"]["impacted_modules"] == ["coding"]


def test_change_impact_to_block() -> None:
    impact = analyze_change_impact(["src/pp_agent/coding/impact.py"])

    payload = timeline_to_jsonable(change_impact_to_block(impact))

    assert payload["type"] == "change_impact"
    assert payload["title"] == "Analyzed change impact"


def test_change_impact_public_models_have_docstrings() -> None:
    assert ChangeImpact.__doc__


def test_change_impact_public_helpers_have_docstrings() -> None:
    assert analyze_change_impact.__doc__
    assert change_impact_to_context_item.__doc__
    assert change_impact_to_timeline_step.__doc__
    assert change_impact_to_block.__doc__
