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


def test_stream_chat_tolerates_empty_choice_chunks(monkeypatch) -> None:
    payload = '\n'.join(
        [
            'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}',
            'data: {"choices":[]}',
            'data: {"usage":{"total_tokens":12},"choices":[]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            'data: [DONE]',
        ]
    )

    monkeypatch.setenv("PP_AGENT_API_KEY", "test-key")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=payload)))
    llm = LLMClient(client=client)

    events = list(llm.stream_chat([ChatMessage(role="user", content=[TextPart(text="hi")], timestamp=0.0)]))

    assert "".join(event["text"] for event in events) == "Hi"
    assert events[1]["tool_calls"] == []
    assert events[1]["finish_reason"] is None


def test_stream_chat_preserves_tool_call_index(monkeypatch) -> None:
    payload = '\n'.join(
        [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"id":"call-2","function":{"name":"list_files","arguments":"{\\"path\\":\\"src\\"}"}}]},"finish_reason":"tool_calls"}]}',
            'data: [DONE]',
        ]
    )

    monkeypatch.setenv("PP_AGENT_API_KEY", "test-key")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=payload)))
    llm = LLMClient(client=client)

    events = list(llm.stream_chat([ChatMessage(role="user", content=[TextPart(text="hi")], timestamp=0.0)]))

    assert events[0]["tool_calls"][0]["index"] == 1


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


def test_default_client_trusts_environment(monkeypatch) -> None:
    monkeypatch.delenv("PP_AGENT_HTTP_TRUST_ENV", raising=False)

    llm = LLMClient()

    assert llm._client.trust_env is True


def test_default_client_can_ignore_environment(monkeypatch) -> None:
    monkeypatch.setenv("PP_AGENT_HTTP_TRUST_ENV", "0")

    llm = LLMClient()

    assert llm._client.trust_env is False
