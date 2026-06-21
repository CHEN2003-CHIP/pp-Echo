from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel

from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.llm.providers import provider_preset


class ModelConnectivityResult(BaseModel):
    """Structured result for explicit model connection tests."""

    provider: str
    model: str
    base_url: str
    api_key_env: str
    status: str
    latency_ms: Optional[int] = None
    message: str
    retryable: bool = False
    safe_detail: str = ""


class ModelConnectivityService:
    """Runs low-token, explicit connectivity probes without exposing API keys."""

    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        self._client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=8.0))

    def test(
        self,
        provider: ProviderConfig,
        model: ModelConfig,
        *,
        prompt: str = "Reply with OK.",
        max_tokens: int = 8,
    ) -> ModelConnectivityResult:
        preset = provider_preset(provider.name or model.provider)
        base_url = (provider.base_url or preset.default_base_url or "").rstrip("/")
        api_key_env = provider.api_key_env or preset.default_api_key_env
        model_name = model.model or (preset.recommended_models[0] if preset.recommended_models else "")
        if not model_name:
            return self._warning(provider.name, model_name, base_url, api_key_env, "No model is configured.")
        if not base_url:
            return self._warning(provider.name, model_name, base_url, api_key_env, "No base URL is configured.")
        api_key = os.getenv(api_key_env)
        if not api_key:
            return self._warning(provider.name, model_name, base_url, api_key_env, "Missing API key environment variable.")

        started = time.perf_counter()
        try:
            if preset.protocol == "anthropic":
                response = self._client.post(
                    f"{base_url}/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={"model": model_name, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]},
                )
            else:
                response = self._client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model_name, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "stream": False},
                )
            latency_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                return ModelConnectivityResult(
                    provider=provider.name,
                    model=model_name,
                    base_url=base_url,
                    api_key_env=api_key_env,
                    status="error",
                    latency_ms=latency_ms,
                    message=f"Model connection failed with HTTP {response.status_code}.",
                    retryable=response.status_code in {408, 409, 425, 429, 500, 502, 503, 504},
                    safe_detail=self._safe_response_text(response),
                )
            return ModelConnectivityResult(
                provider=provider.name,
                model=model_name,
                base_url=base_url,
                api_key_env=api_key_env,
                status="ok",
                latency_ms=latency_ms,
                message="Model connection succeeded.",
                safe_detail=self._safe_success(response),
            )
        except httpx.TimeoutException as exc:
            return self._error(provider.name, model_name, base_url, api_key_env, "Model connection timed out.", str(exc), retryable=True)
        except httpx.HTTPError as exc:
            return self._error(provider.name, model_name, base_url, api_key_env, "Model connection request failed.", str(exc), retryable=True)

    @staticmethod
    def _warning(provider: str, model: str, base_url: str, api_key_env: str, message: str) -> ModelConnectivityResult:
        return ModelConnectivityResult(provider=provider, model=model, base_url=base_url, api_key_env=api_key_env, status="warning", message=message)

    @staticmethod
    def _error(provider: str, model: str, base_url: str, api_key_env: str, message: str, detail: str, *, retryable: bool) -> ModelConnectivityResult:
        return ModelConnectivityResult(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
            status="error",
            message=message,
            retryable=retryable,
            safe_detail=detail[:500],
        )

    @staticmethod
    def _safe_response_text(response: httpx.Response) -> str:
        text = response.text.strip()
        return text[:800]

    @staticmethod
    def _safe_success(response: httpx.Response) -> str:
        try:
            payload: Dict[str, Any] = response.json()
        except ValueError:
            return "Provider returned a non-JSON success response."
        if "id" in payload:
            return f"request id: {payload.get('id')}"
        return "Provider returned a success response."
