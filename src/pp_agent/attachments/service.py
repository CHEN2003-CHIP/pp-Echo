from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pp_agent.attachments.extractors import extract_attachment
from pp_agent.attachments.code_index import CodeSymbol, build_symbol_index, read_symbol_text, search_symbols
from pp_agent.attachments.index import build_keyword_index
from pp_agent.attachments.embeddings import AttachmentEmbeddingProvider, UnavailableEmbeddingProvider
from pp_agent.attachments.hybrid_retrieval import hybrid_search_chunks
from pp_agent.attachments.rerank import rerank_attachment_results
from pp_agent.attachments.retrieval import dump_index, load_chunks, search_chunks, write_chunks
from pp_agent.attachments.schema import AttachmentChunk, AttachmentKind, AttachmentRecord, AttachmentStatus
from pp_agent.attachments.security import detect_attachment_kind, validate_upload_extension, validate_upload_size
from pp_agent.attachments.store import AttachmentStore
from pp_agent.attachments.text_utils import preview_text, read_text_lossy
from pp_agent.observability.noop import NoopObservabilityHooks

DEFAULT_TEXT_READ_CHARS = 30000
MAX_TEXT_READ_CHARS = 60000


class AttachmentService:
    """
    负责管理 pp-Echo 会话附件的核心服务。

    它不把上传文件直接写入 workspace，而是保存到
    .pp-agent/sessions/<session_id>/attachments/ 这样的受控目录中。
    后续解析、切块、索引、检索和工具读取都通过该服务完成，避免大文件污染项目
    或被一次性塞入模型上下文。
    """

    def __init__(self, workspace: Path, *, observability: Any | None = None, embedding_provider: AttachmentEmbeddingProvider | None = None) -> None:
        self.workspace = workspace.resolve()
        self.store = AttachmentStore(self.workspace)
        self.observability = observability or NoopObservabilityHooks()
        self.embedding_provider = embedding_provider or UnavailableEmbeddingProvider()

    def upload_bytes(self, session_id: str, filename: str, data: bytes, *, content_type: str | None = None) -> AttachmentRecord:
        """保存上传字节流并同步执行解析、切块和关键词索引。"""

        started = time.time()
        safe_kind = detect_attachment_kind(filename, content_type)
        validate_upload_extension(filename)
        validate_upload_size(len(data))
        record = self.store.save_original(session_id, filename, data, content_type=content_type, kind=safe_kind)
        self._record_span(
            "attachment.upload",
            started,
            record,
            {"status": record.status.value, "size_bytes": record.size_bytes, "sha256": record.sha256},
        )
        return self.process(record)

    def process(self, record: AttachmentRecord) -> AttachmentRecord:
        """对已保存附件进行抽取、切块和索引，失败时保留 manifest 并标记 failed。"""

        started = time.time()
        directory = self.store.attachment_dir(record)
        original_path = directory / "original" / record.stored_filename
        try:
            extracted_text, chunks, metadata = extract_attachment(
                original_path,
                kind=record.kind,
                attachment_id=record.attachment_id,
                session_id=record.session_id,
                filename=record.stored_filename,
            )
            record.status = AttachmentStatus.EXTRACTED
            record.text_preview = preview_text(extracted_text or metadata.get("preview", ""))
            record.metadata.update(metadata)
            record.metadata["text_length"] = len(extracted_text)
            if record.kind == AttachmentKind.CODE:
                symbols = build_symbol_index(extracted_text, attachment_id=record.attachment_id, filename=record.stored_filename)
                record.metadata["symbols"] = [symbol.model_dump(mode="json") for symbol in symbols]
                record.metadata["outline"] = record.metadata.get("outline") or record.metadata["symbols"]
                self._record_span("attachment.symbol_index", started, record, {"status": "ok", "symbol_count": len(symbols)})
            text_path = directory / "extracted_text.md"
            text_path.write_text(extracted_text, encoding="utf-8")

            record.extracted_text_path = f"{record.relative_dir}/extracted_text.md"
            self._record_span("attachment.extract", started, record, {"status": record.status.value, "preview": record.text_preview})
            chunk_started = time.time()
            chunks_path = directory / "chunks.jsonl"
            write_chunks(chunks_path, chunks)
            record.status = AttachmentStatus.CHUNKED
            record.chunks_path = f"{record.relative_dir}/chunks.jsonl"
            self._record_span("attachment.chunk", chunk_started, record, {"status": record.status.value, "chunk_count": len(chunks)})
            index_started = time.time()
            index = build_keyword_index(chunks)
            index_path = directory / "index.json"
            dump_index(index_path, index)
            record.status = AttachmentStatus.INDEXED
            record.index_path = f"{record.relative_dir}/index.json"
            record.metadata["chunk_count"] = len(chunks)
            record.metadata["index_type"] = "keyword"
            self._record_span("attachment.index", index_started, record, {"status": record.status.value, "chunk_count": len(chunks), "index_type": "keyword"})
        except Exception as exc:  # noqa: BLE001
            record.status = AttachmentStatus.FAILED
            record.error = str(exc)
            record.text_preview = record.text_preview or str(exc)
            self._record_span("attachment.extract", started, record, {"status": "failed", "error": str(exc)}, error=exc)
        self.store.write_manifest(record)
        return record

    def list(self, session_id: str) -> list[AttachmentRecord]:
        """列出当前 session 可见附件。"""

        return self.store.list(session_id)

    def inspect(self, session_id: str, attachment_id: str) -> dict[str, Any]:
        """返回附件摘要、状态、类型、chunk 数、outline 或表格结构等 inspect 信息。"""

        started = time.time()
        record = self._require_active(session_id, attachment_id)
        metadata_keys = sorted(str(key) for key in record.metadata.keys())
        text_length = self._extracted_text_length(record)
        can_read_full_text = text_length <= DEFAULT_TEXT_READ_CHARS if text_length is not None else False
        self._record_span(
            "attachment.inspect",
            started,
            record,
            {
                "metadata_keys": metadata_keys,
                "preview": record.text_preview[:500],
                "chunk_count": record.metadata.get("chunk_count"),
                "text_length": text_length,
                "can_read_full_text": can_read_full_text,
            },
        )
        metadata = dict(record.metadata)
        metadata["text_length"] = text_length
        metadata["can_read_full_text"] = can_read_full_text
        metadata["recommended_read_tool"] = "read_attachment_text"
        return {"attachment": self._public_record(record), "metadata": metadata}

    def search(self, session_id: str, query: str, *, attachment_id: str | None = None, top_k: int = 5, mode: str = "auto") -> list[dict[str, Any]]:
        """在一个或多个 session 附件中搜索相关 chunk。"""

        started = time.time()
        records = [self._require_active(session_id, attachment_id)] if attachment_id else self.list(session_id)
        chunks: list[AttachmentChunk] = []
        for record in records:
            if record.chunks_path:
                chunks.extend(load_chunks(self.workspace / record.chunks_path))
        requested_mode = str(mode or "auto").lower()
        if requested_mode == "keyword":
            raw_results = search_chunks(chunks, query, top_k=top_k)
            chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
            results = rerank_attachment_results(raw_results, chunks_by_id, query)[:top_k]
            trace_meta = {
                "search_mode": "keyword",
                "index_type": "keyword",
                "embedding_available": self.embedding_provider.is_available(),
                "fallback_reason": None,
                "keyword_result_count": len(raw_results),
                "vector_result_count": 0,
                "rerank_applied": True,
            }
        else:
            results, trace_meta = hybrid_search_chunks(chunks, query, top_k=top_k, embedding_provider=self.embedding_provider)
            if requested_mode == "hybrid" and not self.embedding_provider.is_available():
                trace_meta["search_mode"] = "keyword"
                trace_meta["fallback_reason"] = "embedding_provider_unavailable"
        if records:
            self._record_span(
                "attachment.search",
                started,
                records[0],
                {"query": query[:200], "top_k": top_k, "result_count": len(results), "chunk_ids": [item.chunk_id for item in results], **trace_meta},
            )
        return [item.model_dump(mode="json") for item in results]

    def read_chunk(self, session_id: str, chunk_id: str, *, max_chars: int = 12000) -> dict[str, Any]:
        """读取指定 chunk 的文本，并对超长内容截断，提示可继续按范围读取。"""

        started = time.time()
        for record in self.list(session_id):
            chunks = load_chunks(self.workspace / record.chunks_path) if record.chunks_path else []
            for chunk in chunks:
                if chunk.chunk_id == chunk_id:
                    text = chunk.text[:max_chars]
                    truncated = len(chunk.text) > max_chars
                    self._record_span("attachment.read_chunk", started, record, {"chunk_ids": [chunk_id], "truncated": truncated})
                    return {"chunk": chunk.model_dump(mode="json"), "text": text, "truncated": truncated}
        raise FileNotFoundError(f"Attachment chunk not found: {chunk_id}")

    def read_text(self, session_id: str, attachment_id: str, *, offset: int = 0, max_chars: int = DEFAULT_TEXT_READ_CHARS) -> dict[str, Any]:
        """Read extracted text for PDF/DOCX/text-like attachments by character offset."""

        started = time.time()
        record = self._require_active(session_id, attachment_id)
        text_path = self._extracted_text_path(record)
        text = text_path.read_text(encoding="utf-8")
        safe_offset = max(0, int(offset))
        safe_max = max(1, min(int(max_chars or DEFAULT_TEXT_READ_CHARS), MAX_TEXT_READ_CHARS))
        fragment = text[safe_offset : safe_offset + safe_max]
        next_offset = safe_offset + len(fragment)
        truncated = next_offset < len(text)
        self._record_span(
            "attachment.read_text",
            started,
            record,
            {
                "offset": safe_offset,
                "max_chars": safe_max,
                "text_length": len(text),
                "returned_chars": len(fragment),
                "next_offset": next_offset if truncated else None,
                "truncated": truncated,
            },
        )
        return {
            "attachment_id": attachment_id,
            "filename": record.stored_filename,
            "offset": safe_offset,
            "max_chars": safe_max,
            "text_length": len(text),
            "returned_chars": len(fragment),
            "next_offset": next_offset if truncated else None,
            "truncated": truncated,
            "text": fragment,
        }

    def read_range(self, session_id: str, attachment_id: str, start_line: int, end_line: int, *, max_chars: int = 12000) -> dict[str, Any]:
        """读取文本、代码或日志附件的指定行范围，避免一次读取完整大文件。"""

        started = time.time()
        record = self._require_active(session_id, attachment_id)
        original_path = self.store.attachment_dir(record) / "original" / record.stored_filename
        lines = read_text_lossy(original_path).splitlines()
        start = max(1, int(start_line))
        end = min(len(lines), max(start, int(end_line)))
        text = "\n".join(lines[start - 1 : end])
        truncated = len(text) > max_chars
        self._record_span("attachment.read_range", started, record, {"line_range": [start, end], "truncated": truncated})
        return {"attachment_id": attachment_id, "filename": record.stored_filename, "line_start": start, "line_end": end, "text": text[:max_chars], "truncated": truncated}

    def search_symbols(self, session_id: str, query: str, *, attachment_id: str | None = None, top_k: int = 10) -> list[dict[str, Any]]:
        """搜索代码附件中的符号名称、签名和 docstring preview。"""

        started = time.time()
        records = [self._require_active(session_id, attachment_id)] if attachment_id else [record for record in self.list(session_id) if record.kind == AttachmentKind.CODE]
        symbols: list[CodeSymbol] = []
        for record in records:
            for item in record.metadata.get("symbols") or []:
                if isinstance(item, dict):
                    symbols.append(CodeSymbol.model_validate(item))
        results = search_symbols(symbols, query, top_k=top_k)
        if records:
            self._record_span("attachment.symbol_search", started, records[0], {"query": query[:200], "result_count": len(results)})
        return results

    def read_symbol(self, session_id: str, attachment_id: str, symbol_id: str, *, max_chars: int = 12000) -> dict[str, Any]:
        """按 symbol_id 读取局部代码文本，避免一次性读取完整代码附件。"""

        started = time.time()
        record = self._require_active(session_id, attachment_id)
        for item in record.metadata.get("symbols") or []:
            if isinstance(item, dict) and item.get("symbol_id") == symbol_id:
                symbol = CodeSymbol.model_validate(item)
                payload = read_symbol_text(record, symbol, attachment_dir=self.store.attachment_dir(record), max_chars=max_chars)
                self._record_span(
                    "attachment.read_symbol",
                    started,
                    record,
                    {"symbol_id": symbol.symbol_id, "symbol_name": symbol.name, "kind": symbol.kind, "line_start": symbol.line_start, "line_end": symbol.line_end, "preview": payload["text"][:160]},
                )
                return payload
        raise FileNotFoundError(f"Attachment symbol not found: {symbol_id}")

    def delete(self, session_id: str, attachment_id: str) -> dict[str, Any]:
        """将附件标记为 deleted，第一版不做物理删除以保留审计线索。"""

        started = time.time()
        record = self._require_active(session_id, attachment_id)
        record.status = AttachmentStatus.DELETED
        self.store.write_manifest(record)
        self._record_span("attachment.delete", started, record, {"status": record.status.value})
        return {"deleted": True, "attachment_id": attachment_id}

    def context_summary(self, session_id: str, *, limit: int = 8) -> str:
        """构建注入模型上下文的附件摘要，只包含清单和预览，不包含完整文件内容。"""

        records = self.list(session_id)[:limit]
        if not records:
            return ""
        lines = [
            "Current session attachments:",
            "Uploaded attachments are session-scoped files, not workspace paths. Do not use read_file on an attachment filename unless it has been imported into the workspace.",
            "The preview below is not full content. For broad questions about a full PDF/DOCX/document, inspect first, then use read_attachment_text with offsets until truncated is false; use search_attachment/read_attachment_chunk for targeted retrieval and read_attachment_range/read_attachment_symbol for code.",
            "Use list_attachments, inspect_attachment, search_attachment, read_attachment_text, search_attachment_symbols, read_attachment_symbol, read_attachment_chunk, or read_attachment_range when uploaded file content is needed.",
        ]
        for record in records:
            outline = record.metadata.get("outline")
            outline_preview = ""
            if isinstance(outline, list) and outline:
                outline_preview = "; outline: " + ", ".join(str(item.get("name") or item.get("kind")) for item in outline[:6] if isinstance(item, dict))
            text_length = record.metadata.get("text_length") or self._extracted_text_length(record)
            chunk_count = record.metadata.get("chunk_count", 0)
            lines.append(
                f"- {record.attachment_id}: filename={record.stored_filename}; original_name={record.original_filename}; kind={record.kind.value}; status={record.status.value}; size={record.size_bytes} bytes; chunks={chunk_count}; text_length={text_length or 0}; preview_only={record.text_preview[:240]}{outline_preview}"
            )
        return "\n".join(lines)

    def _require_active(self, session_id: str, attachment_id: str | None) -> AttachmentRecord:
        """检查并返回当前 session 的附件记录。"""
        if not attachment_id:
            raise ValueError("attachment_id is required")
        record = self.store.load(session_id, attachment_id)
        if record.status == AttachmentStatus.DELETED:
            raise FileNotFoundError(f"Attachment is deleted: {attachment_id}")
        return record

    def _extracted_text_path(self, record: AttachmentRecord) -> Path:
        """提取并返回附件提取文本的路径。"""
        if not record.extracted_text_path:
            raise FileNotFoundError(f"Attachment has no extracted text: {record.attachment_id}")
        path = (self.workspace / record.extracted_text_path).resolve()
        attachment_dir = self.store.attachment_dir(record).resolve()
        if attachment_dir not in path.parents and path != attachment_dir:
            raise ValueError("Attachment extracted text path escaped attachment store")
        if not path.exists():
            raise FileNotFoundError(f"Attachment extracted text not found: {record.attachment_id}")
        return path

    def _extracted_text_length(self, record: AttachmentRecord) -> int | None:
        try:
            return self._extracted_text_path(record).stat().st_size
        except (FileNotFoundError, ValueError):
            return None

    @staticmethod
    def _public_record(record: AttachmentRecord) -> dict[str, Any]:
        data = record.model_dump(mode="json")
        data.pop("original_path", None)
        return data

    def _record_span(self, name: str, started: float, record: AttachmentRecord, output: dict[str, Any], *, error: Exception | None = None) -> None:
        record_completed_span = getattr(self.observability, "record_completed_span", None)
        if not callable(record_completed_span):
            return
        safe_output = self._safe_trace_output(output)
        record_completed_span(
            name,
            "tool",
            status="error" if error else "ok",
            started_at=started,
            ended_at=time.time(),
            attributes={
                "attachment_id": record.attachment_id,
                "session_id": record.session_id,
                "filename": record.stored_filename,
                "kind": record.kind.value,
                "size_bytes": record.size_bytes,
                "sha256": record.sha256,
                "status": record.status.value,
            },
            output=safe_output,
            error=error,
        )

    @staticmethod
    def _safe_trace_output(output: dict[str, Any]) -> dict[str, Any]:
        """收紧附件 trace 输出，只保留短 preview/snippet 和结构化 metadata。"""

        safe: dict[str, Any] = {}
        for key, value in output.items():
            if key == "text" and isinstance(value, str):
                safe["text_length"] = len(value)
                continue
            if key in {"preview", "snippet"} and isinstance(value, str):
                safe[key] = value[:40]
                safe[f"{key}_length"] = len(value)
                continue
            safe[key] = value
        return safe
