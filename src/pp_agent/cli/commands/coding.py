from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pp_agent.coding import (
    ControlledLoopOptions,
    CodingExecutionSession,
    CodingWorkflow,
    ControlledToolLoopResult,
    ValidationOutcome,
    ValidationRepairCycleState,
    prepare_coding_workflow,
    run_controlled_coding_loop,
    start_coding_execution_session,
    task_plan_to_dict,
    task_scope_to_dict,
    validation_plan_to_dict,
)
from pp_agent.coding.impact import change_impact_to_dict
from pp_agent.observability.timeline import to_jsonable
from pp_agent.runtime.execution_context import runtime_execution_context_to_dict
from pp_agent.runtime.scope_contract import write_scope_to_dict


def build_agent(workspace: Path):
    """Build the runtime lazily so prepare-only CLI imports do not load app/bootstrap."""

    from pp_agent.app.bootstrap import build_agent as bootstrap_build_agent

    return bootstrap_build_agent(workspace)


def run_code_command(
    task: str,
    workspace: Path,
    *,
    max_turns: int = 3,
    prepare_only: bool = False,
    dry_run: bool = False,
    json_mode: bool = False,
    show_timeline: bool = False,
) -> dict[str, Any]:
    """Run the `pp-echo code` product entrypoint without auto-approval or auto-apply.

    The CLI is a first-class controlled coding surface for future TUI/Web reuse. It filters pending
    approvals, timeline details, and result payloads so no full tool payloads, diffs, file contents,
    prompts, or secrets are printed. JSON output is intentionally stable and JSON-friendly.
    """

    resolved_workspace = Path(workspace)
    if prepare_only:
        workflow = prepare_coding_workflow(task, workspace=resolved_workspace)
        session = start_coding_execution_session(workflow)
        payload = prepare_result_to_cli_dict(workflow, session, show_timeline=show_timeline)
        output = json.dumps(payload, ensure_ascii=False, indent=2) if json_mode else format_prepare_only_result(workflow, session, show_timeline=show_timeline)
        print(output)
        return payload

    runtime = build_agent(resolved_workspace)
    options = ControlledLoopOptions(
        max_model_turns=max(0, int(max_turns)),
        stop_on_approval=True,
        stop_on_guardrail_block=True,
        stop_on_scope_block=True,
        dry_run=bool(dry_run),
    )
    result = run_controlled_coding_loop(task, runtime, workspace=resolved_workspace, options=options)
    payload = controlled_loop_result_to_cli_dict(result, show_timeline=show_timeline)
    output = json.dumps(payload, ensure_ascii=False, indent=2) if json_mode else format_controlled_loop_result(result, show_timeline=show_timeline)
    print(output)
    return payload


def prepare_result_to_cli_dict(
    workflow: CodingWorkflow,
    session: CodingExecutionSession,
    *,
    show_timeline: bool = False,
) -> dict[str, Any]:
    """Serialize prepare-only results for CLI/TUI/Web without executable payloads.

    The payload summarizes plan, scope, predicted impact, validation, and guardrails. It does not
    include full file contents, full prompts, secrets, or any structure that would imply approval or
    patch application occurred.
    """

    payload: dict[str, Any] = {
        "mode": "prepare_only",
        "task": workflow.task,
        "status": session.status,
        "phase": session.phase,
        "workflow_status": workflow.status,
        "plan_summary": _plan_summary(workflow),
        "scope_summary": _scope_summary(workflow),
        "predicted_impact_summary": _impact_summary(workflow),
        "validation_summary": _validation_summary(workflow),
        "execution_guardrails": _guardrails_summary(session),
        "write_scope": write_scope_to_dict(session.write_scope) if session.write_scope is not None else None,
        "warnings": _unique([*workflow.warnings, *session.warnings]),
    }
    if show_timeline:
        payload["timeline"] = _timeline_summaries(session.timeline_blocks)
    return _json_safe(payload)


