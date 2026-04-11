from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from pp_agent.memory.store import HistoryStore
from pp_agent.memory.types import HistoryChunkInput, HistoryChunkRecord, HistoryMessageRecord


class SQLiteHistoryStore(HistoryStore):
    def __init__(self, path: Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.busy_timeout_ms = busy_timeout_ms
        self._initialize()

    def append_message(
        self,
        *,
        session_id: str,
        turn_id: str,
        message_index: int,
        role: str,
        text: str,
        metadata: dict | None = None,
    ) -> str:
        message_id = self._message_id(session_id=session_id, turn_id=turn_id, message_index=message_index)
        payload = json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO history_messages (
                    id, session_id, turn_id, message_index, role, text, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_id, turn_id, message_index, role, text, time.time(), payload),
            )
        return message_id

    def append_chunks(
        self,
        *,
        session_id: str,
        turn_id: str,
        message_id: str,
        chunks: list[HistoryChunkInput],
    ) -> list[str]:
        chunk_ids: list[str] = []
        rows = []
        now = time.time()
        for chunk in chunks:
            chunk_id = self._chunk_id(message_id=message_id, chunk_index=chunk.chunk_index)
            chunk_ids.append(chunk_id)
            rows.append(
                (
                    chunk_id,
                    message_id,
                    session_id,
                    turn_id,
                    chunk.chunk_index,
                    chunk.source_kind,
                    chunk.text,
                    chunk.token_estimate,
                    now,
                    chunk.embedding_model,
                    chunk.embedding_status,
                    chunk.embedding_dim,
                    chunk.vector_ref,
                    json.dumps(chunk.metadata, ensure_ascii=False) if chunk.metadata else None,
                    None,
                    None,
                    now,
                )
            )
        if not rows:
            return chunk_ids
        with closing(self._connect()) as connection, connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO history_chunks (
                    id, message_id, session_id, turn_id, chunk_index, source_kind, text, token_estimate,
                    created_at, embedding_model, embedding_status, embedding_dim, vector_ref, metadata_json,
                    embedding_error, indexed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return chunk_ids

    def list_messages_by_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
    ) -> list[HistoryMessageRecord]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT id, session_id, turn_id, message_index, role, text, created_at, metadata_json
                FROM history_messages
                WHERE session_id = ? AND turn_id = ?
                ORDER BY message_index ASC
                """,
                (session_id, turn_id),
            ).fetchall()
        return [
            HistoryMessageRecord(
                id=row["id"],
                session_id=row["session_id"],
                turn_id=row["turn_id"],
                message_index=row["message_index"],
                role=row["role"],
                text=row["text"],
                created_at=row["created_at"],
                metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else None,
            )
            for row in rows
        ]

    def list_pending_chunks(self, *, limit: int) -> list[HistoryChunkRecord]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT *
                FROM history_chunks
                WHERE embedding_status = 'pending'
                ORDER BY created_at ASC, chunk_index ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._chunk_record_from_row(row) for row in rows]

    def list_chunks_for_session(
        self,
        *,
        session_id: str,
        limit: int | None = None,
        statuses: list[str] | None = None,
    ) -> list[HistoryChunkRecord]:
        clauses = ["session_id = ?"]
        parameters: list[object] = [session_id]
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            clauses.append(f"embedding_status IN ({placeholders})")
            parameters.extend(statuses)
        sql = f"""
            SELECT *
            FROM history_chunks
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at ASC, chunk_index ASC
        """
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(limit)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(sql, tuple(parameters)).fetchall()
        return [self._chunk_record_from_row(row) for row in rows]

    def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[HistoryChunkRecord]:
        if not chunk_ids:
            return []
        placeholders = ", ".join("?" for _ in chunk_ids)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM history_chunks
                WHERE id IN ({placeholders})
                """,
                tuple(chunk_ids),
            ).fetchall()
        order = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
        records = [self._chunk_record_from_row(row) for row in rows]
        return sorted(records, key=lambda item: order.get(item.id, len(order)))

    def get_messages_by_ids(self, message_ids: list[str]) -> list[HistoryMessageRecord]:
        if not message_ids:
            return []
        placeholders = ", ".join("?" for _ in message_ids)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""
                SELECT id, session_id, turn_id, message_index, role, text, created_at, metadata_json
                FROM history_messages
                WHERE id IN ({placeholders})
                """,
                tuple(message_ids),
            ).fetchall()
        order = {message_id: index for index, message_id in enumerate(message_ids)}
        records = [
            HistoryMessageRecord(
                id=row["id"],
                session_id=row["session_id"],
                turn_id=row["turn_id"],
                message_index=row["message_index"],
                role=row["role"],
                text=row["text"],
                created_at=row["created_at"],
                metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else None,
            )
            for row in rows
        ]
        return sorted(records, key=lambda item: order.get(item.id, len(order)))

    def search_chunks_by_text(
        self,
        query_text: str,
        *,
        limit: int,
        session_id: str | None = None,
    ) -> list[HistoryChunkRecord]:
        terms = self._search_terms(query_text)
        if not terms or limit <= 0:
            return []
        clauses: list[str] = []
        parameters: list[object] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            parameters.append(session_id)
        for term in terms:
            clauses.append("LOWER(text) LIKE ?")
            parameters.append(f"%{term}%")
        sql = f"""
            SELECT *
            FROM history_chunks
            WHERE {' AND '.join(clauses) if clauses else '1=1'}
            ORDER BY created_at DESC, chunk_index ASC
            LIMIT ?
        """
        parameters.append(limit)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(sql, tuple(parameters)).fetchall()
        return [self._chunk_record_from_row(row) for row in rows]

    def mark_chunk_embedded(
        self,
        *,
        chunk_id: str,
        embedding_model: str,
        embedding_dim: int,
    ) -> None:
        now = time.time()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE history_chunks
                SET embedding_model = ?,
                    embedding_dim = ?,
                    embedding_status = 'embedded',
                    embedding_error = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (embedding_model, embedding_dim, now, chunk_id),
            )

    def mark_chunk_indexed(
        self,
        *,
        chunk_id: str,
        vector_ref: str | None = None,
    ) -> None:
        now = time.time()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE history_chunks
                SET embedding_status = 'indexed',
                    indexed_at = COALESCE(indexed_at, ?),
                    vector_ref = COALESCE(?, vector_ref),
                    embedding_error = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, vector_ref, now, chunk_id),
            )

    def mark_chunk_failed(
        self,
        *,
        chunk_id: str,
        error: str,
    ) -> None:
        now = time.time()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE history_chunks
                SET embedding_status = 'failed',
                    embedding_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (error, now, chunk_id),
            )

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS history_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    message_index INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    metadata_json TEXT NULL,
                    UNIQUE(session_id, turn_id, message_index)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS history_chunks (
                    id TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    source_kind TEXT NOT NULL,
                    text TEXT NOT NULL,
                    token_estimate INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    embedding_model TEXT NULL,
                    embedding_status TEXT NOT NULL DEFAULT 'pending',
                    embedding_dim INTEGER NULL,
                    vector_ref TEXT NULL,
                    metadata_json TEXT NULL,
                    embedding_error TEXT NULL,
                    indexed_at REAL NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(message_id, chunk_index)
                )
                """
            )
            self._ensure_column(connection, "history_chunks", "embedding_error", "TEXT NULL")
            self._ensure_column(connection, "history_chunks", "indexed_at", "REAL NULL")
            self._ensure_column(connection, "history_chunks", "updated_at", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(connection, "history_chunks", "source_kind", "TEXT NOT NULL DEFAULT 'assistant'")
            self._backfill_updated_at(connection)
            connection.execute("CREATE INDEX IF NOT EXISTS idx_history_messages_session_turn ON history_messages(session_id, turn_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_history_chunks_session_turn ON history_chunks(session_id, turn_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_history_chunks_message_id ON history_chunks(message_id)")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(f"PRAGMA busy_timeout={int(self.busy_timeout_ms)}")
        return connection

    def _backfill_updated_at(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            UPDATE history_chunks
            SET updated_at = COALESCE(NULLIF(updated_at, 0), created_at)
            WHERE updated_at IS NULL OR updated_at = 0
            """
        )

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    @staticmethod
    def _chunk_record_from_row(row: sqlite3.Row) -> HistoryChunkRecord:
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else None
        return HistoryChunkRecord(
            id=row["id"],
            message_id=row["message_id"],
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            chunk_index=row["chunk_index"],
            source_kind=row["source_kind"],
            text=row["text"],
            token_estimate=row["token_estimate"],
            created_at=row["created_at"],
            embedding_model=row["embedding_model"],
            embedding_status=row["embedding_status"],
            embedding_dim=row["embedding_dim"],
            vector_ref=row["vector_ref"],
            embedding_error=row["embedding_error"],
            indexed_at=row["indexed_at"],
            updated_at=row["updated_at"],
            metadata=metadata,
        )

    @staticmethod
    def _message_id(*, session_id: str, turn_id: str, message_index: int) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{session_id}:{turn_id}:{message_index}"))

    @staticmethod
    def _chunk_id(*, message_id: str, chunk_index: int) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{message_id}:{chunk_index}"))

    @staticmethod
    def _search_terms(query_text: str) -> list[str]:
        unique_terms: list[str] = []
        seen: set[str] = set()
        for term in re.findall(r"[A-Za-z0-9_./:-]+", query_text.lower()):
            if len(term) < 2 or term in seen:
                continue
            seen.add(term)
            unique_terms.append(term)
        return unique_terms[:6]
