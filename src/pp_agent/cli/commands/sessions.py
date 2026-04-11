from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pp_agent.api import sdk
from pp_agent.app.bootstrap import create_session_host, session_store_for
from pp_agent.cli.render.runtime import console
from pp_agent.cli.render.sessions import render_session_tree


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


def resolve_session_turn_ref(
    workspace: Path,
    ref: str,
    current_session_id: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    session_ref, turn_ref = split_session_turn_ref(ref, current_session_id=current_session_id)
    session_id = resolve_session_id(workspace, session_ref)
    turn_id = resolve_turn_id(workspace, session_id, turn_ref) if turn_ref else None
    return session_id, turn_id


def resume_target(workspace: Path, ref: str, current_session_id: Optional[str] = None) -> str:
    session_id, turn_id = resolve_session_turn_ref(workspace, ref, current_session_id=current_session_id)
    if current_session_id is not None:
        create_session_host(workspace).switch_session(workspace, current_session_id, session_id, target_head_id=turn_id)
    elif turn_id is not None:
        create_session_host(workspace).navigate_tree(workspace, session_id, turn_id)
    return session_id


def branch_session(workspace: Path, source_session_id: str, source_turn_id: Optional[str] = None) -> str:
    return sdk.fork_session(workspace, source_session_id, head_id=source_turn_id)["session_id"]


def rewind_session(workspace: Path, source_session_id: str, message_count: int) -> str:
    return sdk.rewind_session(workspace, source_session_id, message_count=message_count)["session_id"]


def rewind_session_turns(workspace: Path, source_session_id: str, turn_count: int) -> str:
    return sdk.rewind_session(workspace, source_session_id, turn_count=turn_count)["session_id"]


def sessions_list_main(workspace: Path) -> None:
    payload = sdk.list_sessions(workspace)
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))


def sessions_tree_main(
    workspace: Path,
    session_id: Optional[str] = None,
    sort_mode: str = "branch",
    view_mode: str = "default",
) -> None:
    sdk.get_session_tree(workspace, session_id=session_id, sort_mode=sort_mode, view_mode=view_mode)
    render_session_tree(
        workspace,
        current_session_id=session_id,
        focus_session_id=session_id,
        sort_mode=sort_mode,
        view_mode=view_mode,
    )


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


__all__ = [
    "branch_session",
    "resolve_session_id",
    "resolve_session_turn_ref",
    "resolve_turn_id",
    "resume_target",
    "rewind_session",
    "rewind_session_turns",
    "sessions_fork_main",
    "sessions_list_main",
    "sessions_rewind_main",
    "sessions_rewind_turn_main",
    "sessions_tree_main",
    "split_session_turn_ref",
]