def controlled_loop_result_to_cli_dict(
    result: ControlledToolLoopResult,
    *,
    show_timeline: bool = False,
) -> dict[str, Any]:
    """Serialize a controlled loop result for CLI/TUI/Web with safe summaries only.

    Pending approvals are reduced to token, action, tool, title/summary, changed files, command, and
    scope check. Timeline blocks are compact summaries. The CLI never exposes full pending payloads,
    file contents, prompt text, or approval/apply internals.
    """

    payload: dict[str, Any] = {
        "mode": "controlled_loop",
        "task": result.task,
        "status": result.status,
        "stop_reason": result.stop_reason,
        "session_id": result.session.id,
        "runtime_execution_context": runtime_execution_context_to_dict(result.runtime_execution_context),
        "runtime_counters": runtime_execution_context_to_dict(result.runtime_execution_context)["counters"],
        "pending_approvals_count": len(result.pending_approvals),
        "pending_approvals": [_pending_approval_summary(item) for item in result.pending_approvals],
        "validation_commands": _validation_commands(result),
        "validation_outcome": validation_outcome_to_cli_dict(getattr(result, "validation_outcome", None)),
        "validation_repair": validation_repair_state_to_cli_dict(getattr(result, "validation_repair_state", None)),
        "warnings": list(result.warnings),
        "summary_text": result.summary_text,
    }
    if show_timeline:
        payload["timeline"] = _timeline_summaries(result.timeline_blocks)
    return _json_safe(payload)


def format_prepare_only_result(
    workflow: CodingWorkflow,
    session: CodingExecutionSession,
    *,
    show_timeline: bool = False,
) -> str:
    """Format prepare-only CLI output while avoiding auto-approval/apply claims.

    This renderer is deliberately concise because `pp-echo code --prepare-only` is a product entry
    point, not a debug dump. It filters timeline details and never prints file contents or secrets.
    """

    payload = prepare_result_to_cli_dict(workflow, session, show_timeline=show_timeline)
    lines = [
        "Controlled Coding Workflow",
        f"Task: {payload['task']}",
        f"Status: {payload['status']}",
        f"Phase: {payload['phase']}",
        "",
        "Task Plan:",
        f"- Risk: {payload['plan_summary']['risk_level']}",
        f"- Steps: {payload['plan_summary']['step_count']}",
    ]
    lines.extend(f"  - {step}" for step in payload["plan_summary"]["steps"])
    lines.extend(
        [
            "",
            "Task Scope:",
            f"- Edit: {_allowed(payload['scope_summary']['allow_edit'])}",
            f"- Shell: {_allowed(payload['scope_summary']['allow_shell'])}",
            f"- Delete: {_allowed(payload['scope_summary']['allow_delete'])}",
            f"- Network: {_allowed(payload['scope_summary']['allow_network'])}",
            f"- Risk: {payload['scope_summary']['risk_level']}",
            "",
            "Predicted Impact:",
            f"- Risk: {payload['predicted_impact_summary']['risk_level']}",
            f"- Modules: {_join_or_none(payload['predicted_impact_summary']['impacted_modules'])}",
            "",
            "Validation:",
        ]
    )
    lines.extend(f"- {command}" for command in payload["validation_summary"]["commands"]) if payload["validation_summary"]["commands"] else lines.append("- None")
    lines.extend(
        [
            "",
            "Execution Guardrails:",
            f"- Max tool calls: {payload['execution_guardrails']['max_tool_calls']}",
            f"- Max shell commands: {payload['execution_guardrails']['max_shell_commands']}",
            f"- Max patch candidates: {payload['execution_guardrails']['max_patch_candidates']}",
            f"- Stop on approval: {str(payload['execution_guardrails']['stop_on_approval']).lower()}",
        ]
    )
    _append_warnings(lines, payload["warnings"])
    _append_timeline(lines, payload.get("timeline"))
    return "\n".join(lines).strip()


def format_controlled_loop_result(result: ControlledToolLoopResult, *, show_timeline: bool = False) -> str:
    """Format controlled-loop CLI output without printing full payloads or applying anything.

    The renderer reports stop reason, runtime counters, pending approval summaries, validation
    recommendations, warnings, and optional compact timeline summaries. It never auto-approves or
    auto-applies pending actions.
    """

    payload = controlled_loop_result_to_cli_dict(result, show_timeline=show_timeline)
    counters = payload["runtime_counters"]
    lines = [
        "Controlled Coding Workflow",
        f"Task: {payload['task']}",
        f"Status: {payload['status']}",
        f"Stop reason: {payload['stop_reason']}",
        "",
        "Runtime Counters:",
        f"- Tool calls: {counters['tool_calls']}",
        f"- Shell commands: {counters['shell_commands']}",
        f"- Patch candidates: {counters['patch_candidates']}",
        "",
        f"Pending Approvals: {payload['pending_approvals_count']}",
    ]
    for item in payload["pending_approvals"]:
        lines.append(f"- {item['token']} {item['action_type']}: {item.get('title') or item.get('summary') or 'Pending action'}")
        if item.get("tool_name"):
            lines.append(f"  tool: {item['tool_name']}")
        if item.get("command"):
            lines.append(f"  command: {item['command']}")
        if item.get("changed_files"):
            lines.append(f"  changed files: {_join_or_none(item['changed_files'])}")
        scope_check = item.get("scope_check")
        if isinstance(scope_check, dict):
            lines.append(f"  scope: {scope_check.get('allowed')} ({scope_check.get('reason')})")
    lines.append("")
    lines.append("Validation:")
    lines.extend(f"- {command}" for command in payload["validation_commands"]) if payload["validation_commands"] else lines.append("- None")
    outcome_text = format_validation_outcome(getattr(result, "validation_outcome", None))
    if outcome_text:
        lines.extend(["", outcome_text])
    repair_text = format_validation_repair_state(getattr(result, "validation_repair_state", None))
    if repair_text:
        lines.extend(["", repair_text])
    _append_warnings(lines, payload["warnings"])
    if payload.get("summary_text"):
        lines.extend(["", "Summary:", payload["summary_text"]])
    _append_timeline(lines, payload.get("timeline"))
    return "\n".join(lines).strip()


