from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Optional, Union

from pp_agent.app import bootstrap
from pp_agent.web.session_manager import WebSessionManager


SessionManagerFactory = Callable[[Path], WebSessionManager]


class WebWorkspaceManager:
    """
    负责管理所有工作区、所有对话会话、所有生命周期 —— 相当于系统的顶层控制中心。
    """
    def __init__(
        self,
        initial_workspace: Path,
        *,
        initial_manager: Optional[WebSessionManager] = None,
        session_manager_factory: Optional[SessionManagerFactory] = None,
        state_dir: Optional[Path] = None,
        recent_limit: int = 20,
    ) -> None:
        self._lock = threading.Lock()
        self._recent_limit = recent_limit
        self._session_manager_factory = session_manager_factory or WebSessionManager
        self._active_workspace = self._normalize_workspace(initial_workspace)
        self._managers: dict[str, WebSessionManager] = {}
        if initial_manager is not None:
            self._managers[str(self._active_workspace)] = initial_manager
        self._state_path = self._resolve_state_path(self._active_workspace, state_dir)
        self._recent = self._load_recent()
        self._remember(self._active_workspace)

    @property
    def active_workspace(self) -> Path:
        with self._lock:
            return self._active_workspace

    def active_session_manager(self) -> WebSessionManager:
        with self._lock:
            workspace = self._active_workspace
            key = str(workspace)
            manager = self._managers.get(key)
            if manager is None:
                manager = self._session_manager_factory(workspace)
                self._managers[key] = manager
            return manager

    def summary(self) -> dict:
        with self._lock:
            return {"active": self._workspace_entry(self._active_workspace), "recent": list(self._recent)}

    def open_workspace(self, raw_path: str, *, confirmed: bool = False) -> dict:
        """
        这个函数就是「切换工作区（项目目录）」的核心方法！
        用户在界面上选择「打开文件夹 / 切换项目」时，就会调用它，负责校验路径、安全确认、切换目录、记住历史。
        """
        workspace = self._normalize_workspace(raw_path)
        if not workspace.exists():
            raise FileNotFoundError(f"Workspace does not exist: {workspace}")
        if not workspace.is_dir():
            raise NotADirectoryError(f"Workspace is not a directory: {workspace}")

        with self._lock:
            known = str(workspace) == str(self._active_workspace) or any(item["path"] == str(workspace) for item in self._recent)
            if not confirmed and not known:
                return {
                    "requires_confirmation": True,
                    "active": self._workspace_entry(self._active_workspace),
                    "candidate": self._workspace_entry(workspace),
                    "recent": list(self._recent),
                }
            self._active_workspace = workspace
            self._remember(workspace)
            return {
                "requires_confirmation": False,
                "active": self._workspace_entry(workspace),
                "candidate": None,
                "recent": list(self._recent),
            }

    def _remember(self, workspace: Path) -> None:
        """
        把当前打开的工作区（项目文件夹），更新到「最近打开列表」的最顶部，并且保持列表不超长，最后自动保存到磁盘。
        """
        entry = self._workspace_entry(workspace)
        entry["last_opened_at"] = time.time()
        self._recent = [item for item in self._recent if item.get("path") != entry["path"]]
        self._recent.insert(0, entry)
        self._recent = self._recent[: self._recent_limit]
        self._save_recent()

    @staticmethod
    def _normalize_workspace(value: Union[str, Path]) -> Path:
        raw = str(value).strip()
        if not raw:
            raise ValueError("Workspace path cannot be empty.")
        return Path(raw).expanduser().resolve()

    @staticmethod
    def _resolve_state_path(initial_workspace: Path, state_dir: Optional[Path]) -> Path:
        if state_dir is not None:
            state_dir.mkdir(parents=True, exist_ok=True)
            return state_dir / "web-workspaces.json"
        settings = bootstrap.load_settings(initial_workspace)
        for root in [settings.global_dir, settings.project_dir / "global"]:
            if WebWorkspaceManager._is_writable_dir(root):
                return root / "web-workspaces.json"
        return settings.project_dir / "web-workspaces.json"

    @staticmethod
    def _is_writable_dir(root: Path) -> bool:
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".web-workspaces-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    @staticmethod
    def _workspace_entry(workspace: Path) -> dict:
        return {
            "path": str(workspace),
            "name": workspace.name or str(workspace),
            "exists": workspace.exists(),
            "is_dir": workspace.is_dir(),
            "has_agents": (workspace / "AGENTS.md").exists(),
            "has_pp_agent": (workspace / ".pp-agent").exists(),
        }

    def _load_recent(self) -> list[dict]:
        if not self._state_path.exists():
            return []
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        items = data.get("recent", []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict) and isinstance(item.get("path"), str)]

    def _save_recent(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({"recent": self._recent}, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            return
