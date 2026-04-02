from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pp_agent.domain.checkpoints import CheckpointEntry


class CheckpointStore:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, entry: CheckpointEntry) -> CheckpointEntry:
        self.save(entry)
        return entry

    def save(self, entry: CheckpointEntry) -> Path:
        target = self.root / f"{entry.checkpoint_id}.json"
        target.write_text(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def load(self, checkpoint_id: str) -> CheckpointEntry:
        target = self.root / f"{checkpoint_id}.json"
        if not target.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_id}")
        return CheckpointEntry.model_validate(json.loads(target.read_text(encoding="utf-8")))

    def list(self, workspace: Optional[Path] = None, session_id: Optional[str] = None) -> list[CheckpointEntry]:
        items: list[CheckpointEntry] = []
        workspace_root = str(workspace.resolve()) if workspace is not None else None
        for path in sorted(self.root.glob("*.json")):
            try:
                entry = CheckpointEntry.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, ValueError):
                continue
            if workspace_root is not None and entry.workspace_root != workspace_root:
                continue
            if session_id is not None and entry.session_id != session_id:
                continue
            items.append(entry)
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def find_for_session_head(
        self,
        session_id: str,
        head_id: Optional[str],
        turn_id: Optional[str] = None,
        snapshot_type: Optional[str] = None,
    ) -> list[CheckpointEntry]:
        items = self.list(session_id=session_id)
        matches: list[CheckpointEntry] = []
        for item in items:
            if item.head_id != head_id:
                continue
            if turn_id is not None and item.turn_id != turn_id:
                continue
            if snapshot_type is not None and item.snapshot_type != snapshot_type:
                continue
            matches.append(item)
        return matches

    def mark_restored(self, checkpoint_id: str) -> CheckpointEntry:
        return self._mark(checkpoint_id, "restored")

    def mark_dropped(self, checkpoint_id: str) -> CheckpointEntry:
        return self._mark(checkpoint_id, "dropped")

    def mark_failed(self, checkpoint_id: str) -> CheckpointEntry:
        return self._mark(checkpoint_id, "failed")

    def mark_missing(self, checkpoint_id: str) -> CheckpointEntry:
        return self._mark(checkpoint_id, "missing")

    def _mark(self, checkpoint_id: str, status: str) -> CheckpointEntry:
        entry = self.load(checkpoint_id)
        entry.status = status
        self.save(entry)
        return entry
