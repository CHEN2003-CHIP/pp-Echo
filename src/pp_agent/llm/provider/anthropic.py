from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any, Optional

import httpx

from pp_agent.domain import ChatMessage, ContentPart, TextPart
from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.llm.provider.base import BaseLLMClient, LLMClientError


class AnthropicLLMClient(BaseLLMClient):
    """Minimal Anthropic Messages API adapter for text chat streaming."""

    def __init__(
        self,
        provider: Optional[ProviderConfig] = None,
        model: Optional[ModelConfig] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(
            provider=provider or ProviderConfig(name="anthropic", base_url="https://api.anthropic.com/v1", api_key_env="ANTHROPIC_API_KEY"),
            model=model or ModelConfig(provider="anthropic", model="claude-3-5-sonnet-latest"),
        )
        self._client = client or httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0))

    def stream_chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> Iterator[dict[str, Any]]:
        if tools:
            raise LLMClientError("Anthropic tool calling is not enabled in this lightweight adapter.")
        api_key = os.getenv(self.provider.api_key_env)
        if not api_key:
            raise LLMClientError(f"Missing API key in environment variable: {self.provider.api_key_env}")
        system, payload_messages = self._serialize_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model.model,
            "messages": payload_messages,
            "stream": True,
            "max_tokens": self.model.max_tokens or 4096,
            "temperature": self.model.temperature,
        }
        if system:
            payload["system"] = system
        try:
            with self._client.stream(
                "POST",
                f"{self.provider.base_url.rstrip('/')}/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            ) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise LLMClientError(f"Anthropic request failed with status {response.status_code}: {response.text[:800]}") from exc
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise LLMClientError(f"Invalid Anthropic SSE payload: {data}") from exc
                    normalized = self._normalize_chunk(chunk)
                    if normalized is not None:
                        yield normalized
        except httpx.HTTPError as exc:
            raise LLMClientError(f"Anthropic request failed: {exc}") from exc

    def _serialize_messages(self, messages: list[ChatMessage]) -> tuple[str, list[dict[str, str]]]:
        system_parts: list[str] = []
        result: list[dict[str, str]] = []
        for message in messages:
            text = self._text_content(message.content)
            if not text:
                continue
            if message.role == "system":
                system_parts.append(text)
            elif message.role in {"user", "assistant"}:
                result.append({"role": message.role, "content": text})
        return "\n\n".join(system_parts), result

    @staticmethod
    def _text_content(parts: list[ContentPart]) -> str:
        return "".join(part.text for part in parts if isinstance(part, TextPart))

    @staticmethod
    def _normalize_chunk(chunk: dict[str, Any]) -> Optional[dict[str, Any]]:
        if chunk.get("type") == "content_block_delta":
            delta = chunk.get("delta") or {}
            return {"text": delta.get("text", ""), "tool_calls": [], "finish_reason": None, "usage": None, "request_id": None, "raw": chunk}
        if chunk.get("type") == "message_delta":
            delta = chunk.get("delta") or {}
            return {"text": "", "tool_calls": [], "finish_reason": delta.get("stop_reason"), "usage": chunk.get("usage"), "request_id": None, "raw": chunk}
        return None
