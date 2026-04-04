from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from pp_agent.app.bootstrap import session_store_for
from pp_agent.cli.render.runtime import RICH_AVAILABLE, compact_text, console
from pp_agent.runtime import AgentRuntime
from pp_agent.storage.sessions import SessionTreeEntry, SessionTurnEntry


def short_session(session_id: str) -> str:
    return session_id[:8]


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


def _message_preview_for_agent(agent: AgentRuntime, role: str, limit: int = 96) -> str:
    for message in reversed(agent.state.messages):
        if message.role != role:
            continue
        parts = [part.text.strip() for part in message.content if getattr(part, "text", "").strip()]
        text = " ".join(parts)
        return compact_text(text, limit=limit) if text else ""
    return ""


def _transient_tree_entry(agent: AgentRuntime) -> dict:
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
        "active_head_id": None,
    }


def _active_branch_ids(entry_index: dict[str, SessionTreeEntry], session_id: Optional[str]) -> set[str]:
    active_ids: set[str] = set()
    current_id = session_id
    while current_id:
        active_ids.add(current_id)
        parent_id = entry_index.get(current_id).parent_id if current_id in entry_index else None
        current_id = parent_id
    return active_ids


def _tree_line(entry: SessionTreeEntry, current_session_id: Optional[str], active_ids: set[str]) -> tuple[str, Optional[str]]:
    pending = " ?plan" if entry.pending_plan_token else ""
    line = (
        f"    {short_session(entry.id)}  [turn-{entry.turn_count}]  {entry.model}  "
        f"msgs={entry.message_count}  updated={datetime.fromtimestamp(entry.updated_at).strftime('%m-%d %H:%M')}{pending}"
    )
    return line, tree_style_for(entry.id, current_session_id, active_ids)


def _active_turn_ids(turn_entries: list[SessionTurnEntry], active_head_id: Optional[str]) -> set[str]:
    active_ids: set[str] = set()
    current_id = active_head_id
    entry_index = {entry.id: entry for entry in turn_entries}
    while current_id and current_id in entry_index:
        active_ids.add(current_id)
        current_id = entry_index[current_id].parent_id
    return active_ids


def _turn_line(entry: SessionTurnEntry, active_turn_id: Optional[str], active_turn_ids: set[str]) -> str:
    branch = ">>" if entry.id == active_turn_id else (" *" if entry.id in active_turn_ids else "  ")
    preview = entry.assistant_preview or entry.summary_preview or entry.user_preview
    suffix = f"  {preview}" if preview else ""
    kind = f"compact@{entry.summarized_message_count}" if entry.entry_type == "compaction" else f"turn-{entry.turn_number}"
    return f"{branch} {short_turn(entry.id)} [{kind}] {entry.status}{suffix}"


