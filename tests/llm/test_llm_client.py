import json

import httpx
import pytest

from agent_core.llm.client import LLMClient, LLMClientError
from agent_core.types import ChatMessage, TextPart


def test_stream_chat_parses_sse(monkeypatch) -> None:
    payload = '\n'.join(
        [
            'data: {"choices":[{"delta":{"content":"Hel"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}',
            'data: [DONE]',
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "qwen3.5-plus"
        assert body["enable_thinking"] is False
        return httpx.Response(200, text=payload)

    monkeypatch.setenv("PP_AGENT_API_KEY", "test-key")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    llm = LLMClient(client=client)
    events = list(
        llm.stream_chat(
            [ChatMessage(role="user", content=[TextPart(text="hi")], timestamp=0.0)],
            tools=[],
        )
    )

    assert "".join(event["text"] for event in events) == "Hello"


def test_stream_chat_raises_on_invalid_sse(monkeypatch) -> None:
    payload = '\n'.join(['data: not-json', 'data: [DONE]'])

    monkeypatch.setenv("PP_AGENT_API_KEY", "test-key")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=payload)))
    llm = LLMClient(client=client)

    with pytest.raises(LLMClientError):
        list(llm.stream_chat([ChatMessage(role="user", content=[TextPart(text="hi")], timestamp=0.0)]))


def test_stream_chat_raises_on_http_error(monkeypatch) -> None:
    monkeypatch.setenv("PP_AGENT_API_KEY", "test-key")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(400, text="bad request")))
    llm = LLMClient(client=client)

    with pytest.raises(LLMClientError):
        list(llm.stream_chat([ChatMessage(role="user", content=[TextPart(text="hi")], timestamp=0.0)]))