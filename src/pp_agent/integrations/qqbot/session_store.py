from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class QQSessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def resolve(self, conversation_key: str, conversation_type: str, *, session_id_factory: Callable[[], str] | None = None) -> str:
        with self._lock:
            data = self._load()
            now = _utc_now()
            item = data.get(conversation_key)
            if isinstance(item, dict) and item.get("session_id"):
                item["updated_at"] = now
                self._save(data)
                return str(item["session_id"])
            session_id = session_id_factory() if session_id_factory is not None else _fallback_session_id()
            data[conversation_key] = {
                "session_id": session_id,
                "conversation_type": conversation_type,
                "created_at": now,
                "updated_at": now,
            }
            self._save(data)
            return session_id

    def replace(self, conversation_key: str, conversation_type: str, session_id: str) -> str:
        with self._lock:
            data = self._load()
            now = _utc_now()
            existing = data.get(conversation_key) if isinstance(data.get(conversation_key), dict) else {}
            data[conversation_key] = {
                "session_id": session_id,
                "conversation_type": conversation_type,
                "created_at": existing.get("created_at") or now,
                "updated_at": now,
            }
            self._save(data)
            return session_id

    def _load(self) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._save({})
            return {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            backup = self.path.with_name(f"{self.path.name}.corrupt.{int(time.time())}")
            self.path.replace(backup)
            logger.warning("Recovered corrupt QQ session store at %s", backup)
            self._save({})
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _fallback_session_id() -> str:
    import uuid

    return str(uuid.uuid4())
