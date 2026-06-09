from __future__ import annotations

from pathlib import Path
from typing import Callable
from typing import Optional

from pydantic import BaseModel, Field

from pp_agent.attachments.importer import AttachmentWorkspaceImporter
from pp_agent.attachments.memory_ingest import AttachmentMemoryIngestor
from pp_agent.attachments.service import AttachmentService
from pp_agent.observability import TraceRecorder, TraceStore


class AttachmentSearchRequest(BaseModel):
    """HTTP 检索请求体，支持限定单个 attachment 或搜索整个 session。"""

    query: str
    attachment_id: Optional[str] = None
    top_k: int = 5
    mode: str = "auto"


class AttachmentRangeRequest(BaseModel):
    """HTTP 行范围读取请求体，用于代码、日志和文本附件的局部预览。"""

    start_line: int
    end_line: int


class AttachmentTextRequest(BaseModel):
    """HTTP extracted text read request, bounded by offset and max_chars."""

    offset: int = 0
    max_chars: int = 30000


class AttachmentImportRequest(BaseModel):
    """HTTP 导入请求体，导入只会创建 Approval Gate 待审批动作。"""

    target_path: str
    overwrite: bool = False


class AttachmentMemoryIngestRequest(BaseModel):
    """HTTP memory ingest 请求体，只有显式调用时才写入长期记忆。"""

    mode: str = "selected_chunks"
    chunk_ids: list[str] = Field(default_factory=list)
    max_chunks: int = 100
    tags: list[str] = Field(default_factory=lambda: ["attachment"])
    scope: str = "workspace"


