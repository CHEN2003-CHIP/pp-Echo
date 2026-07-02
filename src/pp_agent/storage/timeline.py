from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from pp_agent.domain import PlanStep, RuntimeStatusSnapshot
FORMAL_TURN_PHASES = {"idle", "planning", "awaiting_approval", "executing", "draining_queue"}


class TimelineEntry(BaseModel):
    """
    【会话时间线事件条目】
    标准化记录 AI Agent 会话中的每一个运行事件
    用于：会话回放、调试日志、行为审计、错误追溯、运行监控
    """
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
    """
    【会话时间线本地文件存储】
    采用 JSONL 格式（每行一个 JSON 对象）持久化存储所有会话事件
    支持实时追加写入，不丢失日志，便于后续读取/回放/调试
    """
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "agent-timeline.jsonl"

    def append(self, session_id: str, event: Any) -> TimelineEntry:
        runtime = event.details.get("runtime")
        timestamp = getattr(event, "timestamp", None)
        entry = TimelineEntry(
            id=str(uuid.uuid4()),
            session_id=session_id,
            created_at=float(timestamp) if isinstance(timestamp, (int, float)) else time.time(),
            event_type=event.type,
            turn_id=self._turn_id_from_event(event, runtime),
            phase=self._phase_from_event(event, runtime),
            tool_name=event.tool_name,
            message=event.message,
            is_error=event.is_error,
            runtime=RuntimeStatusSnapshot.model_validate(runtime) if runtime else None,
            plan_step=event.plan_step.model_copy(deep=True) if event.plan_step is not None else None,
            details=self._filtered_details(event),
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
    def _filtered_details(event: Any) -> dict[str, object]:
        details = getattr(event, "details", {}) or {}
        payload = dict(details)
        payload.pop("runtime", None)
        runtime_event = event.model_dump(mode="json") if hasattr(event, "model_dump") else {}
        if isinstance(runtime_event, dict):
            runtime_event.setdefault("details", payload)
            payload.setdefault("runtime_event", runtime_event)
        return payload

    @staticmethod
    def _turn_id_from_event(event: Any, runtime: object) -> int:
        value = getattr(event, "turn_id", None)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            pass
        if not isinstance(runtime, dict):
            return 0
        value = runtime.get("turn_id")
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _phase_from_event(event: Any, runtime: object) -> Optional[str]:
        value = getattr(event, "phase", None)
        if isinstance(value, str) and value:
            return value
        if not isinstance(runtime, dict):
            return None
        value = runtime.get("phase")
        return value if isinstance(value, str) and value in FORMAL_TURN_PHASES else None


