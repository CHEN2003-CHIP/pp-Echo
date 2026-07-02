from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ActivityDisplayItem(BaseModel):
    kind: str = "event"
    title: str
    summary: str = ""
    detail: str = ""
    status: str = "success"
    timestamp: Optional[float] = None


class PersistedActivityBlock(BaseModel):
    record_type: Literal["activity_block"] = "activity_block"
    version: int = 1
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    turn_id: str
    created_at: float = Field(default_factory=time.time)
    status: Literal["running", "done", "error"] = "done"
    title: str = "Activity"
    summary: str = ""
    duration_ms: Optional[int] = None
    event_count: int = 0
    items: list[ActivityDisplayItem] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)


class ActivityBlockStore:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "activity-blocks.jsonl"

    def append(self, block: PersistedActivityBlock) -> PersistedActivityBlock:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(block.model_dump(mode="json"), ensure_ascii=False) + "\n")
        return block

    def upsert(self, block: PersistedActivityBlock) -> PersistedActivityBlock:
        blocks = self.list_session(block.session_id, limit=10000)
        replaced = False
        next_blocks: list[PersistedActivityBlock] = []
        for existing in blocks:
            if existing.turn_id == block.turn_id:
                next_blocks.append(block)
                replaced = True
            else:
                next_blocks.append(existing)
        if not replaced:
            next_blocks.append(block)
        self._rewrite_session(block.session_id, next_blocks)
        return block

    def list_session(self, session_id: str, limit: int = 50) -> list[PersistedActivityBlock]:
        blocks = [block for block in self._load_all() if block.session_id == session_id]
        return blocks[-limit:]

    def _load_all(self) -> list[PersistedActivityBlock]:
        if not self.path.exists():
            return []
        blocks: list[PersistedActivityBlock] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item: Any = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("record_type") == "activity_block":
                blocks.append(PersistedActivityBlock.model_validate(item))
        return blocks

    def _rewrite_session(self, session_id: str, session_blocks: list[PersistedActivityBlock]) -> None:
        others = [block for block in self._load_all() if block.session_id != session_id]
        merged = [*others, *session_blocks]
        with self.path.open("w", encoding="utf-8") as handle:
            for block in merged:
                handle.write(json.dumps(block.model_dump(mode="json"), ensure_ascii=False) + "\n")
