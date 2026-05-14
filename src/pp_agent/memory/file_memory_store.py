from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from pp_agent.memory.file_memory_chunker import FileMemoryChunk


@dataclass(frozen=True)
class FileMemoryFile:
    path: str
    absolute_path: Path
    mtime: float
    size: int
    content_hash: str


@dataclass(frozen=True)
class FileMemoryReadResult:
    path: str
    line_start: int
    line_end: int
    content: str


class FileMemoryAccessError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class FileMemoryIndexStore:
    def __init__(
        self,
        *,
        workspace: Path,
        index_path: Path,
        memory_root: Path | None = None,
        extra_paths: list[str] | None = None,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.workspace = workspace.resolve()
        self.memory_root = (memory_root or workspace).resolve()
        self.index_path = Path(index_path).expanduser()
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.extra_paths = list(extra_paths or [])
        self.busy_timeout_ms = int(busy_timeout_ms)
        self._initialize()

    def scan_memory_files(self) -> list[FileMemoryFile]:
        candidates: list[Path] = []
        root_memory = self.memory_root / "MEMORY.md"
        if root_memory.exists():
            candidates.append(root_memory)
        memory_dir = self.memory_root / "memory"
        if memory_dir.exists():
            candidates.extend(path for path in memory_dir.rglob("*.md") if path.is_file())
        for raw_path in self.extra_paths:
            try:
                candidate = self.resolve_memory_path(raw_path)
            except FileMemoryAccessError:
                continue
            if candidate.exists() and candidate.is_file():
                candidates.append(candidate)
        files: list[FileMemoryFile] = []
        seen: set[str] = set()
        for candidate in sorted(candidates, key=lambda item: self.to_memory_path(item)):
            try:
                rel = self.to_memory_path(candidate)
                if rel in seen or not self.is_allowed_memory_label(rel):
                    continue
                resolved = candidate.resolve()
                if not self._is_under_workspace(resolved):
                    continue
                stat = resolved.stat()
                files.append(
                    FileMemoryFile(
                        path=rel,
                        absolute_path=resolved,
                        mtime=float(stat.st_mtime),
                        size=int(stat.st_size),
                        content_hash=self.file_hash(resolved),
                    )
                )
                seen.add(rel)
            except OSError:
                continue
        return files

    def sync_file(self, file: FileMemoryFile, chunks: list[FileMemoryChunk]) -> None:
        now = time.time()
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM chunks WHERE path = ?", (file.path,))
            connection.execute(
                """
                INSERT INTO indexed_files (path, mtime, size, content_hash, active, updated_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(path) DO UPDATE SET
                    mtime = excluded.mtime,
                    size = excluded.size,
                    content_hash = excluded.content_hash,
                    active = 1,
                    updated_at = excluded.updated_at
                """,
                (file.path, file.mtime, file.size, file.content_hash, now),
            )
            rows = [
                (
                    chunk.chunk_id,
                    chunk.path,
                    chunk.line_start,
                    chunk.line_end,
                    chunk.text,
                    json.dumps(chunk.heading_path, ensure_ascii=False),
                    chunk.content_hash,
                    chunk.file_mtime,
                    chunk.embedding_model,
                    chunk.created_at,
                    chunk.updated_at,
                    1,
                    None,
                )
                for chunk in chunks
            ]
            connection.executemany(
                """
                INSERT INTO chunks (
                    chunk_id, path, line_start, line_end, text, heading_path_json, content_hash,
                    file_mtime, embedding_model, created_at, updated_at, active, vector_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def mark_file_seen(self, file: FileMemoryFile) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO indexed_files (path, mtime, size, content_hash, active, updated_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(path) DO UPDATE SET
                    mtime = excluded.mtime,
                    size = excluded.size,
                    content_hash = excluded.content_hash,
                    active = 1,
                    updated_at = excluded.updated_at
                """,
                (file.path, file.mtime, file.size, file.content_hash, time.time()),
            )

    def deactivate_missing_files(self, active_paths: set[str]) -> list[str]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute("SELECT path FROM indexed_files WHERE active = 1").fetchall()
            missing = [row["path"] for row in rows if row["path"] not in active_paths]
            for path in missing:
                connection.execute("UPDATE indexed_files SET active = 0, updated_at = ? WHERE path = ?", (time.time(), path))
                connection.execute("UPDATE chunks SET active = 0, updated_at = ? WHERE path = ?", (time.time(), path))
        return missing

    def indexed_files(self) -> dict[str, FileMemoryFile]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute("SELECT path, mtime, size, content_hash FROM indexed_files WHERE active = 1").fetchall()
        return {
            row["path"]: FileMemoryFile(
                path=row["path"],
                absolute_path=self.memory_root / row["path"],
                mtime=float(row["mtime"]),
                size=int(row["size"]),
                content_hash=row["content_hash"],
            )
            for row in rows
        }

    def list_chunks(self, *, active_only: bool = True) -> list[FileMemoryChunk]:
        clause = "WHERE active = 1" if active_only else ""
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(f"SELECT * FROM chunks {clause} ORDER BY path, line_start").fetchall()
        return [self._chunk_from_row(row) for row in rows]

    def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[FileMemoryChunk]:
        if not chunk_ids:
            return []
        placeholders = ", ".join("?" for _ in chunk_ids)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"SELECT * FROM chunks WHERE active = 1 AND chunk_id IN ({placeholders})",
                tuple(chunk_ids),
            ).fetchall()
        order = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
        return sorted([self._chunk_from_row(row) for row in rows], key=lambda item: order.get(item.chunk_id, len(order)))

    def mark_chunks_vector_indexed(self, chunk_ids: list[str], *, embedding_model: str) -> None:
        if not chunk_ids:
            return
        now = time.time()
        with closing(self._connect()) as connection, connection:
            connection.executemany(
                """
                UPDATE chunks
                SET embedding_model = ?, vector_ref = chunk_id, updated_at = ?
                WHERE chunk_id = ?
                """,
                [(embedding_model, now, chunk_id) for chunk_id in chunk_ids],
            )

    def chunks_needing_embedding(self, *, embedding_model: str) -> list[FileMemoryChunk]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT * FROM chunks
                WHERE active = 1 AND (embedding_model IS NULL OR embedding_model != ? OR vector_ref IS NULL)
                ORDER BY path, line_start
                """,
                (embedding_model,),
            ).fetchall()
        return [self._chunk_from_row(row) for row in rows]

    def read_line_range(self, raw_path: str, *, start_line: int | None = None, line_count: int | None = None) -> FileMemoryReadResult:
        path = self.resolve_memory_path(raw_path)
        if not path.exists():
            raise FileMemoryAccessError("not_found", f"Memory file does not exist: {raw_path}")
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        if not lines:
            return FileMemoryReadResult(path=self.to_memory_path(path), line_start=1, line_end=0, content="")
        start = max(1, int(start_line or 1))
        count = 120 if line_count is None else int(line_count)
        if count <= 0:
            raise FileMemoryAccessError("invalid_range", "line_count must be positive")
        count = min(count, 300)
        if start > len(lines):
            return FileMemoryReadResult(path=self.to_memory_path(path), line_start=start, line_end=len(lines), content="")
        end = min(len(lines), start + count - 1)
        return FileMemoryReadResult(
            path=self.to_memory_path(path),
            line_start=start,
            line_end=end,
            content="\n".join(lines[start - 1 : end]),
        )

    def resolve_memory_path(self, raw_path: str) -> Path:
        label = self._normalize_label(raw_path)
        if not self.is_allowed_memory_label(label):
            raise FileMemoryAccessError("forbidden_path", f"Path is not an allowed memory Markdown file: {raw_path}")
        candidate = (self.memory_root / label).resolve(strict=False)
        if not self._is_under_workspace(candidate):
            raise FileMemoryAccessError("path_escape", "Memory path escapes the workspace")
        if candidate.exists():
            resolved = candidate.resolve()
            if not self._is_under_workspace(resolved):
                raise FileMemoryAccessError("path_escape", "Memory path resolves outside the workspace")
            return resolved
        return candidate

    def to_memory_path(self, path: Path) -> str:
        try:
            return path.resolve(strict=False).relative_to(self.memory_root).as_posix()
        except ValueError:
            return path.as_posix()

    @staticmethod
    def is_allowed_memory_label(label: str) -> bool:
        normalized = label.replace("\\", "/")
        if normalized == "MEMORY.md":
            return True
        return normalized.startswith("memory/") and normalized.endswith(".md") and "/../" not in f"/{normalized}/"

    @staticmethod
    def file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _normalize_label(self, raw_path: str) -> str:
        raw = str(raw_path or "").strip()
        if not raw:
            raise FileMemoryAccessError("invalid_path", "path is required")
        path = Path(raw)
        if path.is_absolute() or raw.startswith("/") or raw.startswith("\\"):
            raise FileMemoryAccessError("absolute_path", "Absolute paths are not allowed for memory_get")
        parts = [part for part in raw.replace("\\", "/").split("/") if part not in {"", "."}]
        if any(part == ".." for part in parts):
            raise FileMemoryAccessError("path_escape", "Parent directory segments are not allowed")
        label = "/".join(parts)
        lower_name = Path(label).name.lower()
        if lower_name == ".env" or lower_name.startswith(".env.") or lower_name.endswith((".key", ".pem")):
            raise FileMemoryAccessError("forbidden_path", "Secret-like paths are not allowed")
        if not label.endswith(".md"):
            raise FileMemoryAccessError("forbidden_path", "Only Markdown memory files are allowed")
        return label

    def _is_under_workspace(self, path: Path) -> bool:
        resolved = path.resolve(strict=False)
        return resolved == self.workspace or self.workspace in resolved.parents

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS indexed_files (
                    path TEXT PRIMARY KEY,
                    mtime REAL NOT NULL,
                    size INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    line_start INTEGER NOT NULL,
                    line_end INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    heading_path_json TEXT NULL,
                    content_hash TEXT NOT NULL,
                    file_mtime REAL NOT NULL,
                    embedding_model TEXT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    vector_ref TEXT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_file_memory_chunks_path ON chunks(path)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_file_memory_chunks_active ON chunks(active)")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.index_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        return connection

    @staticmethod
    def _chunk_from_row(row: sqlite3.Row) -> FileMemoryChunk:
        return FileMemoryChunk(
            chunk_id=row["chunk_id"],
            path=row["path"],
            line_start=int(row["line_start"]),
            line_end=int(row["line_end"]),
            text=row["text"],
            heading_path=json.loads(row["heading_path_json"]) if row["heading_path_json"] else [],
            content_hash=row["content_hash"],
            file_mtime=float(row["file_mtime"]),
            embedding_model=row["embedding_model"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )
