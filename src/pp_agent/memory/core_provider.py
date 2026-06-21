from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Protocol

from pp_agent.memory.core_types import CoreMemory, CoreMemorySnapshotResult


class MemoryProviderPlugin(Protocol):
    """Additive extension point for future external memory providers.

    Built-in Core Memory stays authoritative for prompt snapshots. Providers can
    prefetch context, mirror writes, or extract candidates later, but they must
    not replace curated Core Memory.
    """

    def prefetch_context(self, *, workspace_id: str, session_id: str | None = None) -> CoreMemorySnapshotResult:
        ...

    def sync_turn(self, *, session_id: str, turn_id: str, messages: list[object]) -> None:
        ...

    def extract_on_session_end(self, *, session_id: str) -> list[object]:
        ...

    def mirror_core_write(self, *, memory: CoreMemory, action: str) -> None:
        ...

    def status(self) -> dict[str, object]:
        ...


class NoopMemoryProviderPlugin:
    def prefetch_context(self, *, workspace_id: str, session_id: str | None = None) -> CoreMemorySnapshotResult:
        return CoreMemorySnapshotResult(workspace_id=workspace_id, session_id=session_id)

    def sync_turn(self, *, session_id: str, turn_id: str, messages: list[object]) -> None:
        return None

    def extract_on_session_end(self, *, session_id: str) -> list[object]:
        return []

    def mirror_core_write(self, *, memory: CoreMemory, action: str) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {"enabled": False, "provider": "noop", "additive": True}


class LocalMemoryProviderPlugin:
    """Small local additive provider used until external providers are wired.

    It mirrors core writes and turn sync metadata into its own SQLite database.
    The provider never replaces Core Memory or changes prompt injection rules.
    """

    def __init__(self, path: Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.busy_timeout_ms = busy_timeout_ms
        self._initialize()

    def prefetch_context(self, *, workspace_id: str, session_id: str | None = None) -> CoreMemorySnapshotResult:
        return CoreMemorySnapshotResult(
            workspace_id=workspace_id,
            session_id=session_id,
            budget={"budget_status": "provider_additive"},
        )

    def sync_turn(self, *, session_id: str, turn_id: str, messages: list[object]) -> None:
        preview = self._messages_preview(messages)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO core_memory_provider_turns (
                    session_id, turn_id, message_count, preview, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, turn_id, len(messages), preview, time.time()),
            )

    def extract_on_session_end(self, *, session_id: str) -> list[object]:
        return []

    def mirror_core_write(self, *, memory: CoreMemory, action: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO core_memory_provider_writes (
                    memory_id, action, status, scope, workspace_id, section, type,
                    content, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.id,
                    action,
                    memory.status,
                    memory.scope,
                    memory.workspace_id,
                    memory.section,
                    memory.type,
                    memory.content,
                    json.dumps(memory.model_dump(mode="python"), ensure_ascii=False),
                    time.time(),
                ),
            )

    def status(self) -> dict[str, object]:
        with closing(self._connect()) as connection, connection:
            write_count = int(connection.execute("SELECT COUNT(*) FROM core_memory_provider_writes").fetchone()[0])
            turn_count = int(connection.execute("SELECT COUNT(*) FROM core_memory_provider_turns").fetchone()[0])
        return {
            "enabled": True,
            "provider": "local",
            "additive": True,
            "path": str(self.path),
            "mirrored_write_count": write_count,
            "synced_turn_count": turn_count,
        }

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS core_memory_provider_writes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    workspace_id TEXT NULL,
                    section TEXT NOT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS core_memory_provider_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    message_count INTEGER NOT NULL,
                    preview TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(f"PRAGMA busy_timeout={int(self.busy_timeout_ms)}")
        return connection

    @staticmethod
    def _messages_preview(messages: list[object]) -> str:
        parts: list[str] = []
        for message in messages[:8]:
            role = getattr(message, "role", "")
            content = getattr(message, "content", "")
            parts.append(f"{role}: {str(content)[:160]}")
        return "\n".join(parts)[:1200]
