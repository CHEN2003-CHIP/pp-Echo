from __future__ import annotations

from pathlib import Path
from typing import Any

from pp_agent.config import get_config_manager
from pp_agent.cli.commands.config import parse_config_value
from pp_agent.cli.render.runtime import console


def debug_set_main(workspace: Path, path: str, raw_value: str, *, session_id: str | None = None) -> dict[str, Any]:
    value = parse_config_value(raw_value)
    snapshot = get_config_manager(workspace).set_runtime_override(path, value, session_id=session_id)
    payload = {
        "path": path,
        "value": value,
        "config_version": snapshot.config_version,
        "reload_policy": snapshot.reload_policy,
    }
    console.print(f"debug override set: {path}")
    return payload


__all__ = ["debug_set_main"]
