from __future__ import annotations

import argparse
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import typer
except ImportError:  # pragma: no cover
    typer = None

try:
    from prompt_toolkit import PromptSession
except ImportError:  # pragma: no cover
    PromptSession = None

try:
    from rich.console import Console
    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover
    import sys
    RICH_AVAILABLE = False

    class Console:  # type: ignore[override]
        def print(self, *args, end="\n", **kwargs):
            text = " ".join(str(arg) for arg in args)
            encoding = sys.stdout.encoding or "utf-8"
            safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
            print(safe, end=end)

from agent_core.llm.client import LLMClient
from agent_core.runtime.monitor import RuntimeMonitor, RuntimeStatusSnapshot
from agent_core.runtime.session import AgentSession
from agent_core.runtime.types import AgentEvent, PlanStep
from storage.settings import Settings
from storage.sessions import SessionStore, SessionTreeEntry, SessionTurnEntry
from storage.timeline import TimelineStore
from tools.pending_actions import PendingActionStore
from tools.registry import ToolRegistry

console = Console()
app = typer.Typer(help="Personal Python coding agent for Windows 10.") if typer else None

PLAN_MARKERS = {
    "pending": "[ ]",
    "awaiting_approval": "[?]",
    "in_progress": "[~]",
    "completed": "[x]",
    "failed": "[!]",
}


RUNTIME_MONITOR = RuntimeMonitor()


def build_agent(workspace: Path, session_id: Optional[str] = None) -> AgentSession:
    settings = Settings.load(workspace)
    session_store = create_session_store(settings)
    record = session_store.load(session_id) if session_id else session_store.create(settings.system_prompt, settings.model)
    agent = AgentSession(
        llm_client=LLMClient(provider=settings.provider, model=record.model),
        tool_registry=ToolRegistry(workspace, policy=settings.tool_policy),
        session_store=session_store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=confirm_tool_call,
        initial_compaction=record.compaction,
        initial_pending_tool_calls=record.pending_tool_calls,
        initial_pending_plan_token=record.pending_plan_token,
        initial_queued_messages=record.queued_messages,
        require_plan_approval=settings.tool_policy.confirm_high_risk_plan,
        timeline_store=timeline_store_for(workspace),
    )
    agent.restore_session_record(record)
    return agent


def create_session_store(settings: Settings) -> SessionStore:
    candidates = [settings.global_dir / "sessions", settings.project_dir / "global" / "sessions"]
    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            return SessionStore(candidate)
        except PermissionError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise PermissionError("Unable to create a writable session tree store")


def session_store_for(workspace: Path) -> SessionStore:
    settings = Settings.load(workspace)
    return create_session_store(settings)


def timeline_store_for(workspace: Path) -> TimelineStore:
    settings = Settings.load(workspace)
    candidates = [settings.global_dir / "timelines", settings.project_dir / "global" / "timelines"]
    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            return TimelineStore(candidate)
        except PermissionError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise PermissionError("Unable to create a writable timeline store")


def pending_action_store_for(workspace: Path) -> PendingActionStore:
    return PendingActionStore((workspace.resolve() / ".pp-agent" / "pending-edits"))


