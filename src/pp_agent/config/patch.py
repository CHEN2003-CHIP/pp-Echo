from __future__ import annotations

from copy import deepcopy
from typing import Any


def merge_patch(target: Any, patch: Any) -> Any:
    """递归合并patch到target"""
    if not isinstance(patch, dict):
        return deepcopy(patch)
    result = deepcopy(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
            continue
        result[key] = merge_patch(result.get(key), value)
    return result


def set_path_value(target: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    result = deepcopy(target)
    parts = _path_parts(path)
    cursor = result
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    cursor[parts[-1]] = deepcopy(value)
    return result


def delete_path_value(target: dict[str, Any], path: str) -> dict[str, Any]:
    result = deepcopy(target)
    parts = _path_parts(path)
    cursor = result
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            return result
        cursor = child
    cursor.pop(parts[-1], None)
    return result


def changed_paths_from_patch(patch: Any, prefix: str = "") -> list[str]:
    if not isinstance(patch, dict):
        return [prefix] if prefix else []
    paths: list[str] = []
    for key, value in patch.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and value:
            paths.extend(changed_paths_from_patch(value, path))
        else:
            paths.append(path)
    return paths


def _path_parts(path: str) -> list[str]:
    parts = [part.strip() for part in path.split(".") if part.strip()]
    if not parts:
        raise ValueError("Config path cannot be empty")
    return parts
