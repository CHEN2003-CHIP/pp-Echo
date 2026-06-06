from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

from pp_agent.config.patch import set_path_value


class SessionConfigStore:
    """Persistent per-session config overrides."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.root = self.workspace / ".pp-agent" / "session-config"
        self._lock = RLock()

    def load(self, session_id: str | None) -> dict[str, Any]:
        """
        根据 session_id 加载配置文件，如果不存在则返回空字典。
        """
        if not session_id:
            return {}
        path = self._path(session_id)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid session config for {session_id}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Invalid session config for {session_id}: expected object")
        return data

    def set_path(self, session_id: str, path: str, value: Any) -> dict[str, Any]:
        if not session_id:
            raise ValueError("session_id is required")
        with self._lock:
            updated = set_path_value(self.load(session_id), path, value)
            self._write(session_id, updated)
            return updated

    def save(self, session_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if not session_id:
            raise ValueError("session_id is required")
        with self._lock:
            self._write(session_id, data)
            return data

    def set_active_profile(self, session_id: str, profile: str | None) -> dict[str, Any]:
        data = self.load(session_id)
        if profile:
            data["active_profile"] = profile
        else:
            data.pop("active_profile", None)
        return self.save(session_id, data)

    def set_model(self, session_id: str, model: str) -> dict[str, Any]:
        model = model.strip()
        if not model:
            raise ValueError("Model cannot be empty")
        provider = model.split("/", 1)[0] if "/" in model else None
        payload = self.set_path(session_id, "model.model", model)
        if provider:
            payload = self.set_path(session_id, "model.provider", provider)
        return payload

    def _path(self, session_id: str) -> Path:
        """
        由 session_id 生成配置文件路径。
        """
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in session_id)
        return self.root / f"{safe}.json"

    def _write(self, session_id: str, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(session_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