def mount_attachment_routes(app, active_workspace: Callable[[], Path]) -> None:
    """挂载 session-scoped attachment HTTP API，保持 web.server 主文件小而稳定。"""

    from fastapi import File, HTTPException, UploadFile
    globals()["File"] = File
    globals()["HTTPException"] = HTTPException
    globals()["UploadFile"] = UploadFile

    def service(session_id: str, *, trace_goal: str | None = None) -> tuple[AttachmentService, TraceRecorder | None]:
        workspace = active_workspace()
        recorder = TraceRecorder(TraceStore(workspace), workspace=workspace)
        if trace_goal:
            recorder.start_run(session_id=session_id, user_goal_preview=trace_goal, attributes={"entrypoint": "attachment_api"})
            return AttachmentService(workspace, observability=recorder), recorder
        return AttachmentService(workspace), None

    @app.post("/api/sessions/{session_id}/attachments")
    async def upload_attachment(session_id: str, file: UploadFile = File(...)) -> dict:
        recorder = None
        try:
            attachment_service, recorder = service(session_id, trace_goal="attachment.upload")
            data = await file.read()
            record = attachment_service.upload_bytes(session_id, file.filename or "attachment", data, content_type=file.content_type)
            return {"attachment": AttachmentService._public_record(record)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            if recorder is not None:
                recorder.end_run()

    @app.get("/api/sessions/{session_id}/attachments")
    def list_attachments(session_id: str) -> dict:
        attachment_service, _recorder = service(session_id)
        return {"attachments": [AttachmentService._public_record(record) for record in attachment_service.list(session_id)]}

    @app.get("/api/sessions/{session_id}/attachments/{attachment_id}")
    def inspect_attachment(session_id: str, attachment_id: str) -> dict:
        recorder = None
        try:
            attachment_service, recorder = service(session_id, trace_goal="attachment.inspect")
            return attachment_service.inspect(session_id, attachment_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            if recorder is not None:
                recorder.end_run()

    @app.get("/api/sessions/{session_id}/attachments/{attachment_id}/chunks/{chunk_id}")
    def read_attachment_chunk(session_id: str, attachment_id: str, chunk_id: str) -> dict:
        _ = attachment_id
        recorder = None
        try:
            attachment_service, recorder = service(session_id, trace_goal="attachment.read_chunk")
            return attachment_service.read_chunk(session_id, chunk_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            if recorder is not None:
                recorder.end_run()

    @app.post("/api/sessions/{session_id}/attachments/{attachment_id}/text")
    def read_attachment_text(session_id: str, attachment_id: str, request: AttachmentTextRequest) -> dict:
        recorder = None
        try:
            attachment_service, recorder = service(session_id, trace_goal="attachment.read_text")
            return attachment_service.read_text(session_id, attachment_id, offset=request.offset, max_chars=request.max_chars)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            if recorder is not None:
                recorder.end_run()

    @app.get("/api/sessions/{session_id}/attachments/{attachment_id}/symbols/{symbol_id}")
    def read_attachment_symbol(session_id: str, attachment_id: str, symbol_id: str) -> dict:
        recorder = None
        try:
            attachment_service, recorder = service(session_id, trace_goal="attachment.read_symbol")
            return attachment_service.read_symbol(session_id, attachment_id, symbol_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            if recorder is not None:
                recorder.end_run()

    @app.post("/api/sessions/{session_id}/attachments/{attachment_id}/range")
    def read_attachment_range(session_id: str, attachment_id: str, request: AttachmentRangeRequest) -> dict:
        recorder = None
        try:
            attachment_service, recorder = service(session_id, trace_goal="attachment.read_range")
            return attachment_service.read_range(session_id, attachment_id, request.start_line, request.end_line)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            if recorder is not None:
                recorder.end_run()

    @app.post("/api/sessions/{session_id}/attachments/{attachment_id}/import/preview")
    def preview_attachment_import(session_id: str, attachment_id: str, request: AttachmentImportRequest) -> dict:
        recorder = None
        try:
            workspace = active_workspace()
            recorder = TraceRecorder(TraceStore(workspace), workspace=workspace)
            recorder.start_run(session_id=session_id, user_goal_preview="attachment.import_preview", attributes={"entrypoint": "attachment_api"})
            return AttachmentWorkspaceImporter(workspace, observability=recorder).preview_import(
                session_id,
                attachment_id,
                target_path=request.target_path,
                overwrite=request.overwrite,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            if recorder is not None:
                recorder.end_run()

    @app.post("/api/sessions/{session_id}/attachments/{attachment_id}/import")
    def request_attachment_import(session_id: str, attachment_id: str, request: AttachmentImportRequest) -> dict:
        recorder = None
        try:
            workspace = active_workspace()
            recorder = TraceRecorder(TraceStore(workspace), workspace=workspace)
            recorder.start_run(session_id=session_id, user_goal_preview="attachment.import_requested", attributes={"entrypoint": "attachment_api"})
            return AttachmentWorkspaceImporter(workspace, observability=recorder).request_import(
                session_id,
                attachment_id,
                target_path=request.target_path,
                overwrite=request.overwrite,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            if recorder is not None:
                recorder.end_run()

    @app.post("/api/sessions/{session_id}/attachments/{attachment_id}/ingest-memory/preview")
    def preview_attachment_memory_ingest(session_id: str, attachment_id: str) -> dict:
        recorder = None
        try:
            workspace = active_workspace()
            recorder = TraceRecorder(TraceStore(workspace), workspace=workspace)
            recorder.start_run(session_id=session_id, user_goal_preview="attachment.memory_ingest_preview", attributes={"entrypoint": "attachment_api"})
            return AttachmentMemoryIngestor(workspace, observability=recorder).preview(session_id, attachment_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            if recorder is not None:
                recorder.end_run()

    @app.post("/api/sessions/{session_id}/attachments/{attachment_id}/ingest-memory")
    def ingest_attachment_memory(session_id: str, attachment_id: str, request: AttachmentMemoryIngestRequest) -> dict:
        recorder = None
        try:
            workspace = active_workspace()
            recorder = TraceRecorder(TraceStore(workspace), workspace=workspace)
            recorder.start_run(session_id=session_id, user_goal_preview="attachment.memory_ingest", attributes={"entrypoint": "attachment_api"})
            return AttachmentMemoryIngestor(workspace, observability=recorder).ingest(
                session_id,
                attachment_id,
                mode=request.mode,
                chunk_ids=request.chunk_ids,
                max_chunks=request.max_chunks,
                tags=request.tags,
                scope=request.scope,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            if recorder is not None:
                recorder.end_run()

    @app.post("/api/sessions/{session_id}/attachments/search")
    def search_attachment(session_id: str, request: AttachmentSearchRequest) -> dict:
        recorder = None
        try:
            attachment_service, recorder = service(session_id, trace_goal="attachment.search")
            return {"results": attachment_service.search(session_id, request.query, attachment_id=request.attachment_id, top_k=request.top_k, mode=request.mode)}
        finally:
            if recorder is not None:
                recorder.end_run()

    @app.delete("/api/sessions/{session_id}/attachments/{attachment_id}")
    def delete_attachment(session_id: str, attachment_id: str) -> dict:
        recorder = None
        try:
            attachment_service, recorder = service(session_id, trace_goal="attachment.delete")
            return attachment_service.delete(session_id, attachment_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            if recorder is not None:
                recorder.end_run()
