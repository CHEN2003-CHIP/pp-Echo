from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel

from pp_agent.web.coding_service import (
    CodingApprovalNotFound,
    CodingApprovalNotSupported,
    CodingTaskNotFound,
    CodingWorkflowService,
    coding_task_state_to_dict,
    extract_validation_commands,
    sanitize_pending_approval,
    summarize_timeline_block,
)


WorkspaceProvider = Callable[[], Path]


class CodingTaskStartRequest(BaseModel):
    task: str
    workspace: Optional[str] = None
    max_turns: Optional[int] = None
    prepare_only: Optional[bool] = None


class CodingApprovalApproveRequest(BaseModel):
    confirm: Optional[bool] = True


class CodingApprovalRejectRequest(BaseModel):
    reason: Optional[str] = None


def create_coding_api_app(
    service: CodingWorkflowService | None = None,
    *,
    workspace: Path | None = None,
):
    """Create a small FastAPI app exposing the Web Coding Workflow API.

    This factory is for Web/API entrypoints and tests. It exposes sanitized
    `CodingTaskState` dictionaries, does not auto-approve or apply pending actions, and accepts
    an injected service so tests can avoid real runtime, shell, or LLM execution.
    """

    try:
        from fastapi import FastAPI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install pp-agent with the 'web' extra to use the coding API.") from exc

    app = FastAPI(title="pp-Echo Coding API", version="0.1.0")
    resolved_workspace = Path(workspace) if workspace is not None else Path.cwd()
    mount_coding_routes(app, lambda: resolved_workspace, service=service)
    return app


def mount_coding_routes(
    app: Any,
    active_workspace: WorkspaceProvider,
    *,
    service: CodingWorkflowService | None = None,
) -> None:
    """Mount Coding Workflow API routes on an existing FastAPI app.

    The mounted routes are a Web frontend contract over `CodingWorkflowService`. They return
    sanitized `CodingTaskState` data, never approve or apply actions, and allow service injection
    so tests and embedding hosts do not need a real runtime.
    """

    coding_service = service or CodingWorkflowService()

    @app.post("/api/coding/tasks")
    def start_coding_task(request: CodingTaskStartRequest):
        parsed = parse_coding_task_request(request, active_workspace())
        if parsed["error"]:
            return coding_api_error("bad_request", parsed["error"], status_code=400)
        try:
            state = coding_service.start_task(
                parsed["task"],
                workspace=parsed["workspace"],
                max_turns=parsed["max_turns"],
                prepare_only=parsed["prepare_only"],
            )
        except ValueError as exc:
            return coding_api_error("bad_request", str(exc), status_code=400)
        except Exception:  # noqa: BLE001
            return coding_api_error("internal_error", "coding task failed", status_code=500)
        return coding_api_state_to_dict(state)

    @app.get("/api/coding/tasks/{task_id}")
    def get_coding_task(task_id: str):
        state = coding_service.get_task(task_id)
        if state is None:
            return coding_api_error("not_found", "coding task not found", status_code=404)
        return coding_api_state_to_dict(state)

    @app.get("/api/coding/tasks/{task_id}/timeline")
    def get_coding_task_timeline(task_id: str):
        if coding_service.get_task(task_id) is None:
            return coding_api_error("not_found", "coding task not found", status_code=404)
        return {"task_id": task_id, "timeline_blocks": [summarize_timeline_block(block) for block in coding_service.get_timeline(task_id)]}

    @app.get("/api/coding/tasks/{task_id}/pending-approvals")
    def get_coding_task_pending_approvals(task_id: str):
        if coding_service.get_task(task_id) is None:
            return coding_api_error("not_found", "coding task not found", status_code=404)
        return {"task_id": task_id, "pending_approvals": [sanitize_pending_approval(item) for item in coding_service.get_pending_approvals(task_id)]}

    @app.get("/api/coding/tasks/{task_id}/validation-plan")
    def get_coding_task_validation_plan(task_id: str):
        if coding_service.get_task(task_id) is None:
            return coding_api_error("not_found", "coding task not found", status_code=404)
        return {"task_id": task_id, "validation_commands": extract_validation_commands(coding_service.get_validation_plan(task_id))}

    @app.post("/api/coding/tasks/{task_id}/approvals/{token}/approve")
    def approve_coding_task_action(task_id: str, token: str, request: Optional[CodingApprovalApproveRequest] = None):
        if request is not None and request.confirm is False:
            return coding_api_error("bad_request", "confirm must be true to approve action", status_code=400)
        try:
            return coding_api_state_to_dict(coding_service.approve_action(task_id, token))
        except CodingTaskNotFound as exc:
            return coding_api_error("not_found", str(exc), status_code=404)
        except CodingApprovalNotFound as exc:
            return coding_api_error("not_found", str(exc), status_code=404)
        except CodingApprovalNotSupported as exc:
            return coding_api_error("not_supported", str(exc), status_code=501)

    @app.post("/api/coding/tasks/{task_id}/approvals/{token}/reject")
    def reject_coding_task_action(task_id: str, token: str, request: Optional[CodingApprovalRejectRequest] = None):
        try:
            return coding_api_state_to_dict(coding_service.reject_action(task_id, token, reason=request.reason if request else None))
        except CodingTaskNotFound as exc:
            return coding_api_error("not_found", str(exc), status_code=404)
        except CodingApprovalNotFound as exc:
            return coding_api_error("not_found", str(exc), status_code=404)


def parse_coding_task_request(request: CodingTaskStartRequest, default_workspace: Path) -> dict[str, Any]:
    """Parse a start-task request for the Web Coding Workflow API.

    The helper normalizes defaults for the API layer only. It does not load `.env`, execute tools,
    approve actions, or expose raw payloads; tests can call it directly without a runtime.
    """

    task = (request.task or "").strip()
    if not task:
        return {"error": "task is required"}
    workspace = Path(request.workspace).expanduser() if request.workspace else Path(default_workspace)
    max_turns = 3 if request.max_turns is None else max(0, int(request.max_turns))
    prepare_only = bool(request.prepare_only) if request.prepare_only is not None else False
    return {
        "error": "",
        "task": task,
        "workspace": workspace,
        "max_turns": max_turns,
        "prepare_only": prepare_only,
    }


def coding_api_error(error: str, message: str, *, status_code: int = 400):
    """Build a JSON error response for the Web Coding Workflow API.

    Error responses use `{error, message}` and intentionally avoid Python tracebacks, raw prompts,
    payloads, file contents, diffs, digest inputs, or approval internals.
    """

    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"error": error, "message": message})


def coding_api_state_to_dict(state: Any) -> dict[str, Any]:
    """Return a defense-in-depth sanitized CodingTaskState API payload.

    The service already emits sanitized state, but the API applies the same filters again so an
    injected fake service or future backend cannot leak payloads, file contents, diffs, or digest
    inputs into the Web frontend response.
    """

    payload = coding_task_state_to_dict(state)
    payload["timeline_blocks"] = [summarize_timeline_block(block) for block in payload.get("timeline_blocks", [])]
    payload["pending_approvals"] = [sanitize_pending_approval(item) for item in payload.get("pending_approvals", [])]
    payload["validation_commands"] = extract_validation_commands(payload.get("validation_commands", []))
    return payload


__all__ = [
    "CodingTaskStartRequest",
    "CodingApprovalApproveRequest",
    "CodingApprovalRejectRequest",
    "coding_api_error",
    "coding_api_state_to_dict",
    "create_coding_api_app",
    "mount_coding_routes",
    "parse_coding_task_request",
]
