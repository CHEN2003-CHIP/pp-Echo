from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from pp_agent.attachments.retrieval import load_chunks
from pp_agent.attachments.schema import AttachmentChunk, AttachmentRecord
from pp_agent.attachments.service import AttachmentService


class AttachmentMemoryIngestor:
    """
    将附件 chunk 转换为长期记忆条目的服务。

    附件默认只在当前 session 中可用。该服务负责在用户明确请求后，
    将解析后的 attachment chunks 写入 pp-Echo 的 Memory / Learning 系统。
    写入时必须保留 attachment_id、filename、chunk_id、source_ref、页码、
    行号或 heading_path，方便后续检索、引用和 TraceInspect 审计。
    """

    def __init__(self, workspace: Path, *, observability: Any | None = None) -> None:
        self.workspace = workspace.resolve()
        self.service = AttachmentService(self.workspace, observability=observability)
        self.observability = observability
        self.memory_path = self.workspace / ".pp-agent" / "learning" / "attachment-memory.jsonl"

    def preview(self, session_id: str, attachment_id: str, *, max_source_refs: int = 10) -> dict[str, Any]:
        """预览 ingest 规模和来源引用，不写 memory。"""

        started = time.time()
        record = self.service._require_active(session_id, attachment_id)
        chunks = self._chunks(record)
        source_refs = [chunk.source_ref or chunk.filename for chunk in chunks[:max_source_refs]]
        payload = {
            "attachment_id": record.attachment_id,
            "filename": record.stored_filename,
            "chunk_count": len(chunks),
            "estimated_memory_items": len(chunks),
            "source_refs": source_refs,
            "requires_confirmation": True,
        }
        self._record_span("attachment.memory_ingest_preview", started, record, {"chunk_count": len(chunks), "source_refs": source_refs})
        return payload

    def ingest(self, session_id: str, attachment_id: str, *, mode: str = "selected_chunks", chunk_ids: list[str] | None = None, max_chunks: int = 100, tags: list[str] | None = None, scope: str = "workspace") -> dict[str, Any]:
        """显式写入附件 chunks 到长期记忆 JSONL，并强制 max_chunks 上限。"""

        started = time.time()
        record = self.service._require_active(session_id, attachment_id)
        selected = self._select_chunks(record, mode=mode, chunk_ids=chunk_ids or [], max_chunks=max_chunks)
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        created = []
        with self.memory_path.open("a", encoding="utf-8") as handle:
            for chunk in selected:
                item = self._memory_item(record, chunk, tags=tags or ["attachment"], scope=scope)
                handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
                created.append(item)
        source_refs = [str(item["metadata"].get("source_ref") or "") for item in created[:10]]
        self._record_span(
            "attachment.memory_ingest",
            started,
            record,
            {"chunk_count": len(selected), "memory_items_created": len(created), "tags": tags or ["attachment"], "scope": scope, "source_refs": source_refs},
        )
        return {
            "attachment_id": record.attachment_id,
            "filename": record.stored_filename,
            "memory_items_created": len(created),
            "memory_path": str(self.memory_path),
            "source_refs": source_refs,
        }

    def _select_chunks(self, record: AttachmentRecord, *, mode: str, chunk_ids: list[str], max_chunks: int) -> list[AttachmentChunk]:
        """根据 selected_chunks/all_chunks 模式选择有限数量的 chunks。"""

        chunks = self._chunks(record)
        capped = max(1, min(500, int(max_chunks or 100)))
        if mode == "all_chunks":
            return chunks[:capped]
        wanted = set(chunk_ids)
        if not wanted:
            raise ValueError("selected_chunks mode requires chunk_ids")
        return [chunk for chunk in chunks if chunk.chunk_id in wanted][:capped]

    def _chunks(self, record: AttachmentRecord) -> list[AttachmentChunk]:
        if not record.chunks_path:
            return []
        return load_chunks(self.workspace / record.chunks_path)

    def _memory_item(self, record: AttachmentRecord, chunk: AttachmentChunk, *, tags: list[str], scope: str) -> dict[str, Any]:
        metadata = {
            "source_type": "attachment",
            "attachment_id": record.attachment_id,
            "filename": record.stored_filename,
            "chunk_id": chunk.chunk_id,
            "source_ref": chunk.source_ref,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
            "heading_path": chunk.heading_path,
            "sha256": record.sha256,
            "created_at": time.time(),
            "session_id": record.session_id,
            "tags": tags,
            "scope": scope,
        }
        return {"memory_id": f"mem_att_{uuid.uuid4().hex[:12]}", "text": chunk.text, "metadata": metadata}

    def _record_span(self, name: str, started: float, record: AttachmentRecord, output: dict[str, Any]) -> None:
        record_completed_span = getattr(self.observability, "record_completed_span", None)
        if not callable(record_completed_span):
            return
        record_completed_span(
            name,
            "tool",
            status="ok",
            started_at=started,
            ended_at=time.time(),
            attributes={"attachment_id": record.attachment_id, "filename": record.stored_filename, "chunk_count": output.get("chunk_count")},
            output=output,
        )
