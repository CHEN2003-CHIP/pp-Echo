from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def load_legacy_session_payloads(root: Path, tree_name: str) -> dict[str, dict]:
    """【迁移工具】加载旧版会话数据"""
    tree_path = root / tree_name
    if tree_path.exists():
        return {}
    legacy_paths = sorted(path for path in root.glob("*.jsonl") if path.name != tree_name)
    sessions: dict[str, dict] = {}
    for path in legacy_paths:
        metadata: Optional[dict] = None
        messages: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("type") == "metadata":
                metadata = item["data"]
            elif item.get("type") == "message":
                messages.append(item["data"])
        if metadata is not None:
            sessions[metadata["id"]] = {"metadata": metadata, "messages": messages}
    return sessions
