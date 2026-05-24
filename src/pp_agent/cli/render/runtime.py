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
from pp_agent.domain import TextPart
from pp_agent.runtime import AgentEvent, AgentRuntime, RuntimeMonitor
from pp_agent.storage.timeline import TimelineStore


console = Console()
RUNTIME_MONITOR = RuntimeMonitor()
EMPTY_TURN_FALLBACK = "No visible reply this turn; the model returned no usable answer."
TURN_COMPLETE_MARKER = "[Done] turn complete"
PLAN_MARKERS = {
    "pending": "[ ]",
    "awaiting_approval": "[?]",
    "in_progress": "[~]",
    "completed": "[x]",
    "failed": "[!]",
}


def render_kv_block(title: str, rows: list[tuple[str, str]], bullets: Optional[list[str]] = None) -> None:
    console.print(f"== {title} ==")
    for key, value in rows:
        if value:
            console.print(f"{key:<10} {value}")
    if bullets:
        for bullet in bullets:
            console.print(f"- {bullet}")


def compact_text(value: str, limit: int = 90) -> str:
    text = value.replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def format_plan_step(step) -> str:
    tool_part = f" [{step.tool_name}]" if step.tool_name else ""
    marker = PLAN_MARKERS.get(step.status, "[-]")
    return f"{marker} {step.title}{tool_part}"


def summarize_tool_args(arguments: object, limit: int = 120) -> str:
    if not arguments:
        return "{}"
    try:
        payload = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
    except TypeError:
        payload = str(arguments)
    return compact_text(payload, limit=limit)


def format_runtime_status(snapshot) -> str:
    return RUNTIME_MONITOR.format(snapshot)


def render_runtime_status(agent: AgentRuntime) -> None:
    snapshot = agent.runtime_monitor.snapshot_from_state(agent.state)
    console.print(format_runtime_status(snapshot))


