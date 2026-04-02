from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pp_agent.app.bootstrap import create_tool_registry
from pp_agent.cli.commands.approvals import approve_or_execute_pending_action, approvals_summary_payload
from pp_agent.cli.render.runtime import console


def workflow_repo_main(
    workspace: Path,
    query: Optional[str] = None,
    token: Optional[str] = None,
    auto_apply: bool = False,
    path_filter: Optional[str] = None,
    staged_only: bool = False,
) -> None:
    registry = create_tool_registry(workspace)
    payload = {"planner": [], "executor": [], "next_actions": []}
    target_path = path_filter
    if query:
        payload["planner"].append({"step": "Search the codebase for relevant symbols or text.", "status": "planned"})
        grep_args = {"query": query}
        if path_filter:
            grep_args["path"] = path_filter
        grep = registry.execute("grep_code", grep_args)
        payload["executor"].append({"step": "Run grep_code", "status": "done", "content": grep.content, "details": grep.details})
        payload["next_actions"].append("Review grep results and decide which file to change.")
    payload["planner"].append({"step": "Inspect staged actions before applying anything.", "status": "planned"})
    summary = approvals_summary_payload(workspace)
    payload["executor"].append({"step": "Inspect pending actions", "status": "done", "details": {"count": summary["count"], "by_type": summary["by_type"]}})
    if token:
        payload["planner"].append({"step": f"Preview the staged action for token {token}.", "status": "planned"})
        preview = registry.execute("preview_pending_action", {"token": token})
        target_path = preview.details.get("target_path") or target_path
        payload["executor"].append({"step": "Preview staged action", "status": "done", "content": preview.content, "details": preview.details})
        payload["next_actions"].append("Check the preview diff, shell command, or planner summary before approving it.")
        if auto_apply:
            payload["planner"].append({"step": "Approve the token and let execution continue.", "status": "planned"})
            applied = approve_or_execute_pending_action(workspace, token, render=False)
            payload["executor"].append({"step": "Approve and execute staged action", "status": "done", "details": applied})
            payload["next_actions"].append("Inspect git status and git diff after applying the action.")
        else:
            payload["planner"].append({"step": f"Approve token {token} when the preview looks correct.", "status": "pending"})
    payload["planner"].append({"step": "Inspect repository state after the planned change.", "status": "planned"})
    status = registry.execute("git_status", {})
    diff_args = {}
    if staged_only and target_path:
        diff_args["path"] = target_path
    elif path_filter:
        diff_args["path"] = path_filter
    diff = registry.execute("git_diff_worktree", diff_args)
    payload["executor"].append({"step": "Inspect git status", "status": "done", "content": status.content, "details": status.details})
    payload["executor"].append({"step": "Inspect git diff", "status": "done", "content": diff.content, "details": diff.details})
    if not token:
        payload["next_actions"].append("Stage an edit, shell action, or planner approval, then re-run workflow repo with --token.")
    if staged_only and not target_path:
        payload["next_actions"].append("No target path found for staged-only diff; provide --path-filter or a token tied to a file action.")
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))


__all__ = ["workflow_repo_main"]
