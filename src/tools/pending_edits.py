from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


class PendingEditStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def stage(self, *, operation: str, path: Path, before: str, after: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        token = str(uuid.uuid4())
        payload = {
            "token": token,
            "operation": operation,
            "path": str(path),
            "before": before,
            "after": after,
            "created_at": time.time(),
            "details": details or {},
        }
        target = self.root / f"{token}.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def load(self, token: str) -> dict[str, Any]:
        target = self.root / f"{token}.json"
        if not target.exists():
            raise FileNotFoundError(f"Pending edit token not found: {token}")
        return json.loads(target.read_text(encoding="utf-8"))

    def apply(self, token: str) -> dict[str, Any]:
        payload = self.load(token)
        path = Path(payload["path"])
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != payload["before"]:
            raise ValueError("File changed since the edit was staged. Re-read the file and stage a new edit.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload["after"], encoding="utf-8")
        (self.root / f"{token}.json").unlink(missing_ok=True)
        payload["applied"] = True
        return payload

    def list(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                items.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return items