def render_session_tree(
    workspace: Path,
    *,
    current_session_id: Optional[str] = None,
    current_agent: Optional[AgentRuntime] = None,
    focus_session_id: Optional[str] = None,
    sort_mode: str = "branch",
) -> None:
    store = session_store_for(workspace)
    entries = store.tree()
    if current_agent is not None and all(entry.id != current_agent.session_id for entry in entries):
        transient = _transient_tree_entry(current_agent)
        entries.append(SessionTreeEntry.model_validate(transient))

    if sort_mode == "updated":
        entries = sorted(entries, key=lambda item: item.updated_at, reverse=True)

    entry_index = {entry.id: entry for entry in entries}
    active_ids = _active_branch_ids(entry_index, current_session_id)
    lines: list[tuple[str, Optional[str]]] = [("Session Tree", None), (f"View: {sort_mode}", None), ("", None), ("Recent Nodes", None)]
    for entry in sorted(entries, key=lambda item: item.updated_at, reverse=True)[:8]:
        lines.append(_tree_line(entry, current_session_id, active_ids))

    lines.extend([("", None), ("Branch View", None)])
    children: dict[Optional[str], list[SessionTreeEntry]] = {}
    for entry in entries:
        children.setdefault(entry.parent_id, []).append(entry)
    for sibling_list in children.values():
        sibling_list.sort(key=lambda item: (item.updated_at, item.id))

    def walk(parent_id: Optional[str], prefix: str = "") -> None:
        nodes = children.get(parent_id, [])
        for index, entry in enumerate(nodes):
            branch = "\\-" if index == len(nodes) - 1 else "|-"
            style = tree_style_for(entry.id, current_session_id, active_ids)
            pending = " ?plan" if entry.pending_plan_token else ""
            line = (
                f"{prefix}{branch}     {short_session(entry.id)}  [turn-{entry.turn_count}]  "
                f"{entry.model}  msgs={entry.message_count}  updated={datetime.fromtimestamp(entry.updated_at).strftime('%m-%d %H:%M')}{pending}"
            )
            lines.append((line, style))
            walk(entry.id, prefix + ("  " if index == len(nodes) - 1 else "| "))

    walk(None)
    if current_agent is not None and current_agent.session_id not in entry_index:
        lines.append(("\\- >>* unsaved current session", tree_style_for(current_agent.session_id, current_session_id, {current_agent.session_id})))

    focus_id = focus_session_id or current_session_id or (entries[0].id if entries else None)
    focus_turn_id: Optional[str] = None
    if focus_id and "@" in focus_id:
        focus_id, focus_turn_id = focus_id.split("@", 1)
    if focus_id:
        try:
            description = store.describe(focus_id)
        except FileNotFoundError:
            transient_focus = entry_index.get(focus_id)
            description = {
                "current": transient_focus.model_dump(mode="json") if transient_focus is not None else None,
                "parent": None,
                "children": [],
                "turns": [],
                "turn_focus": None,
            }
    else:
        description = {"current": None, "parent": None, "children": [], "turns": [], "turn_focus": None}
    lines.extend([("", None), ("Focus", None)])
    for row in render_tree_entry_preview("Current", description.get("current")):
        lines.append((row, None))
    for row in render_tree_entry_preview("Parent", description.get("parent")):
        lines.append((row, None))
    children_payload = description.get("children") or []
    if not children_payload:
        lines.append(("Children: none", None))
    else:
        first_child = children_payload[0]
        if isinstance(first_child, dict):
            for row in render_tree_entry_preview("Child", first_child):
                lines.append((row, None))
    lines.extend([("", None), ("Turn Tree", None)])
    turns = description.get("turns") or []
    if not turns:
        lines.append(("No turns yet.", None))
    else:
        turn_entries = [SessionTurnEntry.model_validate(item) for item in turns]
        active_turn_id = focus_turn_id or (description.get("current") or {}).get("active_head_id")
        active_turn_ids = _active_turn_ids(turn_entries, active_turn_id)
        for entry in turn_entries:
            lines.append((_turn_line(entry, active_turn_id, active_turn_ids), None))
        turn_focus = description.get("turn_focus") or {}
        current_turn = turn_focus.get("current")
        if current_turn:
            lines.append(("", None))
            for row in render_turn_entry_preview("Turn Focus", current_turn):
                lines.append((row, None))

    focus_short = short_session(focus_id) if focus_id else "current"
    turn_hint = f"{focus_short}@{short_turn(focus_turn_id)}" if focus_id and focus_turn_id else None
    lines.append(("", None))
    lines.append(("Branch Navigation", None))
    lines.append(("  Active branch lines are green when rich output is available.", None))
    lines.append(("  /tree updated                 switch to the recent-first view", None))
    lines.append((f"  /tree focus {focus_short}           move the tree focus without changing chat", None))
    lines.append((f"  /resume {focus_short}               switch chat to the focused session head", None))
    if turn_hint:
        lines.append((f"  /resume {turn_hint}       switch chat to that historical turn and continue", None))
    lines.append((f"  /branch {focus_short}               branch from the focused session head", None))
    lines.append((f"  /rewind-turn {focus_short} 1        branch from one full turn earlier", None))
    lines.append(("  /compact                      write a compaction node for the current branch", None))
    print_tree_lines(lines)


__all__ = [
    "render_session_tree",
    "render_tree_entry_preview",
    "render_turn_entry_preview",
    "short_session",
    "short_turn",
]
