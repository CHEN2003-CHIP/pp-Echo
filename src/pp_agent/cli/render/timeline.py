from __future__ import annotations

from datetime import datetime

from pp_agent.cli.render.runtime import compact_text, console


def render_timeline(entries) -> None:
    lines = ["Agent Timeline", f"Total: {len(entries)}"]
    if not entries:
        lines.append("No timeline entries yet.")
        console.print("\n".join(lines))
        return
    for entry in entries:
        timestamp = datetime.fromtimestamp(entry.created_at).strftime("%H:%M:%S")
        phase = entry.phase or (entry.runtime.phase if entry.runtime is not None else "-")
        tool = f" tool={entry.tool_name}" if entry.tool_name else ""
        message = compact_text(entry.message or "", limit=100)
        lines.append(f"{timestamp} turn={entry.turn_id} {entry.event_type} phase={phase}{tool}")
        if message:
            lines.append(f"  message: {message}")
        if entry.plan_step is not None:
            lines.append(f"  plan: {entry.plan_step.title} [{entry.plan_step.status}]")
        if entry.details.get("action"):
            lines.append(f"  action: {entry.details.get('action')} {entry.details.get('delivery', '')}".rstrip())
    console.print("\n".join(lines))


__all__ = ["render_timeline"]
