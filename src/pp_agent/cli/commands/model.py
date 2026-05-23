from __future__ import annotations

from pathlib import Path
from typing import Any

from pp_agent.config import get_config_manager
from pp_agent.cli.render.runtime import console


def model_set_main(workspace: Path, session_id: str, model: str, *, busy: bool = False) -> dict[str, Any]:
    snapshot = get_config_manager(workspace).set_session_model(session_id, model)
    payload = {
        "session_id": session_id,
        "model": snapshot.settings.model.model,
        "config_version": snapshot.config_version,
        "pending_next_turn": bool(busy),
    }
    suffix = " (pending next turn)" if busy else ""
    console.print(f"model set to {payload['model']}{suffix}")
    return payload


__all__ = ["model_set_main"]
