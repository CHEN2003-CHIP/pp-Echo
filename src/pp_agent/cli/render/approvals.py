from __future__ import annotations

from pathlib import Path

from pp_agent.api import sdk
from pp_agent.cli.render.runtime import compact_text, console


def approvals_summary_payload(workspace: Path) -> dict:
    return sdk.approvals_summary(workspace)


def short_token(token: str) -> str:
    return token[:8]


def action_target(item: dict) -> str:
    if item["action_type"] == "planner_approval":
        return f"session={item.get('details', {}).get('session_id', '')}"
    return item.get("target_path") or item.get("command") or ""


def approval_preview(item: dict, limit: int = 8) -> str:
    if item["action_type"] == "run_shell":
        return compact_text(item.get("command") or "")
    if item["action_type"] == "planner_approval":
        summary = item.get("details", {}).get("summary", []) or []
        return "\n".join(summary[:limit]) if summary else "Planner approval with no summary available."
    diff_text = item.get("details", {}).get("diff", "") or ""
    lines = [line for line in diff_text.splitlines() if line.strip()]
    return "\n".join(lines[:limit]) if lines else "No diff preview."


def render_approval_panel(workspace: Path) -> None:
    summary = approvals_summary_payload(workspace)
    items = summary["items"]
    lines = ["Approvals Queue", f"Total: {summary['count']}", f"By type: {summary['by_type']}"]
    if not items:
        lines.append("No pending actions.")
        console.print("\n".join(lines))
        return
    for item in items[:5]:
        lines.append("")
        lines.append(f"[{short_token(item['token'])}] {item['action_type']}")
        lines.append(f"Target: {compact_text(action_target(item), 110)}")
        lines.append("Preview:")
        lines.append(approval_preview(item, limit=6))
    if len(items) > 5:
        lines.append("")
        lines.append(f"... {len(items) - 5} more pending actions")
    console.print("\n".join(lines))


__all__ = [
    "approval_preview",
    "approvals_summary_payload",
    "render_approval_panel",
    "short_token",
]
