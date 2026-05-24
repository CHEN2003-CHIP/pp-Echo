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


def lifecycle_label(item: dict) -> str:
    return (item.get("lifecycle") or {}).get("state", "unknown")


def approval_preview(item: dict, limit: int = 8) -> str:
    if item["action_type"] == "run_shell":
        return compact_text(item.get("command") or "")
    if item["action_type"] == "planner_approval":
        summary = item.get("details", {}).get("summary", []) or []
        return "\n".join(summary[:limit]) if summary else "Planner approval with no summary available."
    diff_text = item.get("details", {}).get("diff", "") or ""
    lines = [line for line in diff_text.splitlines() if line.strip()]
    return "\n".join(lines[:limit]) if lines else "No diff preview."


def approval_actions(item: dict) -> list[str]:
    token = item["token"]
    return [f"/approvals show {token}", f"/approve {token}", f"/reject {token}"]


def render_approval_panel(workspace: Path) -> None:
    summary = approvals_summary_payload(workspace)
    items = summary.get("active_items") or summary["items"]
    lines = [
        "== Approvals Queue ==",
        f"active    {summary.get('active_count', summary['count'])}",
        f"total     {summary['count']}",
        f"by_type   {summary['by_type']}",
    ]
    if not items:
        archived_count = summary.get("archived_count", 0)
        if archived_count:
            lines.extend(["", f"No active pending actions. {archived_count} archived item(s) are hidden."])
        else:
            lines.extend(["", "No pending actions."])
        console.print("\n".join(lines))
        return
    for item in items[:5]:
        details = item.get("details", {}) or {}
        lines.append("")
        lines.append(f"-- {item['action_type']} [{lifecycle_label(item)}] --")
        lines.append(f"token     {item['token']}")
        lines.append(f"target    {compact_text(action_target(item), 110)}")
        if item["action_type"] == "planner_approval":
            summary_lines = details.get("summary") or []
            files = details.get("files_touched_guess") or []
            shell = details.get("shell_commands_guess") or []
            high_risk = details.get("high_risk_tools") or []
            if summary_lines:
                lines.append("summary")
                lines.extend(f"- {line}" for line in summary_lines[:4])
            if files:
                lines.append(f"files     {', '.join(files[:4])}")
            if shell:
                lines.append(f"shell     {', '.join(shell[:3])}")
            if high_risk:
                lines.append(f"high_risk {', '.join(high_risk[:4])}")
        else:
            lines.append("preview")
            lines.append(approval_preview(item, limit=6))
        lines.append(f"actions   {' | '.join(approval_actions(item))}")
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
