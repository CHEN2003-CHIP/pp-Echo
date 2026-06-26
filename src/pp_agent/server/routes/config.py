from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from pp_agent.config import ConfigConflictError, ConfigValidationError, get_config_manager
from pp_agent.runtime.tool_surface import active_tool_surface


class ConfigPatchRequest(BaseModel):
    patch: dict[str, Any]
    base_hash: Optional[str] = None


class ConfigSetRequest(BaseModel):
    path: str
    value: Any
    base_hash: Optional[str] = None


class ModelOverrideRequest(BaseModel):
    model: str
    provider_id: Optional[str] = None


class ProfileSetRequest(BaseModel):
    profile: Optional[str] = None
    path: Optional[str] = None
    value: Any = None
    base_hash: Optional[str] = None
    session_id: Optional[str] = None


class DebugSetRequest(BaseModel):
    path: str
    value: Any
    session_id: Optional[str] = None


def mount_config_routes(app, active_workspace, session_manager) -> None:
    from fastapi import HTTPException

    def manager():
        return get_config_manager(active_workspace())

    def snapshot_payload(session_id: str | None = None) -> dict[str, Any]:
        return manager().get_effective_snapshot(session_id=session_id).model_dump(mode="json")

    def validation_error(exc: ConfigValidationError):
        return HTTPException(status_code=400, detail={"message": str(exc), "errors": exc.errors})

    def mark_pending(session_id: str | None, snapshot_payload: dict[str, Any]) -> None:
        if not session_id:
            return
        handle = session_manager().get_active_handle(session_id)
        if handle is not None:
            setattr(handle.agent, "pending_config_effects", list(snapshot_payload.get("pending_effects") or []))

    @app.get("/api/config")
    def config_get(session_id: Optional[str] = None) -> dict[str, Any]:
        return snapshot_payload(session_id=session_id)

    @app.patch("/api/config")
    def config_patch(request: ConfigPatchRequest) -> dict[str, Any]:
        try:
            return manager().patch_project_config(request.patch, base_hash=request.base_hash).model_dump(mode="json")
        except ConfigConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(exc),
                    "expected_hash": exc.expected_hash,
                    "actual_hash": exc.actual_hash,
                },
            ) from exc
        except ConfigValidationError as exc:
            raise validation_error(exc) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/config/set")
    def config_set(request: ConfigSetRequest) -> dict[str, Any]:
        try:
            return manager().set_path(request.path, request.value, base_hash=request.base_hash).model_dump(mode="json")
        except ConfigConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(exc),
                    "expected_hash": exc.expected_hash,
                    "actual_hash": exc.actual_hash,
                },
            ) from exc
        except ConfigValidationError as exc:
            raise validation_error(exc) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/config/profile")
    def set_project_profile(request: ProfileSetRequest) -> dict[str, Any]:
        try:
            snapshot = manager().set_active_profile(request.profile, base_hash=request.base_hash, session_id=request.session_id)
            payload = snapshot.model_dump(mode="json")
            mark_pending(request.session_id, payload)
            return payload
        except ConfigConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(exc),
                    "expected_hash": exc.expected_hash,
                    "actual_hash": exc.actual_hash,
                },
            ) from exc
        except ConfigValidationError as exc:
            raise validation_error(exc) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/config/profile/set")
    def config_profile_set(request: ProfileSetRequest) -> dict[str, Any]:
        try:
            if not request.profile or not request.path:
                raise ValueError("profile and path are required")
            snapshot = manager().set_profile_path(
                request.profile,
                request.path,
                request.value,
                base_hash=request.base_hash,
                session_id=request.session_id,
            )
            payload = snapshot.model_dump(mode="json")
            mark_pending(request.session_id, payload)
            return payload
        except ConfigConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(exc),
                    "expected_hash": exc.expected_hash,
                    "actual_hash": exc.actual_hash,
                },
            ) from exc
        except ConfigValidationError as exc:
            raise validation_error(exc) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/config/set")
    def session_config_set(session_id: str, request: ConfigSetRequest) -> dict[str, Any]:
        try:
            snapshot = manager().set_session_path(session_id, request.path, request.value)
            payload = snapshot.model_dump(mode="json")
            mark_pending(session_id, payload)
            return payload
        except ConfigValidationError as exc:
            raise validation_error(exc) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/profile")
    def set_session_profile(session_id: str, request: ProfileSetRequest) -> dict[str, Any]:
        try:
            snapshot = manager().set_session_profile(session_id, request.profile)
            payload = snapshot.model_dump(mode="json")
            mark_pending(session_id, payload)
            return payload
        except ConfigValidationError as exc:
            raise validation_error(exc) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/model")
    def set_session_model(session_id: str, request: ModelOverrideRequest) -> dict[str, Any]:
        try:
            snapshot = manager().set_session_model(session_id, request.model, provider_id=request.provider_id)
            handle = session_manager().get_active_handle(session_id)
            pending = bool(handle is not None and handle.is_busy())
            if handle is not None:
                setattr(handle.agent, "pending_config_effects", ["model:next_turn"] if pending else [])
            return {**snapshot.model_dump(mode="json"), "pending_next_turn": pending}
        except (FileNotFoundError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/debug/set")
    def set_debug(request: DebugSetRequest) -> dict[str, Any]:
        try:
            return manager().set_runtime_override(request.path, request.value, session_id=request.session_id).model_dump(mode="json")
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/tools")
    def session_tools(session_id: str) -> dict[str, Any]:
        try:
            handle = session_manager().get_handle(session_id)
            return active_tool_surface(handle.agent)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