class ChatEventRenderer:
    def __init__(self, agent: AgentRuntime) -> None:
        self.agent = agent
        self._current_turn_id = 0
        self._streamed_assistant_text = False
        self._visible_output = False
        self._turn_start_message_count = 0
        self._turn_final_text_signature: str | None = None
        self._last_rendered_assistant_index = -1
        self._last_completed_turn_id = -1

    def render(self, event: AgentEvent) -> None:
        if event.type == "turn_start":
            self._current_turn_id = int(event.details.get("turn_id") or event.turn_id or self._current_turn_id + 1)
            self._streamed_assistant_text = False
            self._visible_output = False
            self._turn_start_message_count = len(self.agent.state.messages)
            self._turn_final_text_signature = None
            return
        if event.type == "message_delta" and event.delta:
            console.print(event.delta, end="")
            self._streamed_assistant_text = True
            self._visible_output = True
            return
        if event.type == "planner_start":
            console.print()
            render_kv_block("Plan", [("status", "planning"), ("next", "Waiting for planner steps")])
            self._visible_output = True
            return
        if event.type == "planner_step" and event.plan_step is not None:
            render_kv_block(
                "Plan Step",
                [
                    ("status", event.plan_step.status),
                    ("step", event.plan_step.title),
                    ("tool", event.plan_step.tool_name or "-"),
                ],
            )
            self._visible_output = True
            return
        if event.type == "planner_end":
            token = event.details.get("token")
            if event.details.get("requires_approval"):
                summary = [str(item) for item in event.details.get("summary", []) if str(item).strip()]
                files = [str(item) for item in event.details.get("files_touched_guess", []) if str(item).strip()]
                shell = [str(item) for item in event.details.get("shell_commands_guess", []) if str(item).strip()]
                high_risk = [str(item) for item in event.details.get("high_risk_tools", []) if str(item).strip()]
                render_kv_block(
                    "Approval Required",
                    [
                        ("status", "awaiting approval"),
                        ("token", str(token or "-")),
                        ("files", ", ".join(files[:4])),
                        ("shell", ", ".join(shell[:3])),
                        ("high_risk", ", ".join(high_risk[:4])),
                        ("actions", f"/approve {token} | /reject {token}" if token else "approve or reject"),
                    ],
                    bullets=summary[:4] or None,
                )
            else:
                render_kv_block("Plan", [("status", "ready"), ("next", "Executor is starting")])
            self._visible_output = True
            return
        if event.type == "tool_start":
            render_kv_block(
                "Tool Start",
                [
                    ("tool", event.tool_name or "-"),
                    ("args", summarize_tool_args(event.tool_args)),
                    ("status", "running"),
                ],
            )
            self._visible_output = True
            return
        if event.type == "tool_end":
            details = event.details or {}
            if details.get("persisted") is True:
                label = "success"
            elif details.get("staged") is True:
                label = "staged"
            elif details.get("approval_unavailable") is True:
                label = "blocked"
            else:
                label = "error" if event.is_error else "done"
            result_lines = [compact_text(event.message or "", limit=140)]
            path = details.get("path")
            command = details.get("command")
            token = details.get("token")
            returncode = details.get("returncode")
            if isinstance(path, str) and path.strip():
                result_lines.append(f"path: {path}")
            if isinstance(command, str) and command.strip():
                result_lines.append(f"command: {command}")
            if isinstance(token, str) and token.strip():
                result_lines.append(f"token: {token}")
            if isinstance(returncode, int):
                result_lines.append(f"exit code: {returncode}")
            render_kv_block(
                "Tool Result",
                [
                    ("tool", event.tool_name or "-"),
                    ("status", label),
                    ("result", "\n".join(result_lines)),
                ],
            )
            self._visible_output = True
            return
        if event.type == "compaction":
            console.print(f"[Runtime] context compacted: {event.details}")
            return
        if event.type == "queue_update":
            action = event.details.get("action")
            delivery = event.details.get("delivery")
            text_value = compact_text(event.details.get("text", ""), limit=80)
            render_kv_block("Queue Update", [("action", str(action or "-")), ("delivery", str(delivery or "-")), ("text", text_value)])
            snapshot = RUNTIME_MONITOR.snapshot_from_event(event)
            if snapshot is not None:
                console.print(format_runtime_status(snapshot))
            return
        if event.type == "turn_state":
            snapshot = RUNTIME_MONITOR.snapshot_from_event(event)
            if snapshot is not None:
                console.print(format_runtime_status(snapshot))
            return
        if event.type == "error":
            render_kv_block("Error", [("message", event.message or "unknown error")])
            self._visible_output = True
            return
        if event.type == "turn_end":
            if self._last_completed_turn_id == self._current_turn_id:
                return
            self._render_turn_end_feedback()
            self._last_completed_turn_id = self._current_turn_id

    def _render_turn_end_feedback(self) -> None:
        latest = self._latest_assistant_message()
        if latest is not None:
            index, text = latest
            if index > self._last_rendered_assistant_index and text and text != self._turn_final_text_signature:
                if not self._streamed_assistant_text:
                    console.print(text)
                    self._visible_output = True
                self._last_rendered_assistant_index = index
                self._turn_final_text_signature = text
        if not self._visible_output:
            console.print(EMPTY_TURN_FALLBACK)
        console.print(TURN_COMPLETE_MARKER)

    def _latest_assistant_message(self) -> tuple[int, str] | None:
        for index in range(len(self.agent.state.messages) - 1, self._turn_start_message_count - 1, -1):
            message = self.agent.state.messages[index]
            if message.role != "assistant":
                continue
            text = "\n".join(
                part.text.strip()
                for part in message.content
                if isinstance(part, TextPart) and part.text.strip()
            ).strip()
            return index, text
        return None


def render_event(event: AgentEvent) -> None:
    if event.type == "compaction":
        console.print(f"[Runtime] context compacted: {event.details}")
    elif event.type == "queue_update":
        action = event.details.get("action")
        delivery = event.details.get("delivery")
        text_value = compact_text(event.details.get("text", ""), limit=80)
        render_kv_block("Queue Update", [("action", str(action or "-")), ("delivery", str(delivery or "-")), ("text", text_value)])
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
    "ChatEventRenderer",
    "EMPTY_TURN_FALLBACK",
    "TURN_COMPLETE_MARKER",
    "compact_text",
    "console",
    "format_plan_step",
    "format_runtime_status",
    "load_timeline_entries",
    "render_event",
    "render_kv_block",
    "render_runtime_status",
    "render_settings",
    "summarize_tool_args",
]