def _plan_summary(workflow: CodingWorkflow) -> dict[str, Any]:
    plan = task_plan_to_dict(workflow.task_plan)
    return {
        "risk_level": plan["risk_level"],
        "understanding": plan["understanding"],
        "step_count": len(plan["plan_steps"]),
        "steps": [step["title"] for step in plan["plan_steps"]],
        "files_to_inspect": plan["files_to_inspect"],
        "likely_files_to_change": plan["likely_files_to_change"],
        "validation_commands": plan["validation_commands"],
        "assumptions": plan["assumptions"],
        "warnings": plan["warnings"],
    }


def _scope_summary(workflow: CodingWorkflow) -> dict[str, Any]:
    scope = task_scope_to_dict(workflow.task_scope)
    return {
        "allowed_paths": scope["allowed_paths"],
        "disallowed_paths_count": len(scope["disallowed_paths"]),
        "allow_edit": scope["allow_edit"],
        "allow_shell": scope["allow_shell"],
        "allow_delete": scope["allow_delete"],
        "allow_network": scope["allow_network"],
        "max_files_changed": scope["max_files_changed"],
        "risk_level": scope["risk_level"],
        "reason": scope["reason"],
        "warnings": scope["warnings"],
    }


def _impact_summary(workflow: CodingWorkflow) -> dict[str, Any]:
    impact = change_impact_to_dict(workflow.predicted_impact)
    return {
        "changed_paths": impact["changed_paths"],
        "impacted_modules": impact["impacted_modules"],
        "impacted_tests": impact["impacted_tests"],
        "impacted_docs": impact["impacted_docs"],
        "risk_level": impact["risk_level"],
        "reason": impact["reason"],
        "predicted_impact_not_actual": True,
        "warnings": impact["warnings"],
    }


def _validation_summary(workflow: CodingWorkflow) -> dict[str, Any]:
    plan = validation_plan_to_dict(workflow.validation_plan)
    return {
        "commands": [command["command"] for command in plan["commands"]],
        "risk_level": plan["risk_level"],
        "reason": plan["reason"],
        "warnings": plan["warnings"],
    }


def _guardrails_summary(session: CodingExecutionSession) -> dict[str, Any]:
    guardrails = session.guardrails
    return {
        "max_tool_calls": guardrails.max_tool_calls,
        "max_shell_commands": guardrails.max_shell_commands,
        "max_patch_candidates": guardrails.max_patch_candidates,
        "stop_on_approval": guardrails.stop_on_approval,
        "stop_on_scope_block": guardrails.stop_on_scope_block,
        "stop_on_test_failure": guardrails.stop_on_test_failure,
    }


def _validation_commands(result: ControlledToolLoopResult) -> list[str]:
    if result.validation_plan is None:
        return []
    return [command.command for command in result.validation_plan.commands]


def validation_outcome_to_cli_dict(outcome: ValidationOutcome | None) -> dict[str, Any]:
    """Return a redacted, stable CLI summary for one typed ValidationOutcome."""

    if outcome is None:
        return {
            "present": False,
            "final_status": "not_run",
            "repair_attempted": False,
            "revalidation_attempted": False,
            "explanation": "Validation outcome is not available.",
        }
    observation = outcome.observation
    command: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None
    if observation is not None:
        command = {
            "command_id": observation.command_id,
            "normalized_command": observation.normalized_command,
            "target": observation.target,
        }
        diagnostics = {
            "execution_status": observation.execution_status,
            "validation_status": observation.validation_status,
            "exit_code": observation.exit_code,
            "failure_kind": observation.failure_kind,
            "failure_summary": observation.failure_summary,
            "timed_out": observation.timed_out,
            "stdout_truncated": observation.stdout_truncated,
            "stderr_truncated": observation.stderr_truncated,
            "stdout_chars": observation.stdout_chars,
            "stderr_chars": observation.stderr_chars,
            "pytest_provenance_status": observation.pytest_provenance_status,
            "pytest_completion_category": observation.pytest_completion_category,
            "pytest_exit_status": observation.pytest_exit_status,
            "repair_eligible": observation.repair_eligible,
        }
    return _json_safe(
        {
            "present": True,
            "final_status": outcome.final_status,
            "repair_attempted": outcome.repair_attempted,
            "revalidation_attempted": outcome.revalidation_attempted,
            "command": command,
            "diagnostics": diagnostics,
            "explanation": explain_validation_outcome(outcome),
        }
    )


