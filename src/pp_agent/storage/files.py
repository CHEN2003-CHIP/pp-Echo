from __future__ import annotations

from pathlib import Path


def resolve_workspace_path(workspace: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = workspace / path
    resolved = path.resolve()
    if workspace.resolve() not in [resolved, *resolved.parents]:
        raise PermissionError(f"Path is outside workspace: {resolved}")
    return resolved
