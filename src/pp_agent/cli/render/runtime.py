from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

try:
    from rich.console import Console

    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover
    import sys

    RICH_AVAILABLE = False

    class Console:  # type: ignore[override]
        def print(self, *args, end: str = "\n", **kwargs) -> None:
            text = " ".join(str(arg) for arg in args)
            encoding = sys.stdout.encoding or "utf-8"
            safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
            print(safe, end=end)


from pp_agent.app.bootstrap import load_settings, timeline_store_for
from pp_agent.runtime import AgentEvent, AgentRuntime, RuntimeMonitor
from pp_agent.storage.timeline import TimelineStore


console = Console()
RUNTIME_MONITOR = RuntimeMonitor()
PLAN_MARKERS = {
    "pending": "[ ]",
    "awaiting_approval": "[?]",
    "in_progress": "[~]",
    "completed": "[x]",
    "failed": "[!]",
}


def compact_text(value: str, limit: int = 90) -> str:
    text = value.replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def format_plan_step(step) -> str:
    tool_part = f" [{step.tool_name}]" if step.tool_name else ""
    marker = PLAN_MARKERS.get(step.status, "[-]")
    return f"{marker} {step.title}{tool_part}"


def format_runtime_status(snapshot) -> str:
    return RUNTIME_MONITOR.format(snapshot)


def render_runtime_status(agent: AgentRuntime) -> None:
    snapshot = agent.runtime_monitor.snapshot_from_state(agent.state)
    console.print(format_runtime_status(snapshot))


def render_event(event: AgentEvent) -> None:
    if event.type == "message_delta" and event.delta:
        console.print(event.delta, end="")
    elif event.type == "planner_start":
        console.print("\n=== Planner ===")
        console.print("Planned steps:")
    elif event.type == "planner_step" and event.plan_step is not None:
        if event.plan_step.status == "pending":
            console.print(f"  {format_plan_step(event.plan_step)}")
        else:
            console.print(f"Planner update: {format_plan_step(event.plan_step)}")
    elif event.type == "planner_end":
        token = event.details.get("token")
        if event.details.get("requires_approval"):
            console.print(f"Planner paused. Approve with /approve {token} or reject with /reject {token}")
        else:
            console.print("=== Executor ===")
    elif event.type == "tool_start":
        console.print(f"Start {event.tool_name} {event.tool_args}")
    elif event.type == "tool_end":
        label = "error" if event.is_error else "done"
        console.print(f"{label.upper()} {event.tool_name}: {event.message}")
    elif event.type == "compaction":
        console.print(f"[Runtime] context compacted: {event.details}")
    elif event.type == "queue_update":
        action = event.details.get("action")
        delivery = event.details.get("delivery")
        text_value = compact_text(event.details.get("text", ""), limit=80)
        console.print(f"[Queue] {action} {delivery}: {text_value}")
        snapshot = RUNTIME_MONITOR.snapshot_from_event(event)
        if snapshot is not None:
            console.print(format_runtime_status(snapshot))
    elif event.type == "turn_state":
        snapshot = RUNTIME_MONITOR.snapshot_from_event(event)
        if snapshot is not None:
            console.print(format_runtime_status(snapshot))
    elif event.type == "error":
        console.print(f"[Error] {event.message}")


def render_settings(agent: AgentRuntime, workspace: Path) -> None:
    settings = load_settings(workspace)
    payload = {
        "workspace": str(settings.workspace),
        "timeline_dir": str(timeline_store_for(workspace).root),
        "session_id": agent.session_id,
        "base_url": agent.llm_client.provider.base_url,
        "model": agent.llm_client.model.model,
        "enable_thinking": agent.llm_client.model.enable_thinking,
        "shell_timeout_seconds": settings.tool_policy.shell_timeout_seconds,
        "confirm_high_risk_plan": settings.tool_policy.confirm_high_risk_plan,
        "pending_plan_token": agent.state.pending_plan_token,
        "pending_tool_call_count": len(agent.state.pending_tool_calls),
        "queued_message_count": len(agent.state.queued_messages),
        "summary_length": len(agent.state.compaction.summary),
        "summarized_message_count": agent.state.compaction.summarized_message_count,
    }
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))


def load_timeline_entries(store: TimelineStore, session_id: Optional[str], limit: int) -> list:
    if session_id:
        return store.list_session(session_id, limit=limit)
    return store.list_recent(limit=limit)


__all__ = [
    "PLAN_MARKERS",
    "RICH_AVAILABLE",
    "RUNTIME_MONITOR",
    "compact_text",
    "console",
    "format_plan_step",
    "format_runtime_status",
    "load_timeline_entries",
    "render_event",
    "render_runtime_status",
    "render_settings",
]