def validation_repair_state_to_cli_dict(state: ValidationRepairCycleState | None) -> dict[str, Any]:
    """Return a redacted, stable CLI summary for one bounded repair cycle state."""

    if state is None:
        return {"present": False}
    return _json_safe(
        {
            "present": True,
            "status": state.status,
            "repair_attempted": state.repair_attempted,
            "revalidation_attempted": state.revalidation_attempted,
            "validation_executions": state.validation_executions,
            "initial_validation": validation_outcome_to_cli_dict(state.initial_result.outcome),
            "revalidation": validation_outcome_to_cli_dict(state.revalidation_result.outcome)
            if state.revalidation_result is not None
            else None,
            "final_outcome": validation_outcome_to_cli_dict(state.final_outcome),
            "explanation": _repair_state_explanation(state),
        }
    )


def format_validation_outcome(outcome: ValidationOutcome | None) -> str:
    """Format a typed validation outcome for human-readable CLI output."""

    payload = validation_outcome_to_cli_dict(outcome)
    if not payload.get("present"):
        return ""
    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
    command = payload.get("command") if isinstance(payload.get("command"), dict) else {}
    lines = [
        "Validation Outcome:",
        f"- Final status: {payload['final_status']}",
        f"- Repair attempted: {str(payload['repair_attempted']).lower()}",
        f"- Re-validation attempted: {str(payload['revalidation_attempted']).lower()}",
        f"- Explanation: {payload['explanation']}",
    ]
    normalized_command = command.get("normalized_command")
    if normalized_command:
        lines.append(f"- Command: {normalized_command}")
    if diagnostics:
        lines.extend(
            [
                f"- Execution: {diagnostics.get('execution_status')}",
                f"- Validation: {diagnostics.get('validation_status')}",
                f"- Pytest category: {diagnostics.get('pytest_completion_category') or 'none'}",
                f"- Failure kind: {diagnostics.get('failure_kind') or 'none'}",
                f"- Truncated output: stdout={str(diagnostics.get('stdout_truncated')).lower()} stderr={str(diagnostics.get('stderr_truncated')).lower()}",
            ]
        )
    return "\n".join(lines).strip()


def format_validation_repair_state(state: ValidationRepairCycleState | None) -> str:
    """Format one bounded repair state without exposing internal provenance details."""

    payload = validation_repair_state_to_cli_dict(state)
    if not payload.get("present"):
        return ""
    lines = [
        "Validation Repair:",
        f"- Status: {payload['status']}",
        f"- Repair attempted: {str(payload['repair_attempted']).lower()}",
        f"- Re-validation attempted: {str(payload['revalidation_attempted']).lower()}",
        f"- Validation executions: {payload['validation_executions']}",
        f"- Explanation: {payload['explanation']}",
    ]
    return "\n".join(lines).strip()


def explain_validation_outcome(outcome: ValidationOutcome | None) -> str:
    """Explain a ValidationOutcome using typed fields only."""

    if outcome is None or outcome.observation is None:
        return "Validation has not run."
    observation = outcome.observation
    if observation.execution_status == "not_executed":
        if outcome.final_status == "approval_pending":
            return "Validation is awaiting approval and has not executed."
        return "Validation did not execute."
    if outcome.final_status == "approval_pending":
        return "Validation or re-validation is awaiting approval."
    if observation.execution_status == "blocked" or outcome.final_status == "blocked":
        if observation.pytest_provenance_status in {"invalid", "missing"}:
            return "Validation is blocked because pytest provenance was not trusted."
        if observation.timed_out:
            return "Validation is blocked because execution timed out."
        return "Validation is blocked by execution or infrastructure failure."
    if outcome.final_status == "passed":
        return "Validation passed." if not outcome.repair_attempted else "Repair was attempted and re-validation passed."
    if outcome.final_status == "failed":
        if observation.pytest_completion_category == "tests_failed" and observation.pytest_provenance_status == "valid":
            if outcome.repair_attempted:
                return "Repair was attempted, but trusted re-validation still reported tests_failed."
            return "Trusted pytest provenance reported tests_failed; repair is eligible."
        return "Validation failed by typed status, but repair is not eligible without trusted tests_failed provenance."
    if outcome.final_status == "validation_nonzero":
        category = observation.pytest_completion_category
        if category in {"internal_error", "usage_error", "no_tests_collected", "interrupted", "unknown"}:
            return f"Pytest completed with {category}; this is not a genuine tests_failed repair trigger."
        return "Validation returned nonzero without trusted tests_failed provenance."
    return f"Validation final status is {outcome.final_status}."


