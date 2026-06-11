from __future__ import annotations

import json
import os
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
        event.event_id = str(self._next_event_id(event.platform, event.bot_id))
        payload = event.model_dump(mode="json", exclude_none=True)
        payload = redact_payload(payload)
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

    def list_events(self, platform: str, bot_id: str, *, limit: int = 100, after_id: str | int | None = None) -> list[dict[str, Any]]:
        path = get_bot_events_path(self.workspace, platform, bot_id)
        items = _read_jsonl_tail(path, limit=5000)
        if after_id not in (None, ""):
            cursor = _event_id_number(after_id)
            items = [item for item in items if _event_id_number(item.get("event_id")) > cursor]
        return items[-max(1, min(1000, limit)) :]

    def list_messages(self, platform: str, bot_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        path = get_bot_messages_path(self.workspace, platform, bot_id)
        return _read_jsonl_tail(path, limit=max(1, min(1000, limit)))

    def list_runs(self, platform: str, bot_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        runs_dir = get_bot_runs_dir(self.workspace, platform, bot_id)
        return _read_json_files_tail(runs_dir, limit=max(1, min(500, limit)))

    def list_traces(self, platform: str, bot_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        traces_dir = get_bot_traces_dir(self.workspace, platform, bot_id)
        return _read_json_files_tail(traces_dir, limit=max(1, min(500, limit)), include_corrupted=True)

    def write_run(self, platform: str, bot_id: str, run_id: str, payload: dict[str, Any]) -> Path:
        run_dir = get_bot_runs_dir(self.workspace, platform, bot_id, date.today())
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{run_id}.json"
        path.write_text(json.dumps(redact_payload(payload), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        return path

    def write_trace(self, platform: str, bot_id: str, trace_id: str, payload: dict[str, Any]) -> Path:
        trace_dir = get_bot_traces_dir(self.workspace, platform, bot_id, date.today())
        trace_dir.mkdir(parents=True, exist_ok=True)
        path = trace_dir / f"{trace_id}.json"
        path.write_text(json.dumps(redact_payload(payload), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
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
            status["agent_state"] = "receiving"
        elif event.type == "agent_run_started":
            status["bot_state"] = "running_agent"
            status["agent_state"] = "running_agent"
            status["last_run_at"] = event.timestamp.isoformat()
        elif event.type == "approval_required":
            status["bot_state"] = "waiting_approval"
            status["agent_state"] = "waiting_approval"
        elif event.type in {"agent_run_completed", "reply_sent"}:
            status["bot_state"] = "idle"
            status["agent_state"] = "idle"
        elif event.type in {"reply_failed", "error", "run_timed_out", "background_task_failed"}:
            status["bot_state"] = "error"
            status["agent_state"] = "error"
            status["last_error"] = event.summary
        elif event.type == "run_cancelled":
            status["bot_state"] = "idle"
            status["agent_state"] = "idle"
        if event.type == "reply_sent":
            status["last_reply_at"] = event.timestamp.isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(redact_payload(status), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    def _next_event_id(self, platform: str, bot_id: str) -> int:
        existing = self.list_events(platform, bot_id, limit=1)
        if not existing:
            return 1
        return _event_id_number(existing[-1].get("event_id")) + 1


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


def _read_json_files_tail(root: Path, *, limit: int, include_corrupted: bool = False) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    paths = sorted(root.glob("*/*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]
    items: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            if include_corrupted:
                items.append({"path": str(path), "corrupted": True, "error": "invalid_json"})
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
    for marker in _secret_values():
        if marker:
            text = text.replace(marker, "***REDACTED***")
    for marker in ("secret", "token", "password"):
        text = text.replace(marker, "***REDACTED***")
        text = text.replace(marker.upper(), "***REDACTED***")
    return text


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("secret", "token", "password", "cookie")):
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value


def _secret_values() -> tuple[str, ...]:
    keys = ("PP_ECHO_QQBOT_APP_SECRET", "PP_ECHO_QQBOT_ACCESS_TOKEN", "PP_ECHO_QQBOT_TOKEN")
    return tuple(value for key in keys if (value := os.environ.get(key)))


def _event_id_number(value: Any) -> int:
    text = str(value or "")
    if text.startswith("evt_"):
        return 0
    try:
        return int(text)
    except ValueError:
        return 0
