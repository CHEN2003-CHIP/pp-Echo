from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from pp_agent.api import sdk
from pp_agent.app import bootstrap
from pp_agent.cli.commands.approvals import (
    approve_or_execute_pending_action,
    load_pending_action_or_user_error,
    reject_pending_action as reject_pending_action_by_token,
)
from pp_agent.web.session_manager import WebSessionManager
from pp_agent.web.workspaces import WebWorkspaceManager
from pp_agent.server.error_logging import write_server_error_log


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


class GitSwitchRequest(BaseModel):
    branch: str


class GitCreateBranchRequest(BaseModel):
    branch: str


def create_app(
    workspace: Path,
    *,
    manager: Optional[WebSessionManager] = None,
    workspace_manager: Optional[WebWorkspaceManager] = None,
):
    """创建 FastAPI应用  定义 API 路由"""
    try:
        from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse
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

    from pp_agent.server.routes.config import mount_config_routes
    from pp_agent.server.routes.capability_config import mount_capability_config_routes
    from pp_agent.server.routes.onboarding import mount_onboarding_routes
    from pp_agent.server.routes.traces import mount_trace_routes
    from pp_agent.server.routes.attachments import mount_attachment_routes
    from pp_agent.server.routes.qqbot import mount_qqbot_routes
    from pp_agent.server.routes.bots import mount_bot_routes

    mount_config_routes(app, active_workspace, session_manager)
    mount_capability_config_routes(app, active_workspace)
    mount_onboarding_routes(app, active_workspace)
    mount_trace_routes(app, active_workspace)
    mount_attachment_routes(app, active_workspace)
    mount_bot_routes(app, active_workspace)
    mount_qqbot_routes(app, active_workspace, session_manager)

    @app.middleware("http")
    async def no_cache(request, call_next):
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            payload = write_server_error_log(active_workspace(), exc, request=request)
            return JSONResponse(
                status_code=500,
                content={
                    "detail": {
                        "message": "Internal server error. See backend log for traceback.",
                        **payload,
                    }
                },
            )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "app": "pp-Echo", "workspace": str(active_workspace())}

    @app.get("/api/workspace")
    def workspace_info() -> dict:
        workspace = active_workspace()
        return {"path": str(workspace), "name": workspace.name or str(workspace)}

    @app.get("/api/workspace/status")
    def workspace_status() -> dict:
        workspace = active_workspace()
        git = _git_status(workspace)
        return {
            "path": str(workspace),
            "name": workspace.name or str(workspace),
            "git_branch": git.get("current_branch") or _git_branch(workspace),
            "git_dirty_count": git.get("dirty_count", 0),
        }

    @app.get("/api/workspace/git")
    def workspace_git() -> dict:
        return _git_status(active_workspace())

    @app.post("/api/workspace/git/switch")
    def workspace_git_switch(request: GitSwitchRequest) -> dict:
        branch = request.branch.strip()
        if not branch:
            raise HTTPException(status_code=400, detail="branch is required")
        try:
            _git_run(active_workspace(), ["git", "switch", branch], timeout=8, raise_on_error=True)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _git_status(active_workspace())

    @app.post("/api/workspace/git/branches")
    def workspace_git_create_branch(request: GitCreateBranchRequest) -> dict:
        branch = request.branch.strip()
        if not branch:
            raise HTTPException(status_code=400, detail="branch is required")
        try:
            _validate_git_branch_name(active_workspace(), branch)
            _git_run(active_workspace(), ["git", "switch", "-c", branch], timeout=8, raise_on_error=True)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _git_status(active_workspace())

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
        return {"sessions": session_manager().list_sessions()}

    @app.post("/api/sessions")
    def create_session() -> dict:
        return session_manager().create_session()

    @app.get("/api/sessions/{session_id}")
    def session_snapshot(session_id: str) -> dict:
        try:
            return session_manager().snapshot(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/events")
    def session_events(session_id: str) -> dict:
        try:
            handle = session_manager().get_active_handle(session_id)
            return {"events": handle.drain_events() if handle is not None else []}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/timeline")
    def session_timeline(session_id: str, limit: int = 80) -> dict:
        try:
            entries = bootstrap.timeline_store_for(active_workspace()).list_session(
                session_id,
                limit=max(1, min(500, int(limit))),
            )
            return {"timeline": [entry.model_dump(mode="json") for entry in entries]}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/timeline")
    def recent_timeline(limit: int = 80) -> dict:
        entries = bootstrap.timeline_store_for(active_workspace()).list_recent(limit=max(1, min(500, int(limit))))
        return {"timeline": [entry.model_dump(mode="json") for entry in entries]}

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

    @app.post("/api/sessions/{session_id}/cancel")
    def cancel(session_id: str) -> dict:
        try:
            return session_manager().get_handle(session_id).cancel()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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

    @app.get("/api/runtime/report")
    def runtime_report(session_id: Optional[str] = None) -> dict:
        return sdk.runtime_doctor_report(active_workspace(), session_id=session_id)

    @app.get("/api/runtime/maintenance/preview")
    def runtime_maintenance_preview(session_id: Optional[str] = None) -> dict:
        return sdk.runtime_maintenance(active_workspace(), session_id=session_id, apply=False)

    @app.post("/api/runtime/maintenance/apply")
    def runtime_maintenance_apply(session_id: Optional[str] = None) -> dict:
        return sdk.runtime_maintenance(active_workspace(), session_id=session_id, apply=True)

    @app.post("/api/approvals/{token}/approve")
    def approve_pending_action(token: str) -> dict:
        try:
            payload = load_pending_action_or_user_error(active_workspace(), token)
            details = payload.get("details", {}) if isinstance(payload.get("details"), dict) else {}
            session_id = str(payload.get("session_id") or details.get("session_id") or "").strip()
            handle = session_manager().get_handle(session_id) if session_id else None
            return approve_or_execute_pending_action(
                active_workspace(),
                token,
                render=False,
                runtime=handle.agent if handle is not None else None,
            )
        except (FileNotFoundError, RuntimeError, ValueError, PermissionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/approvals/{token}/reject")
    def reject_pending_action(token: str) -> dict:
        try:
            payload = load_pending_action_or_user_error(active_workspace(), token)
            details = payload.get("details", {}) if isinstance(payload.get("details"), dict) else {}
            session_id = str(payload.get("session_id") or details.get("session_id") or "").strip()
            handle = session_manager().get_handle(session_id) if session_id else None
            return reject_pending_action_by_token(
                active_workspace(),
                token,
                render=False,
                runtime=handle.agent if handle is not None else None,
            )
        except (FileNotFoundError, RuntimeError, ValueError, PermissionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/capabilities")
    def capabilities(kind: Optional[str] = None, include_mcp: Optional[bool] = None) -> dict:
        return {"capabilities": sdk.list_capabilities(active_workspace(), kind=kind, include_mcp=include_mcp)}

    @app.get("/api/mcp")
    def mcp() -> dict:
        settings = bootstrap.load_settings(active_workspace())
        return settings.capabilities.mcp.model_dump(mode="json")

    @app.websocket("/api/sessions/{session_id}/events")
    async def events(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        try:
            handle = session_manager().get_active_handle(session_id)
            if handle is None:
                await websocket.close(code=4404)
                return
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


def _git_branch(workspace: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=workspace,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        branch = result.stdout.strip()
        if branch:
            return branch
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=workspace,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        commit = result.stdout.strip()
        return f"detached:{commit}" if commit else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _git_run(
    workspace: Path,
    args: list[str],
    *,
    timeout: int = 3,
    raise_on_error: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            cwd=workspace,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if raise_on_error:
            raise RuntimeError(str(exc)) from exc
        return subprocess.CompletedProcess(args, 1, "", str(exc))
    if raise_on_error and result.returncode != 0:
        message = (result.stderr or result.stdout or "git command failed").strip()
        raise RuntimeError(message)
    return result


def _git_status(workspace: Path) -> dict:
    root = _git_run(workspace, ["git", "rev-parse", "--show-toplevel"])
    if root.returncode != 0:
        return {
            "is_repo": False,
            "current_branch": "",
            "branches": [],
            "dirty_count": 0,
            "untracked_count": 0,
            "ahead": 0,
            "behind": 0,
            "error": (root.stderr or "").strip(),
        }

    current_branch = _git_branch(workspace)
    branch_result = _git_run(workspace, ["git", "branch", "--format=%(refname:short)|%(HEAD)|%(upstream:short)"])
    branches = []
    for line in branch_result.stdout.splitlines():
        name, marker, upstream = (line.split("|", 2) + ["", ""])[:3]
        if not name.strip():
            continue
        branches.append({"name": name.strip(), "current": marker.strip() == "*", "upstream": upstream.strip()})

    status_result = _git_run(workspace, ["git", "status", "--porcelain=v1", "--branch"])
    dirty_count = 0
    untracked_count = 0
    ahead = 0
    behind = 0
    for line in status_result.stdout.splitlines():
        if line.startswith("##"):
            ahead, behind = _parse_ahead_behind(line)
            continue
        if not line:
            continue
        dirty_count += 1
        if line.startswith("??"):
            untracked_count += 1

    return {
        "is_repo": True,
        "current_branch": current_branch,
        "branches": branches,
        "dirty_count": dirty_count,
        "untracked_count": untracked_count,
        "ahead": ahead,
        "behind": behind,
        "error": "",
    }


def _validate_git_branch_name(workspace: Path, branch: str) -> None:
    result = _git_run(workspace, ["git", "check-ref-format", "--branch", branch], timeout=3)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Invalid branch name").strip())


def _parse_ahead_behind(line: str) -> tuple[int, int]:
    ahead = 0
    behind = 0
    for part in line.replace("[", ",").replace("]", ",").split(","):
        text = part.strip()
        if text.startswith("ahead "):
            ahead = _safe_int(text.removeprefix("ahead "))
        elif text.startswith("behind "):
            behind = _safe_int(text.removeprefix("behind "))
    return ahead, behind


def _safe_int(value: str) -> int:
    try:
        return int(value.strip())
    except ValueError:
        return 0
