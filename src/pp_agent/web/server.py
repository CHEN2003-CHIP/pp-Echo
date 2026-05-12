from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from pp_agent.api import sdk
from pp_agent.app import bootstrap
from pp_agent.cli.commands.approvals import (
    approve_or_execute_pending_action,
    reject_pending_action as reject_pending_action_by_token,
)
from pp_agent.web.session_manager import WebSessionManager
from pp_agent.web.workspaces import WebWorkspaceManager


class PromptRequest(BaseModel):
    prompt: str


class CheckpointRequest(BaseModel):
    head_id: Optional[str] = None
    turn_id: Optional[str] = None
    reason: str = "manual"
    snapshot_type: str = "head_snapshot"


class RewindRequest(BaseModel):
    checkpoint_id: Optional[str] = None
    turn_count: Optional[int] = None
    message_count: Optional[int] = None
    mode: str = "conversation_and_workspace"
    allow_stash_snapshot: bool = False


class OpenWorkspaceRequest(BaseModel):
    path: str
    confirmed: bool = False


def create_app(
    workspace: Path,
    *,
    manager: Optional[WebSessionManager] = None,
    workspace_manager: Optional[WebWorkspaceManager] = None,
):
    try:
        from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install pp-agent with the 'web' extra to use the web server.") from exc

    workspace_manager = workspace_manager or WebWorkspaceManager(workspace, initial_manager=manager)
    app = FastAPI(title="pp-Echo Web API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8765", "http://localhost:8765"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.workspace_manager = workspace_manager

    def active_workspace() -> Path:
        return workspace_manager.active_workspace

    def session_manager() -> WebSessionManager:
        return workspace_manager.active_session_manager()

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "app": "pp-Echo", "workspace": str(active_workspace())}

    @app.get("/api/workspace")
    def workspace_info() -> dict:
        workspace = active_workspace()
        return {"path": str(workspace), "name": workspace.name or str(workspace)}

    @app.get("/api/workspaces")
    def workspaces() -> dict:
        return workspace_manager.summary()

    @app.post("/api/workspaces/open")
    def open_workspace(request: OpenWorkspaceRequest) -> dict:
        try:
            return workspace_manager.open_workspace(request.path, confirmed=request.confirmed)
        except (FileNotFoundError, NotADirectoryError, ValueError, PermissionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/settings")
    def settings() -> dict:
        loaded = bootstrap.load_settings(active_workspace())
        return loaded.model_dump(mode="json")

    @app.get("/api/sessions")
    def list_sessions() -> dict:
        return {"sessions": sdk.list_sessions(active_workspace())}

    @app.post("/api/sessions")
    def create_session() -> dict:
        return session_manager().create_session()

    @app.get("/api/sessions/{session_id}")
    def session_snapshot(session_id: str) -> dict:
        try:
            return session_manager().get_handle(session_id).snapshot()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/events")
    def session_events(session_id: str) -> dict:
        try:
            return {"events": session_manager().get_handle(session_id).drain_events()}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/tree")
    def session_tree(session_id: str) -> dict:
        try:
            return sdk.get_session_tree(active_workspace(), session_id=session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/prompt")
    def prompt(session_id: str, request: PromptRequest) -> dict:
        try:
            return session_manager().get_handle(session_id).prompt(request.prompt)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/continue")
    def continue_session(session_id: str) -> dict:
        try:
            return session_manager().get_handle(session_id).continue_()
        except (FileNotFoundError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/approve")
    def approve(session_id: str) -> dict:
        try:
            return session_manager().get_handle(session_id).approve()
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/reject")
    def reject(session_id: str) -> dict:
        try:
            return session_manager().get_handle(session_id).reject()
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/fork")
    def fork(session_id: str, head_id: Optional[str] = None) -> dict:
        try:
            return sdk.fork_session(active_workspace(), session_id, head_id=head_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/checkpoints")
    def checkpoints(session_id: str) -> dict:
        return {"checkpoints": sdk.list_checkpoints(active_workspace(), session_id=session_id)}

    @app.post("/api/sessions/{session_id}/checkpoints")
    def create_checkpoint(session_id: str, request: CheckpointRequest) -> dict:
        return sdk.create_checkpoint(
            active_workspace(),
            session_id,
            head_id=request.head_id,
            turn_id=request.turn_id,
            reason=request.reason,
            snapshot_type=request.snapshot_type,
        )

    @app.post("/api/sessions/{session_id}/rewind/preview")
    def preview_rewind(session_id: str, request: RewindRequest) -> dict:
        return sdk.preview_rewind(
            active_workspace(),
            session_id,
            checkpoint_id=request.checkpoint_id,
            turn_count=request.turn_count,
            message_count=request.message_count,
            mode=request.mode,
            allow_stash_snapshot=request.allow_stash_snapshot,
        )

    @app.post("/api/sessions/{session_id}/rewind")
    def rewind(session_id: str, request: RewindRequest) -> dict:
        return sdk.rewind_safe(
            active_workspace(),
            session_id,
            checkpoint_id=request.checkpoint_id,
            turn_count=request.turn_count,
            message_count=request.message_count,
            mode=request.mode,
            allow_stash_snapshot=request.allow_stash_snapshot,
        )

    @app.get("/api/approvals")
    def approvals() -> dict:
        return sdk.approvals_summary(active_workspace())

    @app.post("/api/approvals/{token}/approve")
    def approve_pending_action(token: str) -> dict:
        try:
            return approve_or_execute_pending_action(active_workspace(), token, render=False)
        except (FileNotFoundError, RuntimeError, ValueError, PermissionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/approvals/{token}/reject")
    def reject_pending_action(token: str) -> dict:
        try:
            return reject_pending_action_by_token(active_workspace(), token, render=False)
        except (FileNotFoundError, RuntimeError, ValueError, PermissionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/capabilities")
    def capabilities(kind: Optional[str] = None, include_mcp: Optional[bool] = None) -> dict:
        return {"capabilities": sdk.list_capabilities(active_workspace(), kind=kind, include_mcp=include_mcp)}

    @app.get("/api/mcp")
    def mcp() -> dict:
        settings = bootstrap.load_settings(active_workspace())
        return settings.capabilities.mcp.model_dump(mode="json")

    @app.get("/favicon.ico")
    def favicon() -> dict:
        return {}

    @app.websocket("/api/sessions/{session_id}/events")
    async def events(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        try:
            handle = session_manager().get_handle(session_id)
            while True:
                for event in handle.drain_events():
                    await websocket.send_json(event)
                await asyncio.sleep(0.1)
        except WebSocketDisconnect:
            return
        except FileNotFoundError:
            await websocket.close(code=4404)

    static_root = Path(__file__).resolve().parents[3] / "web" / "dist"
    if static_root.exists():
        app.mount("/", StaticFiles(directory=static_root, html=True), name="web")

    return app
