from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pp_agent.app.bootstrap import load_settings, timeline_store_for
from pp_agent.config import ConfigConflictError, get_config_manager
from pp_agent.cli.render.runtime import console


def config_show_main(workspace: Path) -> None:
    manager = get_config_manager(workspace)
    snapshot = manager.get_effective_snapshot()
    settings = snapshot.settings
    payload = {
        "config_hash": snapshot.config_hash,
        "effective_hash": snapshot.effective_hash,
        "config_version": snapshot.config_version,
        "reload_policy": snapshot.reload_policy,
        "source_map": snapshot.source_map,
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


def config_schema_main(workspace: Path) -> None:
    console.print(json.dumps(get_config_manager(workspace).schema(), ensure_ascii=False, indent=2))


def config_set_main(workspace: Path, path: str, raw_value: str, *, base_hash: str | None = None) -> dict[str, Any]:
    value = parse_config_value(raw_value)
    try:
        snapshot = get_config_manager(workspace).set_path(path, value, base_hash=base_hash)
    except ConfigConflictError as exc:
        message = f"Config conflict: expected {exc.expected_hash}, current {exc.actual_hash}"
        console.print(message)
        return {"ok": False, "conflict": True, "message": message, "actual_hash": exc.actual_hash}
    payload = snapshot.model_dump(mode="json")
    console.print(json.dumps({"ok": True, "config_hash": payload["config_hash"], "reload_policy": payload["reload_policy"]}, ensure_ascii=False, indent=2))
    return payload


def config_patch_main(workspace: Path, raw_patch: str, *, base_hash: str | None = None) -> dict[str, Any]:
    patch = parse_config_value(raw_patch)
    if not isinstance(patch, dict):
        raise ValueError("Config patch must be a JSON object")
    try:
        snapshot = get_config_manager(workspace).patch_project_config(patch, base_hash=base_hash)
    except ConfigConflictError as exc:
        message = f"Config conflict: expected {exc.expected_hash}, current {exc.actual_hash}"
        console.print(message)
        return {"ok": False, "conflict": True, "message": message, "actual_hash": exc.actual_hash}
    payload = snapshot.model_dump(mode="json")
    console.print(json.dumps({"ok": True, "config_hash": payload["config_hash"], "reload_policy": payload["reload_policy"]}, ensure_ascii=False, indent=2))
    return payload


def parse_config_value(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


__all__ = ["config_patch_main", "config_schema_main", "config_set_main", "config_show_main", "parse_config_value"]
