from __future__ import annotations

import os
import time
from typing import Any, Protocol

import httpx


_DASHSCOPE_COMPATIBLE_EMBEDDINGS_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
_DASHSCOPE_MULTIMODAL_EMBEDDINGS_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)
_DASHSCOPE_MULTIMODAL_MODEL_PREFIXES = (
    "multimodal-embedding-",
    "qwen3-vl-embedding",
    "qwen2.5-vl-embedding",
    "tongyi-embedding-vision-",
)


class EmbeddingProvider(Protocol):
    def is_enabled(self) -> bool:
        ...

    def model_name(self) -> str:
        ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class NoopEmbeddingProvider:
    def is_enabled(self) -> bool:
        return False

    def model_name(self) -> str:
        return "noop"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class DashScopeEmbeddingProvider:
    def __init__(
        self,
        *,
        api_key_env: str = "DASHSCOPE_API_KEY",
        model: str = "multimodal-embedding-v1",
        base_url: str | None = None,
        max_retries: int = 2,
        timeout_seconds: float = 30.0,
        client_factory=None,
    ) -> None:
        self.api_key_env = api_key_env
        self._model = model
        self.base_url = base_url or self._default_base_url_for_model(model)
        self.max_retries = max(1, max_retries)
        self.timeout_seconds = timeout_seconds
        # DashScope calls should bypass ambient proxy settings by default.
        # In local Windows environments, inherited proxy/TLS interception can
        # break httpx while direct HTTPS requests still succeed.
        self._client_factory = client_factory or (lambda: httpx.Client(timeout=self.timeout_seconds, trust_env=False))

    def is_enabled(self) -> bool:
        return bool(os.getenv(self.api_key_env))

    def model_name(self) -> str:
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing DashScope API key in env var {self.api_key_env}")
        payload = self._build_payload(texts)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with self._client_factory() as client:
                    response = client.post(self.base_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                items = self._extract_embedding_items(data)
                if len(items) != len(texts):
                    raise RuntimeError(f"Expected {len(texts)} embeddings, got {len(items)}")
                return [list(item.get("embedding") or []) for item in items]
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(0.2 * attempt)
        raise RuntimeError(f"DashScope embedding failed: {last_error}") from last_error

    @staticmethod
    def _default_base_url_for_model(model: str) -> str:
        if _is_multimodal_embedding_model(model):
            return _DASHSCOPE_MULTIMODAL_EMBEDDINGS_URL
        return _DASHSCOPE_COMPATIBLE_EMBEDDINGS_URL

    def _build_payload(self, texts: list[str]) -> dict[str, Any]:
        if _is_multimodal_embedding_model(self._model):
            return {
                "model": self._model,
                "input": {
                    "contents": [{"text": text} for text in texts],
                },
            }
        return {
            "model": self._model,
            "input": texts,
            "encoding_format": "float",
            "input_type": "document",
            "modalities": ["text"],
        }

    def _extract_embedding_items(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(data.get("data"), list):
            return list(data["data"])
        output = data.get("output")
        if isinstance(output, dict) and isinstance(output.get("embeddings"), list):
            return list(output["embeddings"])
        if isinstance(data.get("embeddings"), list):
            return list(data["embeddings"])
        return []


def _is_multimodal_embedding_model(model: str) -> bool:
    normalized = (model or "").strip().lower()
    return any(normalized.startswith(prefix) for prefix in _DASHSCOPE_MULTIMODAL_MODEL_PREFIXES)
