from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any

from pp_agent.config.patch import set_path_value


class RuntimeOverrideStore:
    """Process-local config overrides used by /debug and Web debug controls."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._by_workspace: dict[str, dict[str, Any]] = {}

    def get(self, workspace: Path) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._by_workspace.get(_key(workspace), {}))

    def set_path(self, workspace: Path, path: str, value: Any) -> dict[str, Any]:
        with self._lock:
            key = _key(workspace)
            current = self._by_workspace.get(key, {})
            updated = set_path_value(current, path, value)
            self._by_workspace[key] = updated
            return deepcopy(updated)

    def clear(self, workspace: Path) -> None:
        with self._lock:
            self._by_workspace.pop(_key(workspace), None)


def _key(workspace: Path) -> str:
    return str(workspace.resolve())


runtime_overrides = RuntimeOverrideStore()