def _repair_state_explanation(state: ValidationRepairCycleState) -> str:
    if state.status == "not_repairable":
        return "Repair did not start because the initial validation outcome was not trusted tests_failed."
    if state.status == "repair_pending":
        return "Repair started and is awaiting existing tool approval."
    if state.status == "repair_blocked":
        return "Repair started but was blocked before re-validation."
    if state.status == "revalidation_pending":
        return "Repair completed and same-command re-validation is awaiting approval."
    if state.status == "completed":
        return "The bounded repair cycle completed."
    return f"Repair cycle status is {state.status}."


def _pending_approval_summary(item: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = ("token", "action_type", "tool_name", "title", "summary", "changed_files", "command", "scope_check")
    summary = {key: item.get(key) for key in allowed_keys if key in item}
    if isinstance(summary.get("scope_check"), dict):
        scope = summary["scope_check"]
        summary["scope_check"] = {
            "allowed": scope.get("allowed"),
            "reason": scope.get("reason"),
            "matched_rule": scope.get("matched_rule"),
            "risk_level": scope.get("risk_level"),
        }
    return summary


def _timeline_summaries(blocks: list[Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for block in blocks or []:
        payload = to_jsonable(block)
        if not isinstance(payload, dict):
            continue
        summaries.append(
            {
                "type": payload.get("type"),
                "title": payload.get("title"),
                "status": payload.get("status"),
                "details": _compact_timeline_details(payload.get("details")),
            }
        )
    return summaries


def _compact_timeline_details(details: Any) -> dict[str, Any]:
    mapping = details if isinstance(details, dict) else {}
    compact: dict[str, Any] = {}
    for key in (
        "risk_level",
        "scope_risk_level",
        "impact_risk_level",
        "status",
        "phase",
        "stop_reason",
        "pending_approvals_count",
        "predicted_impact_not_actual",
    ):
        if key in mapping:
            compact[key] = mapping[key]
    if isinstance(mapping.get("validation_commands"), list):
        compact["validation_commands"] = list(mapping["validation_commands"])[:5]
    if isinstance(mapping.get("guardrails"), dict):
        compact["guardrails"] = dict(mapping["guardrails"])
    if isinstance(mapping.get("write_scope"), dict):
        scope = mapping["write_scope"]
        compact["write_scope"] = {
            "allowed_paths_count": len(scope.get("allowed_paths") or []),
            "disallowed_paths_count": len(scope.get("disallowed_paths") or []),
            "allow_delete": scope.get("allow_delete"),
            "max_files_changed": scope.get("max_files_changed"),
            "risk_level": scope.get("risk_level"),
            "source": scope.get("source"),
        }
    return compact


def _json_safe(payload: Any) -> Any:
    return to_jsonable(payload)


def _append_warnings(lines: list[str], warnings: list[str]) -> None:
    if not warnings:
        return
    lines.extend(["", "Warnings:"])
    lines.extend(f"- {warning}" for warning in warnings)


def _append_timeline(lines: list[str], timeline: Any) -> None:
    if not timeline:
        return
    lines.extend(["", "Timeline:"])
    for item in timeline:
        lines.append(f"- {item.get('type')}: {item.get('title')} [{item.get('status')}]")


def _allowed(value: Any) -> str:
    return "allowed" if bool(value) else "denied"


def _join_or_none(values: list[str]) -> str:
    return ", ".join(values) if values else "None"


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


__all__ = [
    "controlled_loop_result_to_cli_dict",
    "explain_validation_outcome",
    "format_controlled_loop_result",
    "format_prepare_only_result",
    "format_validation_outcome",
    "format_validation_repair_state",
    "prepare_result_to_cli_dict",
    "run_code_command",
    "validation_outcome_to_cli_dict",
    "validation_repair_state_to_cli_dict",
]
