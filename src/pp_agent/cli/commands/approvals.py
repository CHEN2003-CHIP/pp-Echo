from __future__ import annotations

import json
import time
from pathlib import Path

from pp_agent.api import sdk
from pp_agent.app.bootstrap import create_tool_registry, pending_action_store_for
from pp_agent.runtime import AgentRuntime
from pp_agent.tools.base import ToolExecutionResult
from pp_agent.cli.render.approvals import approvals_summary_payload, render_approval_panel
from pp_agent.cli.render.runtime import console, render_event


def load_pending_action(workspace: Path, token: str) -> dict:
    return pending_action_store_for(workspace).load(token)


def explain_missing_pending_action(token: str) -> str:
    normalized = token.strip()
    if normalized.lower() == "list":
        return "Use /approvals in chat mode, or run `pp-agent approvals list` in the shell to list pending actions."
    return f"Pending action token not found: {normalized}. Use /approvals to inspect available tokens."


def load_pending_action_or_user_error(workspace: Path, token: str) -> dict:
    try:
        return load_pending_action(workspace, token)
    except FileNotFoundError as exc:
        raise ValueError(explain_missing_pending_action(token)) from exc


def _payload_session_id(payload: dict) -> str:
    details = payload.get("details", {}) if isinstance(payload.get("details"), dict) else {}
    return str(payload.get("session_id") or details.get("session_id") or "").strip()


def _external_approval_base_result(
    payload: dict,
    token: str,
    action: str,
    result: ToolExecutionResult,
    *,
    session_id: str,
) -> dict:
    details = payload.get("details", {}) if isinstance(payload.get("details"), dict) else {}
    lifecycle = result.details.get("lifecycle") if isinstance(result.details, dict) else None
    if lifecycle is None:
        lifecycle = payload.get("lifecycle") or {}
    return {
        "token": token,
        "action_type": payload["action_type"],
        "session_id": session_id,
        "turn_id": payload.get("turn_id") or details.get("turn_id"),
        "tool_call_id": payload.get("tool_call_id") or details.get("tool_call_id"),
        "source_tool_name": details.get("tool_name") or result.tool_name or payload["action_type"],
        "result": result.content,
        "success": not result.is_error,
        "lifecycle": lifecycle,
        "details": result.details or {},
        "approval_action": action,
        "approved": action == "approve" and not result.is_error,
        "rejected": action == "reject",
        "timestamp": time.time(),
    }


def _record_and_maybe_resume(
    workspace: Path,
    runtime: AgentRuntime | None,
    result: dict,
    *,
    resume: bool,
    render: bool,
) -> dict:
    session_id = str(result.get("session_id") or "").strip()
    if not session_id:
        return {**result, "resumed": False, "event_count": 0}
    agent = runtime if runtime is not None and runtime.session_id == session_id else sdk.restore_session(workspace, session_id)
    if runtime is None and render:
        agent.subscribe(render_event)
    agent.record_external_approval_result(result)
    events = agent.continue_() if resume else []
    return {**result, "resumed": resume, "event_count": len(events)}


def approve_or_execute_pending_action(workspace: Path, token: str, render: bool = True, *, runtime: AgentRuntime | None = None) -> dict:
    payload = load_pending_action_or_user_error(workspace, token)
    if payload["action_type"] == "planner_approval":
        session_id = _payload_session_id(payload)
        if not session_id:
            raise ValueError("planner_approval token is missing session_id")
        agent = runtime if runtime is not None and runtime.session_id == session_id else sdk.restore_session(workspace, session_id)
        if runtime is None and render:
            agent.subscribe(render_event)
        events = agent.approve_pending_plan(token)
        if render:
            console.print()
        return {
            "token": token,
            "action_type": payload["action_type"],
            "session_id": session_id,
            "event_count": len(events),
            "result": "approved_and_executed",
            "resumed": True,
        }
    registry = create_tool_registry(workspace, include_dynamic_extensions=True)
    try:
        result = registry.host_execute("approve_pending_action", {"token": token})
    except Exception as exc:  # noqa: BLE001
        lifecycle = {"state": "execution_failed", "updated_at": time.time(), "failure_reason_code": "approval_execution_error", "failure_reason_detail": str(exc)}
        details = payload.get("details", {}) if isinstance(payload.get("details"), dict) else {}
        failure_result = ToolExecutionResult(
            tool_call_id=str(payload.get("tool_call_id") or details.get("tool_call_id") or token or ""),
            tool_name="approve_pending_action",
            content=str(exc),
            is_error=True,
            details={"error": str(exc), "token": token, "action_type": payload["action_type"], "lifecycle": lifecycle},
        )
        response = _external_approval_base_result(payload, token, "approve", failure_result, session_id=_payload_session_id(payload))
        response["success"] = False
        response["lifecycle"] = lifecycle
        response["details"] = failure_result.details
        if render:
            console.print(failure_result.content)
        return _record_and_maybe_resume(workspace, runtime, response, resume=False, render=render)
    finally:
        extension_runtime = getattr(registry, "_extension_runtime", None)
        if extension_runtime is not None:
            extension_runtime.close()
    if render:
        console.print(result.content)
        if result.details:
            console.print(json.dumps(result.details, ensure_ascii=False, indent=2))
    response = _external_approval_base_result(
        payload,
        token,
        "approve",
        result,
        session_id=_payload_session_id(payload),
    )
    return _record_and_maybe_resume(workspace, runtime, response, resume=True, render=render)


