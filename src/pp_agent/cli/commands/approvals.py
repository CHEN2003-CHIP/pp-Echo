from __future__ import annotations

import json
from pathlib import Path

from pp_agent.api import sdk
from pp_agent.app.bootstrap import create_tool_registry, pending_action_store_for
from pp_agent.cli.render.approvals import approvals_summary_payload, render_approval_panel
from pp_agent.cli.render.runtime import console, render_event


def load_pending_action(workspace: Path, token: str) -> dict:
    return pending_action_store_for(workspace).load(token)


def approve_or_execute_pending_action(workspace: Path, token: str, render: bool = True) -> dict:
    payload = load_pending_action(workspace, token)
    if payload["action_type"] == "planner_approval":
        session_id = payload.get("details", {}).get("session_id")
        if not session_id:
            raise ValueError("planner_approval token is missing session_id")
        agent = sdk.restore_session(workspace, session_id)
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
        }
    registry = create_tool_registry(workspace)
    result = registry.host_execute("approve_pending_action", {"token": token})
    if render:
        console.print(result.content)
        if result.details:
            console.print(json.dumps(result.details, ensure_ascii=False, indent=2))
    return {"token": token, "action_type": payload["action_type"], "result": result.content}


def reject_pending_action(workspace: Path, token: str, render: bool = True) -> dict:
    payload = load_pending_action(workspace, token)
    if payload["action_type"] == "planner_approval":
        session_id = payload.get("details", {}).get("session_id")
        if not session_id:
            raise ValueError("planner_approval token is missing session_id")
        agent = sdk.restore_session(workspace, session_id)
        agent.reject_pending_plan(token)
        message = f"Rejected planner approval {token} for session {session_id}"
        if render:
            console.print(message)
        return {"token": token, "action_type": payload["action_type"], "result": message}
    registry = create_tool_registry(workspace)
    result = registry.host_execute("reject_pending_action", {"token": token})
    if render:
        console.print(result.content)
    return {"token": token, "action_type": payload["action_type"], "result": result.content}


def approvals_list_main(workspace: Path) -> None:
    store = pending_action_store_for(workspace)
    console.print(json.dumps(store.list(), ensure_ascii=False, indent=2))


def approvals_summary_main(workspace: Path) -> None:
    render_approval_panel(workspace)


def approvals_show_main(workspace: Path, token: str) -> None:
    registry = create_tool_registry(workspace)
    result = registry.host_execute("preview_pending_action", {"token": token})
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
    "load_pending_action",
    "reject_pending_action",
]
