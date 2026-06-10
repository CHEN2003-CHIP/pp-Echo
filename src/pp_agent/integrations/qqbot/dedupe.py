from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class QQEventDedupeStore:
    def __init__(self, path: Path, *, ttl_seconds: int = 600, clock=time.time) -> None:
        self.path = path
        self.ttl_seconds = max(1, int(ttl_seconds))
        self._clock = clock
        self._lock = threading.Lock()

    def seen_or_mark(self, event_key: str) -> bool:
        with self._lock:
            now = float(self._clock())
            data = {key: at for key, at in self._load().items() if isinstance(at, (int, float)) and now - float(at) <= self.ttl_seconds}
            if event_key in data:
                self._save(data)
                return True
            data[event_key] = now
            self._save(data)
            return False

    def _load(self) -> dict[str, float]:
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
            logger.warning("Recovered corrupt QQ dedupe store at %s", backup)
            self._save({})
            return {}

    def _save(self, data: dict[str, float]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