def confirm_tool_call(tool_name: str, args: dict) -> bool:
    preview = ", ".join(f"{key}={value!r}" for key, value in args.items())
    if typer:
        return typer.confirm(f"Allow tool `{tool_name}` with args: {preview}?", default=False)
    answer = input(f"Allow tool {tool_name} with args: {preview}? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def format_plan_step(step: PlanStep) -> str:
    tool_part = f" [{step.tool_name}]" if step.tool_name else ""
    marker = PLAN_MARKERS.get(step.status, "[-]")
    return f"{marker} {step.title}{tool_part}"


def load_pending_action(workspace: Path, token: str) -> dict:
    return pending_action_store_for(workspace).load(token)


def format_runtime_status(snapshot: RuntimeStatusSnapshot) -> str:
    return RUNTIME_MONITOR.format(snapshot)


def render_runtime_status(agent: AgentSession) -> None:
    snapshot = agent.runtime_monitor.snapshot_from_state(agent.state)
    console.print(format_runtime_status(snapshot))


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


def timeline_show_main(workspace: Path, session_id: Optional[str] = None, limit: int = 30) -> None:
    store = timeline_store_for(workspace)
    if session_id:
        try:
            session_id = resolve_session_id(workspace, session_id)
        except (FileNotFoundError, ValueError):
            pass
        entries = store.list_session(session_id, limit=limit)
    else:
        entries = store.list_recent(limit=limit)
    render_timeline(entries)


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


def render_settings(agent: AgentSession, workspace: Path) -> None:
    settings = Settings.load(workspace)
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


def approvals_summary_payload(workspace: Path) -> dict:
    items = pending_action_store_for(workspace).list()
    by_type: dict[str, int] = {}
    for item in items:
        by_type[item["action_type"]] = by_type.get(item["action_type"], 0) + 1
    return {"count": len(items), "by_type": by_type, "tokens": [item["token"] for item in items], "items": items}


def short_token(token: str) -> str:
    return token[:8]


def short_session(session_id: str) -> str:
    return session_id[:8]


def resolve_session_id(workspace: Path, session_ref: str) -> str:
    store = session_store_for(workspace)
    entries = store.tree()
    if not session_ref:
        raise FileNotFoundError("Session id is required")
    exact = next((entry.id for entry in entries if entry.id == session_ref), None)
    if exact:
        return exact
    matches = [entry.id for entry in entries if entry.id.startswith(session_ref)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(f"Session not found: {session_ref}")
    raise ValueError(f"Session prefix is ambiguous: {session_ref}")


def split_session_turn_ref(ref: str, current_session_id: Optional[str] = None) -> tuple[str, Optional[str]]:
    if "@" not in ref:
        return ref, None
    session_ref, turn_ref = ref.split("@", 1)
    session_ref = session_ref or (current_session_id or "")
    turn_ref = turn_ref.strip() or None
    return session_ref.strip(), turn_ref


def resolve_turn_id(workspace: Path, session_id: str, turn_ref: str) -> str:
    store = session_store_for(workspace)
    record = store.load(session_id)
    turn_ids = [node.id for node in record.turn_nodes]
    exact = next((turn_id for turn_id in turn_ids if turn_id == turn_ref), None)
    if exact:
        return exact
    matches = [turn_id for turn_id in turn_ids if turn_id.startswith(turn_ref)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(f"Turn not found: {turn_ref}")
    raise ValueError(f"Turn prefix is ambiguous: {turn_ref}")


def resolve_session_turn_ref(workspace: Path, ref: str, current_session_id: Optional[str] = None) -> tuple[str, Optional[str]]:
    session_ref, turn_ref = split_session_turn_ref(ref, current_session_id=current_session_id)
    session_id = resolve_session_id(workspace, session_ref)
    turn_id = resolve_turn_id(workspace, session_id, turn_ref) if turn_ref else None
    return session_id, turn_id


def resume_target(workspace: Path, ref: str, current_session_id: Optional[str] = None) -> str:
    session_id, turn_id = resolve_session_turn_ref(workspace, ref, current_session_id=current_session_id)
    if turn_id is not None:
        session_store_for(workspace).set_active_head(session_id, turn_id)
    return session_id


def short_turn(turn_id: str) -> str:
    return turn_id[:8]


def tree_style_for(entry_id: str, current_session_id: Optional[str], active_ids: set[str]) -> Optional[str]:
    if not RICH_AVAILABLE:
        return None
    if entry_id == current_session_id:
        return "bold black on green"
    if entry_id in active_ids:
        return "green"
    return None


def print_tree_lines(lines: list[tuple[str, Optional[str]]]) -> None:
    for line, style in lines:
        if style and RICH_AVAILABLE:
            console.print(line, style=style)
        else:
            console.print(line)


def render_queue_panel(agent: AgentSession) -> None:
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


def handle_queue_command(agent: AgentSession, raw: str) -> bool:
    if raw in {"/queue", "/queue list"}:
        render_queue_panel(agent)
        return True
    if raw.startswith("/queue steering "):
        text = raw.split(" ", 2)[2].strip()
        if not text:
            console.print("Usage: /queue steering <message>")
            return True
        agent.enqueue_message(text, delivery="steering")
        return True
    if raw.startswith("/queue follow-up "):
        text = raw.split(" ", 2)[2].strip()
        if not text:
            console.print("Usage: /queue follow-up <message>")
            return True
        agent.enqueue_message(text, delivery="follow_up")
        return True
    if raw.startswith("/queue followup "):
        text = raw.split(" ", 2)[2].strip()
        if not text:
            console.print("Usage: /queue followup <message>")
            return True
        agent.enqueue_message(text, delivery="follow_up")
        return True
    console.print("Usage: /queue | /queue list | /queue steering <message> | /queue follow-up <message>")
    return True


def compact_text(value: str, limit: int = 90) -> str:
    text = value.replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


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

def render_tree_entry_preview(label: str, entry: Optional[dict]) -> list[str]:
    if not entry:
        return [f"{label}: none"]
    updated = datetime.fromtimestamp(entry["updated_at"]).strftime("%m-%d %H:%M") if entry.get("updated_at") else "unknown"
    turn_id = f"turn-{entry.get('turn_count', 0)}"
    lines = [
        f"{label}: {short_session(entry['id'])}  [{turn_id}]",
        f"  model: {entry['model']}  messages: {entry['message_count']}  turns: {entry.get('turn_count', 0)}  updated: {updated}",
    ]
    if entry.get("summary_preview"):
        lines.append(f"  summary: {entry['summary_preview']}")
    if entry.get("last_user_preview"):
        lines.append(f"  user: {entry['last_user_preview']}")
    if entry.get("last_assistant_preview"):
        lines.append(f"  assistant: {entry['last_assistant_preview']}")
    if entry.get("pending_plan_token"):
        lines.append(f"  pending-plan: {entry['pending_plan_token']}")
    return lines


def render_turn_entry_preview(label: str, entry: Optional[dict]) -> list[str]:
    if not entry:
        return [f"{label}: none"]
    created = datetime.fromtimestamp(entry["created_at"]).strftime("%m-%d %H:%M") if entry.get("created_at") else "unknown"
    status = entry.get("status", "committed")
    entry_type = entry.get("entry_type", "turn")
    kind = f"compact@{entry.get('summarized_message_count', 0)}" if entry_type == "compaction" else f"turn-{entry.get('turn_number', 0)}"
    lines = [
        f"{label}: {short_turn(entry['id'])}  [{kind}]  {status}",
        f"  messages: {entry.get('message_count', 0)}  total: {entry.get('total_message_count', 0)}  created: {created}",
    ]
    if entry.get("user_preview"):
        lines.append(f"  user: {entry['user_preview']}")
    if entry.get("assistant_preview"):
        lines.append(f"  assistant: {entry['assistant_preview']}")
    elif entry.get("summary_preview"):
        lines.append(f"  summary: {entry['summary_preview']}")
    return lines


def _message_preview_for_agent(agent: AgentSession, role: str, limit: int = 96) -> str:
    for message in reversed(agent.state.messages):
        if message.role != role:
            continue
        parts = [part.text.strip() for part in message.content if isinstance(part, TextPart) and part.text.strip()]
        text = " ".join(parts)
        return compact_text(text, limit=limit) if text else ""
    return ""


def _transient_tree_entry(agent: AgentSession) -> dict:
    summary = compact_text(agent.state.compaction.summary, limit=96) if agent.state.compaction.summary else ""
    if not summary and agent.state.messages:
        summary = _message_preview_for_agent(agent, agent.state.messages[-1].role, limit=96)
    return {
        "id": agent.session_id,
        "parent_id": None,
        "updated_at": 0.0,
        "model": agent.llm_client.model.model,
        "message_count": len(agent.state.messages),
        "turn_count": sum(1 for message in agent.state.messages if message.role == "user"),
        "pending_plan_token": agent.state.pending_plan_token,
        "summary_preview": summary,
        "last_user_preview": _message_preview_for_agent(agent, "user"),
        "last_assistant_preview": _message_preview_for_agent(agent, "assistant"),
    }


def _active_branch_ids(entry_index: dict[str, SessionTreeEntry], session_id: Optional[str]) -> set[str]:
    active: set[str] = set()
    current = session_id
    while current and current in entry_index:
        active.add(current)
        current = entry_index[current].parent_id
    return active


def _tree_line(entry: SessionTreeEntry, current_session_id: Optional[str], active_ids: set[str]) -> tuple[str, Optional[str]]:
    current_marker = ">>" if entry.id == current_session_id else "  "
    branch_marker = "*" if entry.id in active_ids else " "
    updated = datetime.fromtimestamp(entry.updated_at).strftime("%m-%d %H:%M")
    pending = "  pending-plan" if entry.pending_plan_token else ""
    summary = f"  {entry.summary_preview}" if entry.summary_preview else ""
    line = (
        f"{current_marker}{branch_marker} {short_session(entry.id)}  [turn-{entry.turn_count}]  {entry.model}"
        f"  msgs={entry.message_count}  updated={updated}{pending}{summary}"
    )
    return line, tree_style_for(entry.id, current_session_id, active_ids)


def _active_turn_ids(turn_entries: list[SessionTurnEntry], active_head_id: Optional[str]) -> set[str]:
    index = {entry.id: entry for entry in turn_entries}
    active: set[str] = set()
    current = active_head_id
    while current and current in index:
        active.add(current)
        current = index[current].parent_id
    return active


def _turn_line(entry: SessionTurnEntry, active_turn_id: Optional[str], active_turn_ids: set[str]) -> str:
    current_marker = ">>" if entry.id == active_turn_id else "  "
    branch_marker = "*" if entry.id in active_turn_ids else " "
    summary = entry.assistant_preview or entry.summary_preview or entry.user_preview
    status = f" {entry.status}" if entry.status != "committed" else ""
    kind = f"compact@{entry.summarized_message_count}" if entry.entry_type == "compaction" else f"turn-{entry.turn_number}"
    return f"{current_marker}{branch_marker} {short_turn(entry.id)}  [{kind}]  msgs={entry.message_count}{status}  {summary}".rstrip()


def render_session_tree(
    workspace: Path,
    current_session_id: Optional[str] = None,
    current_agent: Optional[AgentSession] = None,
    focus_session_id: Optional[str] = None,
    sort_mode: str = "branch",
) -> None:
    if sort_mode not in {"branch", "updated"}:
        sort_mode = "branch"
    store = session_store_for(workspace)
    entries = store.tree()
    entry_index = {entry.id: entry for entry in entries}
    active_ids = _active_branch_ids(entry_index, current_session_id)
    lines: list[tuple[str, Optional[str]]] = [("Session Tree", None), (f"View: {sort_mode}", None)]

    if not entries and current_agent is None:
        print_tree_lines([("Session Tree", None), ("No sessions yet.", None)])
        return

    recent_entries = sorted(entries, key=lambda item: item.updated_at, reverse=True)
    lines.append(("", None))
    lines.append(("Recent Nodes", None))
    if recent_entries:
        for entry in recent_entries[:5]:
            line, style = _tree_line(entry, current_session_id, active_ids)
            lines.append((f"  {line}", style))
    elif current_agent is not None:
        for item in render_tree_entry_preview("Current (unsaved)", _transient_tree_entry(current_agent)):
            lines.append((item, None))

    lines.append(("", None))
    if sort_mode == "updated":
        lines.append(("Updated View", None))
        if recent_entries:
            for entry in recent_entries[:12]:
                lines.append(_tree_line(entry, current_session_id, active_ids))
    else:
        children: dict[Optional[str], list[SessionTreeEntry]] = {}
        for entry in entries:
            children.setdefault(entry.parent_id, []).append(entry)
        for item in children.values():
            item.sort(key=lambda node: (node.updated_at, node.id), reverse=True)
        lines.append(("Branch View", None))

        def walk(parent_id: Optional[str], prefix: str = "") -> None:
            nodes = children.get(parent_id, [])
            for index, entry in enumerate(nodes):
                branch = "\-" if index == len(nodes) - 1 else "|-"
                line, style = _tree_line(entry, current_session_id, active_ids)
                lines.append((f"{prefix}{branch} {line}", style))
                walk(entry.id, prefix + ("   " if index == len(nodes) - 1 else "|  "))

        if children:
            walk(None)
        elif current_agent is not None:
            lines.append(("\- >>* unsaved current session", tree_style_for(current_agent.session_id, current_session_id, {current_agent.session_id})))

    focus_ref = focus_session_id or current_session_id
    focus_id: Optional[str] = None
    focus_turn_id: Optional[str] = None
    if focus_ref:
        try:
            session_ref, turn_ref = split_session_turn_ref(focus_ref, current_session_id=current_session_id)
            focus_id = resolve_session_id(workspace, session_ref)
            focus_turn_id = resolve_turn_id(workspace, focus_id, turn_ref) if turn_ref else None
        except (FileNotFoundError, ValueError):
            focus_id = None
            focus_turn_id = None
    description: Optional[dict[str, object]] = None
    if focus_id and focus_id in entry_index:
        description = store.describe(focus_id)
        if focus_turn_id:
            description["turn_focus"] = store.describe_turn(focus_id, focus_turn_id)
    elif current_agent is not None and current_session_id and current_session_id not in entry_index:
        description = {"current": _transient_tree_entry(current_agent), "parent": None, "children": [], "turns": [], "turn_focus": None}
    elif current_agent is not None and focus_ref == current_agent.session_id:
        description = {"current": _transient_tree_entry(current_agent), "parent": None, "children": [], "turns": [], "turn_focus": None}
    elif recent_entries:
        focus_id = recent_entries[0].id
        description = store.describe(recent_entries[0].id)

    if description is not None:
        lines.append(("", None))
        lines.append(("Focus", None))
        for item in render_tree_entry_preview("Current", description.get("current")):
            lines.append((item, None))
        for item in render_tree_entry_preview("Parent", description.get("parent")):
            lines.append((item, None))
        children_preview = description.get("children") or []
        if children_preview:
            lines.append(("Children:", None))
            for child in children_preview[:3]:
                for item in render_tree_entry_preview("Child", child):
                    lines.append((f"  {item}", None))
        else:
            lines.append(("Children: none", None))

        if focus_id:
            turn_entries = store.turn_tree(focus_id)
            session_entry = entry_index.get(focus_id)
            active_turn_id = focus_turn_id or (session_entry.active_head_id if session_entry is not None else None)
            active_turn_ids = _active_turn_ids(turn_entries, active_turn_id)
            turn_children: dict[Optional[str], list[SessionTurnEntry]] = {}
            for entry in turn_entries:
                turn_children.setdefault(entry.parent_id, []).append(entry)
            for item in turn_children.values():
                item.sort(key=lambda node: (node.created_at, node.id), reverse=True)
            lines.append(("", None))
            lines.append(("Turn Tree", None))

            def walk_turns(parent_id: Optional[str], prefix: str = "") -> None:
                nodes = turn_children.get(parent_id, [])
                for index, entry in enumerate(nodes):
                    branch = "\-" if index == len(nodes) - 1 else "|-"
                    lines.append((f"{prefix}{branch} {_turn_line(entry, active_turn_id, active_turn_ids)}", None))
                    walk_turns(entry.id, prefix + ("   " if index == len(nodes) - 1 else "|  "))

            if turn_children:
                walk_turns(None)
            else:
                lines.append(("No turns yet.", None))

            turn_focus = description.get("turn_focus")
            if focus_turn_id and turn_focus is not None:
                lines.append(("", None))
                lines.append(("Turn Focus", None))
                for item in render_turn_entry_preview("Current", turn_focus.get("current") if isinstance(turn_focus, dict) else None):
                    lines.append((item, None))
                for item in render_turn_entry_preview("Parent", turn_focus.get("parent") if isinstance(turn_focus, dict) else None):
                    lines.append((item, None))
                child_turns = turn_focus.get("children") if isinstance(turn_focus, dict) else []
                if child_turns:
                    lines.append(("Children:", None))
                    for child in child_turns[:3]:
                        for item in render_turn_entry_preview("Child", child):
                            lines.append((f"  {item}", None))
                else:
                    lines.append(("Children: none", None))
                current_turn = turn_focus.get("current") if isinstance(turn_focus, dict) else None
                parent_turn = turn_focus.get("parent") if isinstance(turn_focus, dict) else None
                if isinstance(current_turn, dict):
                    current_ref = f"{focus_id}@{current_turn['id']}"
                    lines.append(("Turn Actions", None))
                    lines.append((f"  /resume {current_ref}      continue exactly from this history point", None))
                    lines.append((f"  /branch {current_ref}      fork a new session from this history point", None))
                    if isinstance(parent_turn, dict):
                        parent_ref = f"{focus_id}@{parent_turn['id']}"
                        lines.append((f"  /resume {parent_ref}      move one node earlier", None))
                        lines.append((f"  /branch {parent_ref}      fork from the parent node", None))
                    if child_turns:
                        first_child = child_turns[0]
                        if isinstance(first_child, dict):
                            child_ref = f"{focus_id}@{first_child['id']}"
                            lines.append((f"  /resume {child_ref}      jump into the newest child branch", None))

    focus_short = short_session(focus_id) if focus_id else "current"
    turn_hint = f"{focus_short}@{short_turn(focus_turn_id)}" if focus_id and focus_turn_id else None
    lines.append(("", None))
    lines.append(("Branch Navigation", None))
    lines.append(("  Active branch lines are green when rich output is available.", None))
    lines.append((f"  /tree updated                 switch to the recent-first view", None))
    lines.append((f"  /tree focus {focus_short}           move the tree focus without changing chat", None))
    lines.append((f"  /resume {focus_short}               switch chat to the focused session head", None))
    if turn_hint:
        lines.append((f"  /resume {turn_hint}       switch chat to that historical turn and continue", None))
    lines.append((f"  /branch {focus_short}               branch from the focused session head", None))
    lines.append((f"  /rewind-turn {focus_short} 1        branch from one full turn earlier", None))
    lines.append(("  /compact                      write a compaction node for the current branch", None))
    print_tree_lines(lines)


def branch_session(workspace: Path, source_session_id: str, source_turn_id: Optional[str] = None) -> str:
    store = session_store_for(workspace)
    forked = store.fork_from_head(source_session_id, source_turn_id) if source_turn_id is not None else store.fork(source_session_id)
    store.save(forked)
    return forked.id


def rewind_session(workspace: Path, source_session_id: str, message_count: int) -> str:
    store = session_store_for(workspace)
    rewound = store.rewind(source_session_id, message_count)
    store.save(rewound)
    return rewound.id


def rewind_session_turns(workspace: Path, source_session_id: str, turn_count: int) -> str:
    store = session_store_for(workspace)
    rewound = store.rewind_turns(source_session_id, turn_count)
    store.save(rewound)
    return rewound.id


def approve_or_execute_pending_action(workspace: Path, token: str, render: bool = True) -> dict:
    payload = load_pending_action(workspace, token)
    if payload["action_type"] == "planner_approval":
        session_id = payload.get("details", {}).get("session_id")
        if not session_id:
            raise ValueError("planner_approval token is missing session_id")
        agent = build_agent(workspace, session_id=session_id)
        agent.subscribe(render_event)
        events = agent.approve_pending_plan(token)
        if render:
            console.print()
        return {"token": token, "action_type": payload["action_type"], "session_id": session_id, "event_count": len(events), "result": "approved_and_executed"}
    registry = ToolRegistry(workspace, policy=Settings.load(workspace).tool_policy)
    result = registry.execute("approve_pending_action", {"token": token})
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
        agent = build_agent(workspace, session_id=session_id)
        agent.reject_pending_plan(token)
        message = f"Rejected planner approval {token} for session {session_id}"
        if render:
            console.print(message)
        return {"token": token, "action_type": payload["action_type"], "result": message}
    registry = ToolRegistry(workspace, policy=Settings.load(workspace).tool_policy)
    result = registry.execute("reject_pending_action", {"token": token})
    if render:
        console.print(result.content)
    return {"token": token, "action_type": payload["action_type"], "result": result.content}


def handle_command(agent: AgentSession, raw: str, workspace: Path) -> str:
    if raw == "/quit":
        return "quit"
    if raw == "/new":
        return "new"
    if raw == "/session":
        console.print(f"session: {agent.session_id}")
        return "handled"
    if raw == "/settings":
        render_settings(agent, workspace)
        return "handled"
    if raw == "/status":
        render_runtime_status(agent)
        return "handled"
    if raw == "/approvals":
        render_approval_panel(workspace)
        return "handled"
    if raw == "/timeline":
        timeline_show_main(workspace, session_id=agent.session_id, limit=30)
        return "handled"
    if raw == "/compact":
        events = agent.compact_now()
        if not events:
            console.print("No new messages to compact.")
        return "handled"
    if raw.startswith("/tree"):
        parts = raw.split()
        sort_mode = "branch"
        focus_session_id: Optional[str] = None
        if len(parts) >= 2:
            if parts[1] in {"branch", "updated"}:
                sort_mode = parts[1]
                if len(parts) >= 3:
                    focus_session_id = parts[2]
            elif parts[1] == "focus" and len(parts) >= 3:
                focus_session_id = parts[2]
            else:
                focus_session_id = parts[1]
        if focus_session_id:
            try:
                focus_session_id, focus_turn_id = resolve_session_turn_ref(workspace, focus_session_id, current_session_id=agent.session_id)
                focus_session_id = f"{focus_session_id}@{focus_turn_id}" if focus_turn_id else focus_session_id
            except (FileNotFoundError, ValueError) as exc:
                console.print(f"[Error] {exc}")
                return "handled"
        render_session_tree(
            workspace,
            current_session_id=agent.session_id,
            current_agent=agent,
            focus_session_id=focus_session_id,
            sort_mode=sort_mode,
        )
        return "handled"
    if raw.startswith("/branch "):
        source_ref = raw.split(" ", 1)[1].strip()
        try:
            source_session_id, source_turn_id = resolve_session_turn_ref(workspace, source_ref, current_session_id=agent.session_id)
        except (FileNotFoundError, ValueError) as exc:
            console.print(f"[Error] {exc}")
            return "handled"
        new_session_id = branch_session(workspace, source_session_id, source_turn_id)
        source_label = f"{source_session_id}@{source_turn_id}" if source_turn_id else source_session_id
        console.print(f"Branched {source_label} -> {new_session_id}")
        return new_session_id
    if raw.startswith("/rewind-turn "):
        parts = raw.split()
        try:
            if len(parts) == 2:
                source_session_id = agent.session_id
                turn_count = int(parts[1])
            elif len(parts) == 3:
                source_session_id = resolve_session_id(workspace, parts[1])
                turn_count = int(parts[2])
            else:
                raise ValueError
        except ValueError:
            console.print("Usage: /rewind-turn <turn_count> or /rewind-turn <session_id> <turn_count>")
            return "handled"
        try:
            new_session_id = rewind_session_turns(workspace, source_session_id, turn_count)
        except (FileNotFoundError, ValueError) as exc:
            console.print(f"[Error] {exc}")
            return "handled"
        console.print(f"Turn-rewound {source_session_id} at turn_count={turn_count} -> {new_session_id}")
        return new_session_id
    if raw.startswith("/rewind "):
        parts = raw.split()
        try:
            if len(parts) == 2:
                source_session_id = agent.session_id
                message_count = int(parts[1])
            elif len(parts) == 3:
                source_session_id = resolve_session_id(workspace, parts[1])
                message_count = int(parts[2])
            else:
                raise ValueError
        except ValueError:
            console.print("Usage: /rewind <message_count> or /rewind <session_id> <message_count>")
            return "handled"
        try:
            new_session_id = rewind_session(workspace, source_session_id, message_count)
        except (FileNotFoundError, ValueError) as exc:
            console.print(f"[Error] {exc}")
            return "handled"
        console.print(f"Rewound {source_session_id} at message_count={message_count} -> {new_session_id}")
        return new_session_id
    if raw.startswith("/approve "):
        token = raw.split(" ", 1)[1].strip()
        payload = load_pending_action(workspace, token)
        if payload["action_type"] == "planner_approval":
            session_id = payload.get("details", {}).get("session_id")
            if session_id != agent.session_id:
                console.print(f"Planner token belongs to session {session_id}. Use /resume {session_id} first.")
                return "handled"
            agent.approve_pending_plan(token)
            console.print()
        else:
            approve_or_execute_pending_action(workspace, token, render=True)
        return "handled"
    if raw.startswith("/reject "):
        token = raw.split(" ", 1)[1].strip()
        payload = load_pending_action(workspace, token)
        if payload["action_type"] == "planner_approval":
            session_id = payload.get("details", {}).get("session_id")
            if session_id != agent.session_id:
                console.print(f"Planner token belongs to session {session_id}. Use /resume {session_id} first.")
                return "handled"
            agent.reject_pending_plan(token)
            console.print(f"Rejected planner approval {token}")
        else:
            reject_pending_action(workspace, token, render=True)
        return "handled"
    if raw.startswith("/model "):
        agent.llm_client.model.model = raw.split(" ", 1)[1].strip()
        agent.state.model.model = agent.llm_client.model.model
        console.print(f"model set to {agent.llm_client.model.model}")
        return "handled"
    if raw.startswith("/resume "):
        session_ref = raw.split(" ", 1)[1].strip()
        try:
            return resume_target(workspace, session_ref, current_session_id=agent.session_id)
        except (FileNotFoundError, ValueError) as exc:
            console.print(f"[Error] {exc}")
            return "handled"
    return "run"


def chat_main(workspace: Path, session_id: Optional[str] = None) -> None:
    prompt_session = None
    if PromptSession:
        try:
            prompt_session = PromptSession()
        except Exception:
            prompt_session = None
    while True:
        agent = build_agent(workspace, session_id=session_id)
        agent.subscribe(render_event)
        worker: Optional[threading.Thread] = None

        def is_busy() -> bool:
            return worker is not None and worker.is_alive()

        def start_worker(action: str, fn) -> None:
            nonlocal worker

            def runner() -> None:
                try:
                    fn()
                finally:
                    console.print()

            worker = threading.Thread(target=runner, name=f"pp-agent-{action}", daemon=True)
            worker.start()

        console.print(f"pp-agent session={agent.session_id} model={agent.llm_client.model.model}")
        if agent.state.pending_plan_token:
            console.print(f"Pending planner gate: {agent.state.pending_plan_token}. Use /approve {agent.state.pending_plan_token} or /reject {agent.state.pending_plan_token}.")
        if agent.state.queued_messages:
            console.print(f"Queued messages: {len(agent.state.queued_messages)}. Use /queue to inspect them.")
        render_runtime_status(agent)
        console.print("Tips: /status shows runtime state. Plain text while busy becomes follow-up queue. Use /queue steering <msg> for higher-priority guidance.")

        while True:
            try:
                raw = prompt_session.prompt("\n> ").strip() if prompt_session else input("\n> ").strip()
            except EOFError:
                return
            if not raw:
                continue

            if raw.startswith("/queue"):
                handle_queue_command(agent, raw)
                if not is_busy() and not agent.state.pending_plan_token and agent.state.queued_messages:
                    start_worker("queue", agent.continue_)
                continue

            if is_busy():
                if raw.startswith("/"):
                    if raw in {"/session", "/settings", "/status", "/approvals", "/timeline"} or raw.startswith("/tree"):
                        result = handle_command(agent, raw, workspace)
                        if result == "quit":
                            console.print("Wait for the current task to finish before quitting.")
                        continue
                    console.print("Agent is busy. Use /queue steering <message>, /queue, or wait for the current task to finish.")
                    continue
                agent.enqueue_message(raw, delivery="follow_up")
                continue

            if agent.state.pending_plan_token and raw.strip().lower() in {"approve", "yes", "??", "??"}:
                token = agent.state.pending_plan_token
                start_worker("approve", lambda: agent.approve_pending_plan(token))
                continue

            if agent.state.pending_plan_token and raw.strip().lower() in {"reject", "no", "??"}:
                token = agent.state.pending_plan_token
                result = handle_command(agent, f"/reject {token}", workspace)
                if result == "quit":
                    return
                if result == "new":
                    session_id = None
                    break
                if result != "handled":
                    session_id = result
                    break
                continue

            if raw.startswith("/approve "):
                token = raw.split(" ", 1)[1].strip()
                payload = load_pending_action(workspace, token)
                if payload["action_type"] == "planner_approval":
                    session_for_token = payload.get("details", {}).get("session_id")
                    if session_for_token != agent.session_id:
                        console.print(f"Planner token belongs to session {session_for_token}. Use /resume {session_for_token} first.")
                        continue
                    start_worker("approve", lambda: agent.approve_pending_plan(token))
                else:
                    approve_or_execute_pending_action(workspace, token, render=True)
                continue

            if raw.startswith("/reject "):
                result = handle_command(agent, raw, workspace)
                if result == "quit":
                    return
                if result == "new":
                    session_id = None
                    break
                if result != "handled":
                    session_id = result
                    break
                continue

            if raw.startswith("/"):
                result = handle_command(agent, raw, workspace)
                if result == "handled":
                    continue
                if result == "quit":
                    if is_busy():
                        console.print("Wait for the current task to finish before quitting.")
                        continue
                    return
                if result == "new":
                    if is_busy():
                        console.print("Wait for the current task to finish before creating a new session.")
                        continue
                    session_id = None
                    break
                if result != "run":
                    if is_busy():
                        console.print("Wait for the current task to finish before switching sessions.")
                        continue
                    session_id = result
                    break

            start_worker("prompt", lambda value=raw: agent.prompt(value))


def run_main(prompt: str, workspace: Path, session_id: Optional[str] = None) -> None:
    agent = build_agent(workspace, session_id=session_id)
    agent.subscribe(render_event)
    agent.prompt(prompt)
    console.print()


def sessions_list_main(workspace: Path) -> None:
    store = session_store_for(workspace)
    payload = [{"id": session.id, "parent_id": session.parent_id, "model": session.model.model, "updated_at": session.updated_at, "summarized_message_count": session.compaction.summarized_message_count, "pending_plan_token": session.pending_plan_token, "pending_tool_call_count": len(session.pending_tool_calls), "queued_message_count": len(session.queued_messages)} for session in store.list()]
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))


def sessions_tree_main(workspace: Path, session_id: Optional[str] = None, sort_mode: str = "branch") -> None:
    render_session_tree(workspace, current_session_id=session_id, focus_session_id=session_id, sort_mode=sort_mode)


def sessions_fork_main(workspace: Path, session_id: str) -> None:
    new_session_id = branch_session(workspace, session_id)
    console.print(f"forked session: {new_session_id} parent={session_id}")


def sessions_rewind_main(workspace: Path, session_id: str, message_count: int) -> None:
    try:
        new_session_id = rewind_session(workspace, session_id, message_count)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[Error] {exc}")
        return
    console.print(f"rewound session: {new_session_id} parent={session_id} message_count={message_count}")


def sessions_rewind_turn_main(workspace: Path, session_id: str, turn_count: int) -> None:
    try:
        new_session_id = rewind_session_turns(workspace, session_id, turn_count)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[Error] {exc}")
        return
    console.print(f"turn-rewound session: {new_session_id} parent={session_id} turn_count={turn_count}")


def approvals_list_main(workspace: Path) -> None:
    store = pending_action_store_for(workspace)
    console.print(json.dumps(store.list(), ensure_ascii=False, indent=2))


def approvals_summary_main(workspace: Path) -> None:
    render_approval_panel(workspace)


def approvals_show_main(workspace: Path, token: str) -> None:
    registry = ToolRegistry(workspace, policy=Settings.load(workspace).tool_policy)
    result = registry.execute("preview_pending_action", {"token": token})
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

def workflow_repo_main(workspace: Path, query: Optional[str] = None, token: Optional[str] = None, auto_apply: bool = False, path_filter: Optional[str] = None, staged_only: bool = False) -> None:
    registry = ToolRegistry(workspace, policy=Settings.load(workspace).tool_policy)
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


def config_show_main(workspace: Path) -> None:
    settings = Settings.load(workspace)
    payload = {
        "workspace": str(settings.workspace),
        "timeline_dir": str(timeline_store_for(workspace).root),
        "global_dir": str(settings.global_dir),
        "project_dir": str(settings.project_dir),
        "base_url": settings.provider.base_url,
        "model": settings.model.model,
        "enable_thinking": settings.model.enable_thinking,
        "shell_timeout_seconds": settings.tool_policy.shell_timeout_seconds,
        "tool_confirmation": {
            "write_file": settings.tool_policy.confirm_write_file,
            "edit_file": settings.tool_policy.confirm_edit_file,
            "run_shell": settings.tool_policy.confirm_run_shell,
            "high_risk_plan": settings.tool_policy.confirm_high_risk_plan,
        },
    }
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))