def reject_pending_action(workspace: Path, token: str, render: bool = True, *, runtime: AgentRuntime | None = None) -> dict:
    payload = load_pending_action_or_user_error(workspace, token)
    if payload["action_type"] == "planner_approval":
        session_id = _payload_session_id(payload)
        if not session_id:
            raise ValueError("planner_approval token is missing session_id")
        agent = runtime if runtime is not None and runtime.session_id == session_id else sdk.restore_session(workspace, session_id)
        agent.reject_pending_plan(token)
        message = f"Rejected planner approval {token} for session {session_id}"
        if render:
            console.print(message)
        return {"token": token, "action_type": payload["action_type"], "result": message, "resumed": False, "session_id": session_id}
    registry = create_tool_registry(workspace, include_dynamic_extensions=True)
    try:
        result = registry.host_execute("reject_pending_action", {"token": token})
    except Exception as exc:  # noqa: BLE001
        details = payload.get("details", {}) if isinstance(payload.get("details"), dict) else {}
        lifecycle = {"state": "rejected", "updated_at": time.time(), "failure_reason_code": "approval_reject_error", "failure_reason_detail": str(exc)}
        failure_result = ToolExecutionResult(
            tool_call_id=str(payload.get("tool_call_id") or details.get("tool_call_id") or token or ""),
            tool_name="reject_pending_action",
            content=str(exc),
            is_error=True,
            details={"error": str(exc), "token": token, "action_type": payload["action_type"], "lifecycle": lifecycle},
        )
        response = _external_approval_base_result(payload, token, "reject", failure_result, session_id=_payload_session_id(payload))
        response["success"] = False
        response["lifecycle"] = lifecycle
        response["details"] = failure_result.details
        if render:
            console.print(failure_result.content)
        return _record_and_maybe_resume(workspace, runtime, response, resume=False, render=render)
    finally:
        extension_runtime = getattr(registry, "_extension_runtime", None)
        if extension_runtime is not None:
            extension_runtime.close()
    if render:
        console.print(result.content)
    response = _external_approval_base_result(
        payload,
        token,
        "reject",
        result,
        session_id=_payload_session_id(payload),
    )
    return _record_and_maybe_resume(workspace, runtime, response, resume=True, render=render)


def approvals_list_main(workspace: Path) -> None:
    store = pending_action_store_for(workspace)
    console.print(json.dumps(store.list(), ensure_ascii=False, indent=2))


def approvals_summary_main(workspace: Path) -> None:
    render_approval_panel(workspace)


def approvals_show_main(workspace: Path, token: str) -> None:
    registry = create_tool_registry(workspace, include_dynamic_extensions=True)
    try:
        result = registry.host_execute("preview_pending_action", {"token": token})
    finally:
        extension_runtime = getattr(registry, "_extension_runtime", None)
        if extension_runtime is not None:
            extension_runtime.close()
    console.print(f"Token: {token}")
    console.print(result.content)
    console.print(json.dumps(result.details, ensure_ascii=False, indent=2))


def approvals_approve_main(workspace: Path, token: str) -> None:
    approve_or_execute_pending_action(workspace, token, render=True)


def approvals_reject_main(workspace: Path, token: str) -> None:
    reject_pending_action(workspace, token, render=True)


def approvals_approve_all_main(workspace: Path) -> None:
    store = pending_action_store_for(workspace)
    tokens = [item["token"] for item in store.list()]
    results = [approve_or_execute_pending_action(workspace, token, render=False) for token in tokens]
    console.print(json.dumps(results, ensure_ascii=False, indent=2))


def approvals_reject_all_main(workspace: Path) -> None:
    store = pending_action_store_for(workspace)
    tokens = [item["token"] for item in store.list()]
    results = [reject_pending_action(workspace, token, render=False) for token in tokens]
    console.print(json.dumps(results, ensure_ascii=False, indent=2))


__all__ = [
    "approve_or_execute_pending_action",
    "approvals_approve_all_main",
    "approvals_approve_main",
    "approvals_list_main",
    "approvals_reject_all_main",
    "approvals_reject_main",
    "approvals_show_main",
    "approvals_summary_main",
    "approvals_summary_payload",
    "explain_missing_pending_action",
    "load_pending_action",
    "load_pending_action_or_user_error",
    "reject_pending_action",
]
