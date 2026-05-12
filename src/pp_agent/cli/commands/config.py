from __future__ import annotations

import json
from pathlib import Path

from pp_agent.app.bootstrap import load_settings, timeline_store_for
from pp_agent.cli.render.runtime import console


def config_show_main(workspace: Path) -> None:
    settings = load_settings(workspace)
    payload = {
        "workspace": str(settings.workspace),
        "session_dir": str(settings.session_store_dir()),
        "timeline_dir": str(timeline_store_for(workspace).root),
        "checkpoint_dir": str(settings.checkpoint_store_dir()),
        "history_db_path": str(settings.history_db_path()),
        "chroma_dir": str(settings.chroma_dir_path()),
        "global_dir": str(settings.global_dir),
        "project_dir": str(settings.project_dir),
        "base_url": settings.provider.base_url,
        "model": settings.model.model,
        "enable_thinking": settings.model.enable_thinking,
        "shell_timeout_seconds": settings.tool_policy.shell_timeout_seconds,
        "tool_policy": settings.tool_policy.model_dump(mode="json"),
        "tool_confirmation": {
            "write_file": settings.tool_policy.confirm_write_file,
            "edit_file": settings.tool_policy.confirm_edit_file,
            "run_shell": settings.tool_policy.confirm_run_shell,
            "high_risk_plan": settings.tool_policy.confirm_high_risk_plan,
        },
        "capabilities": {
            "builtin_tools": settings.capabilities.builtin_tools.model_dump(mode="json"),
            "skills": settings.capabilities.skills.model_dump(mode="json"),
            "mcp": settings.capabilities.mcp.model_dump(mode="json"),
            "extensions": settings.capabilities.extensions.model_dump(mode="json"),
        },
        "storage": settings.storage.model_dump(mode="json"),
        "memory": settings.memory.model_dump(mode="json"),
        "learning": settings.learning.model_dump(mode="json"),
    }
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))


__all__ = ["config_show_main"]
