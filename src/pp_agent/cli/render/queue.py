from __future__ import annotations

from pp_agent.cli.render.runtime import compact_text, console
from pp_agent.runtime import AgentRuntime


def render_queue_panel(agent: AgentRuntime) -> None:
    items = agent.list_queued_messages()
    lines = ["Message Queue", f"Total: {len(items)}"]
    if not items:
        lines.append("No queued steering or follow-up messages.")
        console.print("\n".join(lines))
        return
    for item in items[:8]:
        lines.append("")
        lines.append(f"[{item.delivery}] {item.id[:8]}")
        lines.append(compact_text(item.text, limit=120))
    if len(items) > 8:
        lines.append("")
        lines.append(f"... {len(items) - 8} more queued messages")
    console.print("\n".join(lines))


__all__ = ["render_queue_panel"]
