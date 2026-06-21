from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from pp_agent.memory.core_governance import detect_conflicts, find_duplicate, normalize_memory_content, scan_memory_candidate
from pp_agent.memory.core_types import CoreMemory, CoreMemoryAuditRecord, CoreMemoryCandidate, CoreMemoryWriteResult


class CoreMemoryStore:
    """SQLite store for curated long-term core memory.

    The store keeps structured fields instead of rendered prompt text so status,
    provenance, workspace isolation, and audit metadata remain queryable.
    """

    def __init__(self, path: Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.busy_timeout_ms = busy_timeout_ms
        self._initialize()

    def add_candidate(self, candidate: CoreMemoryCandidate, *, require_approval: bool = True) -> CoreMemoryWriteResult:
        existing = self._list_for_governance(candidate.scope, candidate.workspace_id, candidate.section, candidate.type)
        duplicate = find_duplicate(candidate, existing)
        if duplicate is not None:
            return CoreMemoryWriteResult(memory=duplicate, duplicate_of=duplicate.id, warnings=["duplicate_core_memory"])
        safety = scan_memory_candidate(candidate)
        status = "pending" if require_approval and safety.allowed else "active"
        if not safety.allowed:
            status = "rejected"
        memory = candidate.to_memory(status=status)
        metadata = dict(memory.metadata)
        if not safety.allowed:
            metadata["rejected_reason"] = list(safety.reasons)
        conflicts = detect_conflicts(memory, existing)
        if conflicts:
            metadata["conflicts_with"] = conflicts
        memory.metadata = metadata
        self._insert(memory)
        warnings = ["rejected_by_safety_scan"] if not safety.allowed else []
        return CoreMemoryWriteResult(memory=memory, warnings=warnings, safety=safety.to_dict(), conflicts_with=conflicts)

    def add_memory(self, memory: CoreMemory) -> CoreMemory:
        self._insert(memory)
        return memory

    def approve(self, memory_id: str) -> CoreMemory:
        memory = self._require(memory_id)
        if memory.status != "pending":
            raise ValueError(f"Only pending memory can be approved: {memory_id}")
        return self.update(memory_id, {"status": "active"})

    def reject(self, memory_id: str) -> CoreMemory:
        memory = self._require(memory_id)
        if memory.status not in {"pending", "active"}:
            raise ValueError(f"Only pending or active memory can be rejected: {memory_id}")
        return self.update(memory_id, {"status": "rejected"})

    def archive(self, memory_id: str) -> CoreMemory:
        memory = self._require(memory_id)
        if memory.status == "archived":
            return memory
        return self.update(memory_id, {"status": "archived"})

    def replace(self, old_memory_id: str, new_memory: CoreMemoryCandidate | CoreMemory) -> CoreMemory:
        old = self._require(old_memory_id)
        if isinstance(new_memory, CoreMemoryCandidate):
            replacement = new_memory.to_memory(status="active")
        else:
            replacement = new_memory.model_copy(deep=True, update={"status": "active"})
        supersedes = list(dict.fromkeys([*replacement.supersedes, old.id]))
        replacement.supersedes = supersedes
        with closing(self._connect()) as connection, connection:
            self._insert_row(connection, replacement)
            connection.execute(
                "UPDATE core_memories SET status = ?, updated_at = ? WHERE id = ?",
                ("archived", time.time(), old.id),
            )
        return replacement

    def record_audit(self, record: CoreMemoryAuditRecord) -> CoreMemoryAuditRecord:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO core_memory_audit (
                    audit_id, memory_id, action, actor, source_json, before_status,
                    after_status, reason, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.audit_id,
                    record.memory_id,
                    record.action,
                    record.actor,
                    json.dumps(record.source.model_dump(mode="python"), ensure_ascii=False),
                    record.before_status,
                    record.after_status,
                    record.reason,
                    record.created_at,
                    json.dumps(record.metadata, ensure_ascii=False),
                ),
            )
        return record

    def list_audit(self, *, memory_id: str | None = None, limit: int = 100) -> list[CoreMemoryAuditRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if memory_id:
            clauses.append("memory_id = ?")
            params.append(memory_id)
        sql = "SELECT * FROM core_memory_audit"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        return [self._audit_from_row(row) for row in rows]

    def list_active(self, *, scope: str | None = None, section: str | None = None, workspace_id: str | None = None) -> list[CoreMemory]:
        return self._list(statuses=["active"], scope=scope, section=section, workspace_id=workspace_id)

    def list_pending(self, *, scope: str | None = None, workspace_id: str | None = None) -> list[CoreMemory]:
        return self._list(statuses=["pending"], scope=scope, workspace_id=workspace_id)

    def list_all(self, *, scope: str | None = None, workspace_id: str | None = None) -> list[CoreMemory]:
        return self._list(statuses=["pending", "active", "rejected", "archived"], scope=scope, workspace_id=workspace_id)

    def get(self, memory_id: str) -> CoreMemory | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT * FROM core_memories WHERE id = ?", (memory_id,)).fetchone()
        return self._from_row(row) if row is not None else None

    def update(self, memory_id: str, patch: dict[str, Any]) -> CoreMemory:
        memory = self._require(memory_id)
        allowed = {"scope", "workspace_id", "section", "type", "content", "source", "confidence", "status", "supersedes", "expires_at", "metadata"}
        unknown = sorted(set(patch) - allowed)
        if unknown:
            raise ValueError(f"Unknown core memory patch field: {unknown[0]}")
        updated = memory.model_copy(update={**patch, "updated_at": time.time()}, deep=True)
        CoreMemory.model_validate(updated.model_dump(mode="python"))
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE core_memories
                SET scope = ?, workspace_id = ?, section = ?, type = ?, content = ?, content_norm = ?,
                    source_json = ?, confidence = ?, status = ?, updated_at = ?, supersedes_json = ?,
                    expires_at = ?, metadata_json = ?
                WHERE id = ?
                """,
                self._row_values(updated) + (memory_id,),
            )
        return updated

    def search_core_memory(self, query: str, *, scope: str | None = None, workspace_id: str | None = None) -> list[CoreMemory]:
        terms = [term for term in normalize_memory_content(query).split() if len(term) >= 2][:6]
        if not terms:
            return []
        clauses = ["status = 'active'"]
        params: list[object] = []
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if workspace_id is not None:
            clauses.append("(workspace_id = ? OR scope = 'global')")
            params.append(workspace_id)
        for term in terms:
            clauses.append("content_norm LIKE ?")
            params.append(f"%{term}%")
        sql = f"SELECT * FROM core_memories WHERE {' AND '.join(clauses)} ORDER BY confidence DESC, updated_at DESC"
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        return [self._from_row(row) for row in rows]

    def _list_for_governance(self, scope: str, workspace_id: str | None, section: str, memory_type: str) -> list[CoreMemory]:
        return self._list(statuses=["active", "pending"], scope=scope, workspace_id=workspace_id, section=section, memory_type=memory_type)

    def list_for_governance(self, scope: str, workspace_id: str | None, section: str, memory_type: str) -> list[CoreMemory]:
        return self._list_for_governance(scope, workspace_id, section, memory_type)

    def _list(
        self,
        *,
        statuses: list[str],
        scope: str | None = None,
        section: str | None = None,
        workspace_id: str | None = None,
        memory_type: str | None = None,
    ) -> list[CoreMemory]:
        clauses = [f"status IN ({', '.join('?' for _ in statuses)})"]
        params: list[object] = list(statuses)
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if section:
            clauses.append("section = ?")
            params.append(section)
        if memory_type:
            clauses.append("type = ?")
            params.append(memory_type)
        if workspace_id is not None:
            clauses.append("(workspace_id = ? OR scope = 'global')")
            params.append(workspace_id)
        sql = f"SELECT * FROM core_memories WHERE {' AND '.join(clauses)} ORDER BY section ASC, confidence DESC, updated_at DESC"
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        return [self._from_row(row) for row in rows]

    def _insert(self, memory: CoreMemory) -> None:
        with closing(self._connect()) as connection, connection:
            self._insert_row(connection, memory)

    def _insert_row(self, connection: sqlite3.Connection, memory: CoreMemory) -> None:
        try:
            connection.execute(
                """
                INSERT INTO core_memories (
                    id, scope, workspace_id, section, type, content, content_norm, source_json,
                    confidence, status, created_at, updated_at, supersedes_json, expires_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (memory.id, *self._row_values(memory, include_created=True)),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Core memory already exists: {memory.id}") from exc

    def _require(self, memory_id: str) -> CoreMemory:
        memory = self.get(memory_id)
        if memory is None:
            raise KeyError(memory_id)
        return memory

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS core_memories (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    workspace_id TEXT NULL,
                    section TEXT NOT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_norm TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    supersedes_json TEXT NOT NULL,
                    expires_at REAL NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_core_memories_status_scope ON core_memories(status, scope, workspace_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_core_memories_section_type ON core_memories(section, type)")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS core_memory_audit (
                    audit_id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    before_status TEXT NULL,
                    after_status TEXT NULL,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_core_memory_audit_memory ON core_memory_audit(memory_id, created_at)")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(f"PRAGMA busy_timeout={int(self.busy_timeout_ms)}")
        return connection

    @staticmethod
    def _row_values(memory: CoreMemory, *, include_created: bool = False) -> tuple[object, ...]:
        values: tuple[object, ...] = (
            memory.scope,
            memory.workspace_id,
            memory.section,
            memory.type,
            memory.content,
            normalize_memory_content(memory.content),
            json.dumps(memory.source.model_dump(mode="python"), ensure_ascii=False),
            memory.confidence,
            memory.status,
            memory.created_at,
            memory.updated_at,
            json.dumps(memory.supersedes, ensure_ascii=False),
            memory.expires_at,
            json.dumps(memory.metadata, ensure_ascii=False),
        )
        if include_created:
            return values
        return values[:9] + values[10:]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> CoreMemory:
        return CoreMemory(
            id=row["id"],
            scope=row["scope"],
            workspace_id=row["workspace_id"],
            section=row["section"],
            type=row["type"],
            content=row["content"],
            source=json.loads(row["source_json"]),
            confidence=row["confidence"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            supersedes=json.loads(row["supersedes_json"]),
            expires_at=row["expires_at"],
            metadata=json.loads(row["metadata_json"]),
        )

    @staticmethod
    def _audit_from_row(row: sqlite3.Row) -> CoreMemoryAuditRecord:
        return CoreMemoryAuditRecord(
            audit_id=row["audit_id"],
            memory_id=row["memory_id"],
            action=row["action"],
            actor=row["actor"],
            source=json.loads(row["source_json"]),
            before_status=row["before_status"],
            after_status=row["after_status"],
            reason=row["reason"],
            created_at=row["created_at"],
            metadata=json.loads(row["metadata_json"]),
        )
