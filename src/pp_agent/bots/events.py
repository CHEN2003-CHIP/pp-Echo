from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import date
from pathlib import Path
from typing import Any

from pp_agent.bots.models import BotEvent, BotStatus, NormalizedBotMessage
from pp_agent.bots.paths import (
    ensure_bot_dirs,
    get_bot_events_path,
    get_bot_logs_dir,
    get_bot_messages_path,
    get_bot_runs_dir,
    get_bot_status_path,
    get_bot_traces_dir,
)


class BotEventStore:
    def __init__(self, workspace: Path, *, buffer_size: int = 200) -> None:
        self.workspace = Path(workspace)
        self._buffers: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=buffer_size))

    def publish(self, event: BotEvent) -> BotEvent:
        ensure_bot_dirs(self.workspace, event.platform, event.bot_id)
        payload = event.model_dump(mode="json", exclude_none=True)
        _append_jsonl(get_bot_events_path(self.workspace, event.platform, event.bot_id), payload)
        self._buffers[event.bot_id].append(payload)
        self._append_log(event)
        self._merge_status_from_event(event)
        return event

    def record_message(self, message: NormalizedBotMessage) -> None:
        _append_jsonl(
            get_bot_messages_path(self.workspace, message.source.platform, message.source.bot_id),
            message.model_dump(mode="json", exclude_none=True),
        )

    def write_status(self, status: BotStatus) -> None:
        path = get_bot_status_path(self.workspace, status.platform, status.bot_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def read_status(self, platform: str, bot_id: str) -> dict[str, Any] | None:
        path = get_bot_status_path(self.workspace, platform, bot_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def list_events(self, platform: str, bot_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        path = get_bot_events_path(self.workspace, platform, bot_id)
        return _read_jsonl_tail(path, limit=max(1, min(1000, limit)))

    def list_messages(self, platform: str, bot_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        path = get_bot_messages_path(self.workspace, platform, bot_id)
        return _read_jsonl_tail(path, limit=max(1, min(1000, limit)))

    def list_runs(self, platform: str, bot_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        runs_dir = get_bot_runs_dir(self.workspace, platform, bot_id)
        return _read_json_files_tail(runs_dir, limit=max(1, min(500, limit)))

    def list_traces(self, platform: str, bot_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        traces_dir = get_bot_traces_dir(self.workspace, platform, bot_id)
        return _read_json_files_tail(traces_dir, limit=max(1, min(500, limit)))

    def write_run(self, platform: str, bot_id: str, run_id: str, payload: dict[str, Any]) -> Path:
        run_dir = get_bot_runs_dir(self.workspace, platform, bot_id, date.today())
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{run_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        return path

    def read_logs(self, platform: str, bot_id: str, *, limit: int = 200) -> dict[str, list[str]]:
        logs_dir = get_bot_logs_dir(self.workspace, platform, bot_id)
        return {
            "bot": _tail_text(logs_dir / "bot.log", limit),
            "error": _tail_text(logs_dir / "error.log", limit),
        }

    def _append_log(self, event: BotEvent) -> None:
        logs_dir = get_bot_logs_dir(self.workspace, event.platform, event.bot_id)
        logs_dir.mkdir(parents=True, exist_ok=True)
        line = f"{event.timestamp.isoformat()} [{event.level.upper()}] {event.type}: {_redact(event.summary)}\n"
        (logs_dir / "bot.log").open("a", encoding="utf-8").write(line)
        if event.level == "error":
            (logs_dir / "error.log").open("a", encoding="utf-8").write(line)

    def _merge_status_from_event(self, event: BotEvent) -> None:
        path = get_bot_status_path(self.workspace, event.platform, event.bot_id)
        status = self.read_status(event.platform, event.bot_id) or {}
        status["bot_id"] = event.bot_id
        status["platform"] = event.platform
        status["last_event_at"] = event.timestamp.isoformat()
        if event.type == "message_received":
            status["last_message_at"] = event.timestamp.isoformat()
            status["bot_state"] = "receiving"
        elif event.type == "agent_run_started":
            status["bot_state"] = "running_agent"
        elif event.type == "approval_required":
            status["bot_state"] = "waiting_approval"
        elif event.type in {"agent_run_completed", "reply_sent"}:
            status["bot_state"] = "idle"
        elif event.type == "reply_sent":
            status["last_reply_at"] = event.timestamp.isoformat()
        elif event.type in {"reply_failed", "error"}:
            status["bot_state"] = "error"
            status["last_error"] = event.summary
        if event.type == "reply_sent":
            status["last_reply_at"] = event.timestamp.isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _read_jsonl_tail(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    items: list[dict[str, Any]] = []
    for line in lines[-limit * 2 :]:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            items.append(payload)
    return items[-limit:]


def _read_json_files_tail(root: Path, *, limit: int) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    paths = sorted(root.glob("*/*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]
    items: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payload.setdefault("path", str(path))
            items.append(payload)
    return items


def _tail_text(path: Path, limit: int) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []


def _redact(value: str) -> str:
    text = str(value)
    for marker in ("secret", "token", "password"):
        text = text.replace(marker, "[redacted]")
        text = text.replace(marker.upper(), "[REDACTED]")
    return text
