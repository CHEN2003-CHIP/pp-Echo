from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any, Optional

import httpx

from pp_agent.domain import ChatMessage, ContentPart, TextPart, ToolCallPart
from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.llm.provider.base import BaseLLMClient, LLMClientError


class LLMClient(BaseLLMClient):
    """"""
    def __init__(
        self,
        provider: Optional[ProviderConfig] = None,
        model: Optional[ModelConfig] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(
            provider=provider or ProviderConfig(base_url=os.getenv("PP_AGENT_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")),
            model=model or ModelConfig(model=os.getenv("PP_AGENT_MODEL", "qwen3.5-plus")),
        )
        self._client = client or httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0))

    def stream_chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> Iterator[dict[str, Any]]:
        """流式输出"""
        api_key = os.getenv(self.provider.api_key_env)
        if not api_key:
            raise LLMClientError(f"Missing API key in environment variable: {self.provider.api_key_env}")

        payload: dict[str, Any] = {
            "model": self.model.model,
            "messages": [self._serialize_message(message) for message in messages],
            "stream": True,
            "temperature": self.model.temperature,
            "enable_thinking": self.model.enable_thinking,
        }
        if self.model.max_tokens is not None:
            payload["max_tokens"] = self.model.max_tokens
        if tools:
            payload["tools"] = tools

        try:
            with self._client.stream(
                "POST",
                f"{self.provider.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise LLMClientError(f"Invalid SSE payload: {data}") from exc
                    yield self._normalize_chunk(chunk)
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip() or str(exc)
            raise LLMClientError(f"LLM request failed with status {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise LLMClientError(f"LLM request failed: {exc}") from exc

    def _serialize_message(self, message: ChatMessage) -> dict[str, Any]:
        if message.role == "tool":
            return {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": self._text_content(message.content),
            }

        content = self._text_content(message.content)
        payload: dict[str, Any] = {
            "role": message.role,
            "content": content,
        }
        tool_calls = [
            {
                "id": part.id,
                "type": "function",
                "function": {
                    "name": part.name,
                    "arguments": json.dumps(part.arguments, ensure_ascii=False),
                },
            }
            for part in message.content
            if isinstance(part, ToolCallPart)
        ]
        if tool_calls:
            payload["tool_calls"] = tool_calls
        return payload

    @staticmethod
    def _text_content(parts: list[ContentPart]) -> str:
        return "".join(part.text for part in parts if isinstance(part, TextPart))

    @staticmethod
    def _normalize_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
        """大模型流式响应标准化工具方法"""
        choice = chunk.get("choices", [{}])[0]
        delta = choice.get("delta", {})
        normalized: dict[str, Any] = {
            "text": delta.get("content", ""),
            "tool_calls": [],
            "finish_reason": choice.get("finish_reason"),
            "raw": chunk,
        }
        for tool_call in delta.get("tool_calls", []) or []:
            function = tool_call.get("function", {})
            normalized["tool_calls"].append(
                {
                    "id": tool_call.get("id"),
                    "name": function.get("name"),
                    "arguments_chunk": function.get("arguments", ""),
                }
            )
        return normalized
