from __future__ import annotations

from pathlib import Path

from pp_agent.cli.commands.approvals import (
    approve_or_execute_pending_action,
    load_pending_action,
    reject_pending_action,
)
from pp_agent.cli.commands.sessions import (
    branch_session,
    resolve_session_id,
    resolve_session_turn_ref,
    resume_target,
    rewind_session,
    rewind_session_turns,
)
from pp_agent.cli.commands.timeline import timeline_show_main
from pp_agent.cli.render.approvals import render_approval_panel
from pp_agent.cli.render.queue import render_queue_panel
from pp_agent.cli.render.runtime import console, render_runtime_status, render_settings
from pp_agent.cli.render.sessions import render_session_tree


def handle_queue_command(agent, raw: str) -> bool:
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


def handle_command(agent, raw: str, workspace: Path) -> str:
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
        focus_session_id = None
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


__all__ = ["handle_command", "handle_queue_command"]
