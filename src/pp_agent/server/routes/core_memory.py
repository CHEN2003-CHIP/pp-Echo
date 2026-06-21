from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from pp_agent.app.bootstrap import load_settings
from pp_agent.memory.core_service import service_for_workspace
from pp_agent.memory.core_tools import candidate_from_arguments
from pp_agent.memory.core_renderer import workspace_id_for_path


class CoreMemoryProposeRequest(BaseModel):
    content: str
    scope: str = "workspace"
    section: str = "project_profile"
    type: str = "general"
    confidence: float = 0.5
    reason: str = ""
    source: dict[str, Any] = {}
    metadata: dict[str, Any] = {}


class CoreMemoryActionRequest(BaseModel):
    actor: str = "web"
    reason: str = ""


class CoreMemoryReplaceRequest(CoreMemoryProposeRequest):
    actor: str = "web"


def mount_core_memory_routes(app, active_workspace) -> None:
    from fastapi import HTTPException

    def service():
        workspace = active_workspace()
        return service_for_workspace(workspace, load_settings(workspace))

    def memory_payload(memory) -> dict[str, Any]:
        return memory.model_dump(mode="json")

    def result_payload(result) -> dict[str, Any]:
        return {
            "memory": memory_payload(result.memory),
            "warnings": list(result.warnings),
            "duplicate_of": result.duplicate_of,
            "safety": dict(result.safety),
            "conflicts_with": list(result.conflicts_with),
            "budget": dict(result.budget),
            "audit": list(result.audit),
        }

    @app.get("/api/memory/core/pending")
    def core_memory_pending() -> dict[str, Any]:
        workspace_id = workspace_id_for_path(active_workspace())
        return {"pending": [memory_payload(memory) for memory in service().store.list_pending(workspace_id=workspace_id)]}

    @app.get("/api/memory/core/active")
    def core_memory_active() -> dict[str, Any]:
        workspace_id = workspace_id_for_path(active_workspace())
        return {"active": [memory_payload(memory) for memory in service().store.list_active(workspace_id=workspace_id)]}

    @app.post("/api/memory/core/propose")
    def core_memory_propose(request: CoreMemoryProposeRequest) -> dict[str, Any]:
        try:
            candidate = candidate_from_arguments(request.model_dump(mode="python"), workspace=active_workspace())
            return result_payload(service().propose(candidate, actor="web", reason=request.reason))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/memory/core/{memory_id}/approve")
    def core_memory_approve(memory_id: str, request: CoreMemoryActionRequest) -> dict[str, Any]:
        try:
            return result_payload(service().approve(memory_id, actor=request.actor, reason=request.reason))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/memory/core/{memory_id}/reject")
    def core_memory_reject(memory_id: str, request: CoreMemoryActionRequest) -> dict[str, Any]:
        try:
            return result_payload(service().reject(memory_id, actor=request.actor, reason=request.reason))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/memory/core/{memory_id}/archive")
    def core_memory_archive(memory_id: str, request: CoreMemoryActionRequest) -> dict[str, Any]:
        try:
            return result_payload(service().archive(memory_id, actor=request.actor, reason=request.reason))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/memory/core/{memory_id}/replace")
    def core_memory_replace(memory_id: str, request: CoreMemoryReplaceRequest) -> dict[str, Any]:
        try:
            candidate = candidate_from_arguments(request.model_dump(mode="python"), workspace=active_workspace())
            return result_payload(service().replace(memory_id, candidate, actor=request.actor, reason=request.reason))
        except (KeyError, ValueError) as exc:
            status = 404 if isinstance(exc, KeyError) else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.get("/api/memory/core/snapshot")
    def core_memory_snapshot(session_id: Optional[str] = None) -> dict[str, Any]:
        return service().snapshot(session_id=session_id).model_dump(mode="json")

    @app.get("/api/memory/core/audit")
    def core_memory_audit(memory_id: Optional[str] = None, limit: int = 100) -> dict[str, Any]:
        records = service().audit(memory_id=memory_id, limit=max(1, min(500, int(limit))))
        return {"audit": [record.model_dump(mode="json") for record in records]}

    @app.get("/api/memory/core/compact-preview")
    def core_memory_compact_preview() -> dict[str, Any]:
        return service().compact_preview()

    @app.post("/api/memory/core/compact-apply")
    def core_memory_compact_apply(request: CoreMemoryActionRequest) -> dict[str, Any]:
        return service().compact_apply(actor=request.actor, reason=request.reason or "manual_compaction")

    @app.get("/api/memory/core/merge-preview")
    def core_memory_merge_preview() -> dict[str, Any]:
        return service().merge_preview()

    @app.post("/api/memory/core/merge-apply")
    def core_memory_merge_apply(request: CoreMemoryActionRequest) -> dict[str, Any]:
        return service().merge_apply(actor=request.actor, reason=request.reason or "auto_merge")

    @app.get("/api/memory/core/provider/status")
    def core_memory_provider_status() -> dict[str, Any]:
        return service().provider.status()
