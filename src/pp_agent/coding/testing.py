from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from pp_agent.coding.impact import ChangeImpact, change_impact_to_dict
from pp_agent.coding.planner import TaskPlan
from pp_agent.coding.repository import RepositoryAnalysis
from pp_agent.context.item import ContextItem
from pp_agent.context.source_ref import SourceRef

FOCUSED_COMMANDS = {
    "tests/coding": "python -m pytest tests/coding -q",
    "tests/context": "python -m pytest tests/context -q",
    "tests/observability": "python -m pytest tests/observability -q",
    "tests/tools/test_shell_sandbox_executor.py": "python -m pytest tests/tools/test_shell_sandbox_executor.py -q",
    "tests/runtime": "python -m pytest tests/runtime -q",
    "tests/tools": "python -m pytest tests/tools -q",
    "tests/config": "python -m pytest tests/config -q",
    "tests/storage": "python -m pytest tests/storage -q",
    "tests/cli": "python -m pytest tests/cli -q",
}


@dataclass
class ValidationCommand:
    """A recommended validation command that a future orchestrator may choose to run."""

    command: str
    priority: str = "focused"
    reason: str = ""
    related_paths: list[str] = field(default_factory=list)


@dataclass
class ValidationPlan:
    """A non-executing validation recommendation derived from change impact."""

    commands: list[ValidationCommand] = field(default_factory=list)
    risk_level: str = "unknown"
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    summary_text: str = ""


def build_validation_plan(
    impact: ChangeImpact,
    repository_analysis: RepositoryAnalysis | None = None,
    task_plan: TaskPlan | None = None,
) -> ValidationPlan:
    """Build a stable, rule-based validation plan without running commands."""

    _ = task_plan
    warnings = list(impact.warnings)
    commands: list[ValidationCommand] = []
    for test_path in impact.impacted_tests:
        command = FOCUSED_COMMANDS.get(test_path)
        if command:
            commands.append(
                ValidationCommand(
                    command=command,
                    priority="focused",
                    reason=f"Focused validation for impacted test path {test_path}.",
                    related_paths=[test_path],
                )
            )
    if "web" in impact.impacted_modules and _has_web_package(repository_analysis):
        commands.extend(
            [
                ValidationCommand(
                    command="cd web && npm test",
                    priority="focused",
                    reason="Frontend package was impacted and web/package.json is present.",
                    related_paths=["web/package.json"],
                ),
                ValidationCommand(
                    command="cd web && npm run build",
                    priority="focused",
                    reason="Frontend package was impacted and web/package.json is present.",
                    related_paths=["web/package.json"],
                ),
            ]
        )
    if impact.risk_level == "high":
        full_command = _full_validation_command(repository_analysis)
        commands.append(
            ValidationCommand(
                command=full_command,
                priority="full",
                reason="High-risk changes should include full validation.",
                related_paths=[],
            )
        )
    if not commands:
        fallback = _fallback_validation_command(repository_analysis)
        if fallback:
            commands.append(
                ValidationCommand(
                    command=fallback,
                    priority="fallback",
                    reason="No focused validation command matched; using repository likely validation.",
                    related_paths=[],
                )
            )
        else:
            warnings.append("No validation command could be inferred from impact or repository analysis.")
    plan = ValidationPlan(
        commands=_dedupe_commands(commands),
        risk_level=impact.risk_level,
        reason=_reason(impact),
        warnings=_unique(warnings),
    )
    plan.summary_text = _render_summary_text(plan)
    return plan


def validation_plan_to_context_item(plan: ValidationPlan, *, id: str = "validation-plan") -> ContextItem:
    """Convert ValidationPlan into context for future execution orchestration."""

    return ContextItem(
        id=id,
        type="project_context",
        title="Validation plan",
        content=plan.summary_text,
        source_ref=SourceRef(source_type="project_context", source_id="validation_plan", metadata=validation_plan_to_dict(plan)),
        priority=55,
        metadata={"context_section": "project_context", "validation_plan": validation_plan_to_dict(plan)},
    )


def validation_plan_to_dict(plan: ValidationPlan) -> dict[str, object]:
    """Return a JSON-friendly ValidationPlan payload for Web/TUI and future orchestration."""

    return {
        "commands": [
            {
                "command": command.command,
                "priority": command.priority,
                "reason": command.reason,
                "related_paths": list(command.related_paths),
            }
            for command in plan.commands
        ],
        "risk_level": plan.risk_level,
        "reason": plan.reason,
        "warnings": list(plan.warnings),
        "summary_text": plan.summary_text,
    }


def _has_web_package(analysis: RepositoryAnalysis | None) -> bool:
    return analysis is not None and ("web/package.json" in analysis.config_files or "web" in analysis.frontend_roots)


def _full_validation_command(analysis: RepositoryAnalysis | None) -> str:
    if analysis is not None and analysis.likely_test_commands:
        return analysis.likely_test_commands[0]
    return "python -m pytest -q"


def _fallback_validation_command(analysis: RepositoryAnalysis | None) -> str | None:
    if analysis is not None and analysis.likely_test_commands:
        return analysis.likely_test_commands[0]
    return None


def _reason(impact: ChangeImpact) -> str:
    payload = change_impact_to_dict(impact)
    modules = payload.get("impacted_modules") or []
    if modules:
        return "Validation commands were inferred from impacted modules and test paths."
    return "Validation plan is conservative because no impacted module was detected."


def _render_summary_text(plan: ValidationPlan) -> str:
    lines = [
        "Validation Plan:",
        f"- Risk: {plan.risk_level}",
        "- Commands:",
    ]
    if plan.commands:
        lines.extend(f"  - [{command.priority}] {command.command}" for command in plan.commands)
    else:
        lines.append("  - None")
    if plan.warnings:
        lines.append("- Warnings:")
        lines.extend(f"  - {warning}" for warning in plan.warnings)
    return "\n".join(lines).strip()


def _dedupe_commands(commands: Iterable[ValidationCommand]) -> list[ValidationCommand]:
    seen: set[str] = set()
    deduped: list[ValidationCommand] = []
    for command in commands:
        key = command.command.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(command)
    return deduped


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
