from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional


class PendingActionStore:
    """【待处理操作本地文件存储】"""
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def stage(
        self,
        *,
        action_type: str,
        target_path: Optional[Path] = None,
        before: str = "",
        after: str = "",
        command: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """将一个待处理操作添加到存储中"""
        token = str(uuid.uuid4())
        payload = {
            "token": token,
            "action_type": action_type,
            "target_path": str(target_path) if target_path else None,
            "before": before,
            "after": after,
            "command": command,
            "created_at": time.time(),
            "details": details or {},
        }
        target = self.root / f"{token}.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def load(self, token: str) -> dict[str, Any]:
        target = self.root / f"{token}.json"
        if not target.exists():
            raise FileNotFoundError(f"Pending action token not found: {token}")
        return json.loads(target.read_text(encoding="utf-8"))

    def remove(self, token: str) -> None:
        (self.root / f"{token}.json").unlink(missing_ok=True)

    def list(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                items.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return items