from __future__ import annotations

import os
from typing import Any, Optional

from pydantic import BaseModel

from pp_agent.config import ConfigConflictError, ConfigValidationError, get_config_manager
from pp_agent.llm.connectivity import ModelConnectivityService
from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.llm.providers import list_provider_presets, provider_preset
from pp_agent.observability.store import TraceStore


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

    @app.get("/api/models/usage")
    def model_usage(limit: int = 200) -> dict[str, Any]:
        settings = current_settings()
        current_provider = settings.provider.name or settings.model.provider
        current_model = settings.model.model
        usage: dict[tuple[str, str], dict[str, Any]] = {}
        for preset in list_provider_presets():
            for model_name in preset.recommended_models:
                usage[(preset.id, model_name)] = _usage_row(
                    preset_id=preset.id,
                    provider_label=preset.label,
                    model_name=model_name,
                    base_url=preset.default_base_url,
                    api_key_env=preset.default_api_key_env,
                    current_provider=current_provider,
                    current_model=current_model,
                )
        for summary in TraceStore(active_workspace()).list_runs(limit=max(1, min(500, int(limit)))):
            provider_id = summary.provider or "unknown"
            model_name = summary.model or "unknown"
            key = (provider_id, model_name)
            if key not in usage:
                usage[key] = _usage_row(
                    preset_id=provider_id,
                    provider_label=provider_id,
                    model_name=model_name,
                    base_url="",
                    api_key_env="",
                    current_provider=current_provider,
                    current_model=current_model,
                )
            row = usage[key]
            row["runs"] += 1
            row["llm_calls"] += summary.llm_calls
            row["input_tokens"] += summary.total_input_tokens
            row["output_tokens"] += summary.total_output_tokens
            row["total_tokens"] += summary.total_tokens
            if summary.total_cost_usd is not None:
                row["total_cost_usd"] = round(float(row["total_cost_usd"] or 0.0) + float(summary.total_cost_usd), 8)
        return {"models": list(usage.values())}

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


def _usage_row(
    *,
    preset_id: str,
    provider_label: str,
    model_name: str,
    base_url: str,
    api_key_env: str,
    current_provider: str,
    current_model: str,
) -> dict[str, Any]:
    return {
        "provider_id": preset_id,
        "provider_label": provider_label,
        "model": model_name,
        "base_url": base_url,
        "api_key_env": api_key_env,
        "api_key_configured": bool(api_key_env and os.getenv(api_key_env)),
        "current": preset_id == current_provider and model_name == current_model,
        "runs": 0,
        "llm_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "total_cost_usd": None,
    }
