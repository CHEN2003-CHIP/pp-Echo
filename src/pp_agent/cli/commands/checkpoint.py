from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pp_agent.api import sdk
from pp_agent.app.bootstrap import checkpoint_store_for, create_session_host, session_store_for
from pp_agent.cli.render.runtime import console
from pp_agent.runtime.git_checkpoint import GitCheckpointManager


def checkpoint_create_main(
    workspace: Path,
    session_id: str,
    *,
    reason: str = "manual",
    snapshot_type: str = "head_snapshot",
    force_stash: bool = False,
) -> None:
    manager = GitCheckpointManager(workspace, checkpoint_store_for(workspace), session_store_for(workspace))
    stats = manager._file_stats()
    chosen_type = snapshot_type
    if stats.has_dirty_workspace and chosen_type == "head_snapshot":
        preview = {
            "has_dirty_workspace": stats.has_dirty_workspace,
            "has_untracked_files": stats.has_untracked_files,
            "files": stats.files,
        }
        console.print(json.dumps(preview, ensure_ascii=False, indent=2))
        if force_stash:
            chosen_type = "stash_snapshot"
        else:
            console.print("Dirty workspace detected. Re-run with explicit stash intent to create a protection snapshot.")
            return
    payload = sdk.create_checkpoint(workspace, session_id, reason=reason, snapshot_type=chosen_type)
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))


def checkpoint_list_main(workspace: Path, *, session_id: Optional[str] = None) -> None:
    console.print(json.dumps(sdk.list_checkpoints(workspace, session_id=session_id), ensure_ascii=False, indent=2))


def checkpoint_restore_main(workspace: Path, checkpoint_id: str) -> None:
    manager = GitCheckpointManager(workspace, checkpoint_store_for(workspace), session_store_for(workspace))
    preview = manager.preview_restore(checkpoint_id).model_dump(mode="json")
    console.print(json.dumps(preview, ensure_ascii=False, indent=2))
    manager.restore_checkpoint(checkpoint_id)
    console.print(f"restored checkpoint: {checkpoint_id}")


def rewind_safe_main(
    workspace: Path,
    *,
    session_id: str,
    checkpoint_id: Optional[str] = None,
    turn_count: Optional[int] = None,
    message_count: Optional[int] = None,
    workspace_only: bool = False,
    conversation_only: bool = False,
) -> None:
    mode = "conversation_and_workspace"
    if workspace_only:
        mode = "workspace_only"
    elif conversation_only:
        mode = "conversation_only"
    preview = sdk.preview_rewind(
        workspace,
        session_id,
        checkpoint_id=checkpoint_id,
        turn_count=turn_count,
        message_count=message_count,
        mode=mode,
    )
    console.print(json.dumps(preview, ensure_ascii=False, indent=2))
    result = sdk.rewind_safe(
        workspace,
        session_id,
        checkpoint_id=checkpoint_id,
        turn_count=turn_count,
        message_count=message_count,
        mode=mode,
    )
    console.print(json.dumps(result, ensure_ascii=False, indent=2))
