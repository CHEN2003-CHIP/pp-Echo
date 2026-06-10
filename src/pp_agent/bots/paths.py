from __future__ import annotations

from datetime import date
from pathlib import Path


def get_bots_root(workspace: Path) -> Path:
    return Path(workspace) / ".pp-agent" / "bots"


def get_bot_index_path(workspace: Path) -> Path:
    return get_bots_root(workspace) / "index.json"


def get_bot_root(workspace: Path, platform: str, bot_id: str) -> Path:
    return get_bots_root(workspace) / _safe_segment(platform) / _safe_segment(bot_id)


def get_bot_config_path(workspace: Path, platform: str, bot_id: str) -> Path:
    return get_bot_root(workspace, platform, bot_id) / "config.json"


def get_bot_status_path(workspace: Path, platform: str, bot_id: str) -> Path:
    return get_bot_root(workspace, platform, bot_id) / "status.json"


def get_bot_events_path(workspace: Path, platform: str, bot_id: str) -> Path:
    return get_bot_root(workspace, platform, bot_id) / "events.jsonl"


def get_bot_messages_path(workspace: Path, platform: str, bot_id: str) -> Path:
    return get_bot_root(workspace, platform, bot_id) / "messages.jsonl"


def get_bot_logs_dir(workspace: Path, platform: str, bot_id: str) -> Path:
    return get_bot_root(workspace, platform, bot_id) / "logs"


def get_bot_runs_dir(workspace: Path, platform: str, bot_id: str, date_value: date | str | None = None) -> Path:
    root = get_bot_root(workspace, platform, bot_id) / "runs"
    return root / _date_segment(date_value) if date_value is not None else root


def get_bot_traces_dir(workspace: Path, platform: str, bot_id: str, date_value: date | str | None = None) -> Path:
    root = get_bot_root(workspace, platform, bot_id) / "traces"
    return root / _date_segment(date_value) if date_value is not None else root


def get_bot_approvals_dir(workspace: Path, platform: str, bot_id: str) -> Path:
    return get_bot_root(workspace, platform, bot_id) / "approvals"


def ensure_bot_dirs(workspace: Path, platform: str, bot_id: str) -> Path:
    root = get_bot_root(workspace, platform, bot_id)
    for path in (
        root,
        get_bot_logs_dir(workspace, platform, bot_id),
        get_bot_runs_dir(workspace, platform, bot_id),
        get_bot_traces_dir(workspace, platform, bot_id),
        get_bot_approvals_dir(workspace, platform, bot_id),
    ):
        path.mkdir(parents=True, exist_ok=True)
    return root


def _date_segment(value: date | str) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def _safe_segment(value: str) -> str:
    text = str(value or "").strip()
    if not text or any(part in text for part in ("/", "\\", "..")):
        raise ValueError(f"Invalid bot path segment: {value!r}")
    return text
