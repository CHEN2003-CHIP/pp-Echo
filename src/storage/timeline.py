from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from agent_core.runtime.monitor import RuntimeStatusSnapshot
from agent_core.runtime.types import AgentEvent, PlanStep


class TimelineEntry(BaseModel):
    id: str
    session_id: str
    created_at: float
    event_type: str
    turn_id: int = 0
    phase: Optional[str] = None
    tool_name: Optional[str] = None
    message: Optional[str] = None
    is_error: bool = False
    runtime: Optional[RuntimeStatusSnapshot] = None
    plan_step: Optional[PlanStep] = None
    details: dict[str, object] = Field(default_factory=dict)


class TimelineStore:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "agent-timeline.jsonl"

    def append(self, session_id: str, event: AgentEvent) -> TimelineEntry:
        runtime = event.details.get("runtime")
        entry = TimelineEntry(
            id=str(uuid.uuid4()),
            session_id=session_id,
            created_at=time.time(),
            event_type=event.type,
            turn_id=int(event.details.get("turn_id") or (runtime or {}).get("turn_id") or 0),
            phase=event.details.get("phase") or (runtime or {}).get("phase"),
            tool_name=event.tool_name,
            message=event.message,
            is_error=event.is_error,
            runtime=RuntimeStatusSnapshot.model_validate(runtime) if runtime else None,
            plan_step=event.plan_step.model_copy(deep=True) if event.plan_step is not None else None,
            details=self._filtered_details(event.details),
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n")
        return entry

    def list_session(self, session_id: str, limit: int = 50, event_types: Optional[list[str]] = None) -> list[TimelineEntry]:
        entries = [entry for entry in self._load_all() if entry.session_id == session_id]
        if event_types:
            allowed = set(event_types)
            entries = [entry for entry in entries if entry.event_type in allowed]
        return entries[-limit:]

    def list_recent(self, limit: int = 50, event_types: Optional[list[str]] = None) -> list[TimelineEntry]:
        entries = self._load_all()
        if event_types:
            allowed = set(event_types)
            entries = [entry for entry in entries if entry.event_type in allowed]
        return entries[-limit:]

    def _load_all(self) -> list[TimelineEntry]:
        if not self.path.exists():
            return []
        entries: list[TimelineEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entries.append(TimelineEntry.model_validate(json.loads(line)))
        return entries

    @staticmethod
    def _filtered_details(details: dict[str, object]) -> dict[str, object]:
        payload = dict(details)
        payload.pop("runtime", None)
        return payload
