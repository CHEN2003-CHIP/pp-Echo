from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from pp_agent.config import ConfigConflictError, ConfigValidationError, get_config_manager
from pp_agent.llm.connectivity import ModelConnectivityService
from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.llm.providers import list_provider_presets, provider_preset


class ModelTestRequest(BaseModel):
    provider: Optional[dict[str, Any]] = None
    model: Optional[dict[str, Any]] = None
    prompt: str = "Reply with OK."
    max_tokens: int = 8


class ApplyProviderPresetRequest(BaseModel):
    provider_id: str
    model: Optional[str] = None
    base_hash: Optional[str] = None


def mount_model_routes(app, active_workspace) -> None:
    from fastapi import HTTPException

    def current_settings():
        return get_config_manager(active_workspace()).get_effective_snapshot().settings

    @app.get("/api/models/providers")
    def model_providers() -> dict[str, Any]:
        return {"providers": [preset.model_dump(mode="json") for preset in list_provider_presets()]}

    @app.post("/api/models/test")
    def model_test(request: ModelTestRequest) -> dict[str, Any]:
        settings = current_settings()
        provider_payload = request.provider or settings.provider.model_dump(mode="python")
        model_payload = request.model or settings.model.model_dump(mode="python")
        result = ModelConnectivityService().test(
            ProviderConfig(**provider_payload),
            ModelConfig(**model_payload),
            prompt=request.prompt,
            max_tokens=max(1, min(request.max_tokens, 32)),
        )
        return result.model_dump(mode="json")

    @app.post("/api/models/apply-preset")
    def apply_provider_preset(request: ApplyProviderPresetRequest) -> dict[str, Any]:
        preset = provider_preset(request.provider_id)
        model_name = request.model or (preset.recommended_models[0] if preset.recommended_models else "")
        patch = {
            "provider": {
                "name": preset.id,
                "base_url": preset.default_base_url,
                "api_key_env": preset.default_api_key_env,
            },
            "model": {
                "provider": preset.id,
                "model": model_name,
            },
        }
        try:
            return get_config_manager(active_workspace()).patch_project_config(patch, base_hash=request.base_hash).model_dump(mode="json")
        except ConfigConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={"message": str(exc), "expected_hash": exc.expected_hash, "actual_hash": exc.actual_hash},
            ) from exc
        except ConfigValidationError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "errors": exc.errors}) from exc
