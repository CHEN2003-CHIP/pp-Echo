from __future__ import annotations

import json
from pathlib import Path

from pp_agent.api import sdk
from pp_agent.app import bootstrap
from pp_agent.cli.render.runtime import console
from pp_agent.config import get_config_manager
from pp_agent.config.schema import ConfigValidationError, config_error
from pp_agent.skills import skill_search_roots


def skills_list_main(workspace: Path) -> list[dict]:
    payload = sdk.list_capabilities(workspace, kind="skill")
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def skills_show_main(workspace: Path, name: str) -> dict:
    payload = sdk.get_capability(workspace, kind="skill", name=name)
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def skills_roots_main(workspace: Path) -> list[dict]:
    settings = bootstrap.load_settings(workspace)
    roots = skill_search_roots(workspace, settings.global_dir, config=settings.capabilities.skills)
    payload = [root.model_dump(mode="json") for root in roots]
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def skills_add_dir_main(workspace: Path, directory: Path) -> dict:
    workspace = workspace.resolve()
    resolved = _resolve_skill_directory(workspace, directory)
    _validate_skill_directory(resolved)
    value = _config_path_value(workspace, resolved)

    manager = get_config_manager(workspace)
    project_config = manager.get_project_config()
    capabilities = project_config.get("capabilities", {})
    skill_config = capabilities.get("skills", {}) if isinstance(capabilities, dict) else {}
    existing = list(skill_config.get("custom_directories", [])) if isinstance(skill_config, dict) else []
    normalized_existing = {_normalize_path_value(workspace, str(item)) for item in existing}
    if _normalize_path_value(workspace, value) not in normalized_existing:
        existing.append(value)

    snapshot = manager.patch_project_config({"capabilities": {"skills": {"custom_directories": existing}}})
    payload = {
        "added": value,
        "resolved": str(resolved),
        "custom_directories": snapshot.settings.capabilities.skills.custom_directories,
    }
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def _resolve_skill_directory(workspace: Path, directory: Path) -> Path:
    candidate = directory.expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    return candidate.resolve()


def _validate_skill_directory(directory: Path) -> None:
    if not directory.exists():
        raise ConfigValidationError([config_error("directory", "not_found", f"Skill directory not found: {directory}")])
    if not directory.is_dir():
        raise ConfigValidationError([config_error("directory", "type", f"Skill path is not a directory: {directory}")])
    if not any(directory.glob("**/SKILL.md")):
        raise ConfigValidationError([config_error("directory", "not_found", "No SKILL.md found in this directory")])


def _config_path_value(workspace: Path, directory: Path) -> str:
    try:
        relative = directory.relative_to(workspace)
    except ValueError:
        return str(directory)
    return relative.as_posix() or "."


def _normalize_path_value(workspace: Path, value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = workspace / path
    try:
        return str(path.resolve())
    except (OSError, PermissionError):
        return str(path.absolute())


__all__ = ["skills_list_main", "skills_show_main", "skills_roots_main", "skills_add_dir_main"]