if app:
    @app.command()
    def chat(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"), session_id: Optional[str] = typer.Option(None, "--session")) -> None:
        chat_main(workspace, session_id)


    @app.command()
    def run(prompt: str = typer.Argument(..., help="Prompt to send to the agent."), workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"), session_id: Optional[str] = typer.Option(None, "--session")) -> None:
        run_main(prompt, workspace, session_id)


    sessions_app = typer.Typer(help="Manage stored sessions.")
    approvals_app = typer.Typer(help="Manage staged approvals.")
    workflow_app = typer.Typer(help="Guided repo-aware workflows.")
    config_app = typer.Typer(help="Show active configuration.")
    timeline_app = typer.Typer(help="Inspect persisted agent timeline history.")
    app.add_typer(sessions_app, name="sessions")
    app.add_typer(approvals_app, name="approvals")
    app.add_typer(workflow_app, name="workflow")
    app.add_typer(config_app, name="config")
    app.add_typer(timeline_app, name="timeline")

    @sessions_app.command("list")
    def sessions_list(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        sessions_list_main(workspace)


    @sessions_app.command("tree")
    def sessions_tree(sort_mode: str = typer.Option("branch", "--sort"), session_id: Optional[str] = typer.Option(None, "--session"), workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        sessions_tree_main(workspace, session_id=session_id, sort_mode=sort_mode)


    @sessions_app.command("fork")
    def sessions_fork(session_id: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        sessions_fork_main(workspace, session_id)


    @sessions_app.command("branch")
    def sessions_branch(session_id: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        sessions_fork_main(workspace, session_id)


    @sessions_app.command("rewind")
    def sessions_rewind(session_id: str, message_count: int, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        sessions_rewind_main(workspace, session_id, message_count)


    @sessions_app.command("rewind-turn")
    def sessions_rewind_turn(session_id: str, turn_count: int, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        sessions_rewind_turn_main(workspace, session_id, turn_count)


    @approvals_app.command("list")
    def approvals_list(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        approvals_list_main(workspace)


    @approvals_app.command("summary")
    def approvals_summary(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        approvals_summary_main(workspace)


    @approvals_app.command("show")
    def approvals_show(token: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        approvals_show_main(workspace, token)


    @approvals_app.command("approve")
    def approvals_approve(token: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        approvals_approve_main(workspace, token)


    @approvals_app.command("reject")
    def approvals_reject(token: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        approvals_reject_main(workspace, token)


    @approvals_app.command("approve-all")
    def approvals_approve_all(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        approvals_approve_all_main(workspace)


    @approvals_app.command("reject-all")
    def approvals_reject_all(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        approvals_reject_all_main(workspace)


    @workflow_app.command("repo")
    def workflow_repo(query: Optional[str] = typer.Option(None, "--query"), token: Optional[str] = typer.Option(None, "--token"), auto_apply: bool = typer.Option(False, "--auto-apply"), path_filter: Optional[str] = typer.Option(None, "--path-filter"), staged_only: bool = typer.Option(False, "--staged-only"), workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        workflow_repo_main(workspace, query=query, token=token, auto_apply=auto_apply, path_filter=path_filter, staged_only=staged_only)


    @config_app.command("show")
    def config_show(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        config_show_main(workspace)


    @timeline_app.command("show")
    def timeline_show(session_id: Optional[str] = typer.Option(None, "--session"), limit: int = typer.Option(30, "--limit"), workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        timeline_show_main(workspace, session_id=session_id, limit=limit)

def main() -> None:
    if app and typer:
        app()
        return

    parser = argparse.ArgumentParser(description="Personal Python coding agent for Windows 10.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    chat_parser = subparsers.add_parser("chat")
    chat_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    chat_parser.add_argument("--session", default=None)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("prompt")
    run_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    run_parser.add_argument("--session", default=None)
    sessions_parser = subparsers.add_parser("sessions")
    sessions_subparsers = sessions_parser.add_subparsers(dest="sessions_command", required=True)
    sessions_list_parser = sessions_subparsers.add_parser("list")
    sessions_list_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    sessions_tree_parser = sessions_subparsers.add_parser("tree")
    sessions_tree_parser.add_argument("--sort", default="branch")
    sessions_tree_parser.add_argument("--session", default=None)
    sessions_tree_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    for name in ["fork", "branch"]:
        p = sessions_subparsers.add_parser(name)
        p.add_argument("session_id")
        p.add_argument("--workspace", "-w", default=str(Path.cwd()))
    sessions_rewind_parser = sessions_subparsers.add_parser("rewind")
    sessions_rewind_parser.add_argument("session_id")
    sessions_rewind_parser.add_argument("message_count", type=int)
    sessions_rewind_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    sessions_rewind_turn_parser = sessions_subparsers.add_parser("rewind-turn")
    sessions_rewind_turn_parser.add_argument("session_id")
    sessions_rewind_turn_parser.add_argument("turn_count", type=int)
    sessions_rewind_turn_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    approvals_parser = subparsers.add_parser("approvals")
    approvals_subparsers = approvals_parser.add_subparsers(dest="approvals_command", required=True)
    for name in ["list", "summary", "approve-all", "reject-all"]:
        p = approvals_subparsers.add_parser(name)
        p.add_argument("--workspace", "-w", default=str(Path.cwd()))
    approvals_show_parser = approvals_subparsers.add_parser("show")
    approvals_show_parser.add_argument("token")
    approvals_show_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    approvals_approve_parser = approvals_subparsers.add_parser("approve")
    approvals_approve_parser.add_argument("token")
    approvals_approve_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    approvals_reject_parser = approvals_subparsers.add_parser("reject")
    approvals_reject_parser.add_argument("token")
    approvals_reject_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    workflow_parser = subparsers.add_parser("workflow")
    workflow_subparsers = workflow_parser.add_subparsers(dest="workflow_command", required=True)
    workflow_repo_parser = workflow_subparsers.add_parser("repo")
    workflow_repo_parser.add_argument("--query", default=None)
    workflow_repo_parser.add_argument("--token", default=None)
    workflow_repo_parser.add_argument("--auto-apply", action="store_true")
    workflow_repo_parser.add_argument("--path-filter", default=None)
    workflow_repo_parser.add_argument("--staged-only", action="store_true")
    workflow_repo_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    config_parser = subparsers.add_parser("config")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    config_show_parser = config_subparsers.add_parser("show")
    config_show_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    timeline_parser = subparsers.add_parser("timeline")
    timeline_subparsers = timeline_parser.add_subparsers(dest="timeline_command", required=True)
    timeline_show_parser = timeline_subparsers.add_parser("show")
    timeline_show_parser.add_argument("--session", default=None)
    timeline_show_parser.add_argument("--limit", type=int, default=30)
    timeline_show_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))

    args = parser.parse_args()
    command = getattr(args, "command")
    if command == "chat":
        chat_main(Path(args.workspace), args.session)
    elif command == "run":
        run_main(args.prompt, Path(args.workspace), args.session)
    elif command == "sessions" and args.sessions_command == "list":
        sessions_list_main(Path(args.workspace))
    elif command == "sessions" and args.sessions_command == "tree":
        sessions_tree_main(Path(args.workspace), session_id=args.session, sort_mode=args.sort)
    elif command == "sessions" and args.sessions_command in {"fork", "branch"}:
        sessions_fork_main(Path(args.workspace), args.session_id)
    elif command == "sessions" and args.sessions_command == "rewind":
        sessions_rewind_main(Path(args.workspace), args.session_id, args.message_count)
    elif command == "sessions" and args.sessions_command == "rewind-turn":
        sessions_rewind_turn_main(Path(args.workspace), args.session_id, args.turn_count)
    elif command == "approvals" and args.approvals_command == "list":
        approvals_list_main(Path(args.workspace))
    elif command == "approvals" and args.approvals_command == "summary":
        approvals_summary_main(Path(args.workspace))
    elif command == "approvals" and args.approvals_command == "show":
        approvals_show_main(Path(args.workspace), args.token)
    elif command == "approvals" and args.approvals_command == "approve":
        approvals_approve_main(Path(args.workspace), args.token)
    elif command == "approvals" and args.approvals_command == "reject":
        approvals_reject_main(Path(args.workspace), args.token)
    elif command == "approvals" and args.approvals_command == "approve-all":
        approvals_approve_all_main(Path(args.workspace))
    elif command == "approvals" and args.approvals_command == "reject-all":
        approvals_reject_all_main(Path(args.workspace))
    elif command == "workflow" and args.workflow_command == "repo":
        workflow_repo_main(Path(args.workspace), query=args.query, token=args.token, auto_apply=args.auto_apply, path_filter=args.path_filter, staged_only=args.staged_only)
    elif command == "config" and args.config_command == "show":
        config_show_main(Path(args.workspace))
    elif command == "timeline" and args.timeline_command == "show":
        timeline_show_main(Path(args.workspace), session_id=args.session, limit=args.limit)


if __name__ == "__main__":
    main()
