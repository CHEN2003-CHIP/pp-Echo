import os

from pp_agent.memory.embedding import DashScopeEmbeddingProvider


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payloads, seen_requests):
        self._payloads = payloads
        self._seen_requests = seen_requests

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, headers=None, json=None):
        self._seen_requests.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse(self._payloads.pop(0))


def test_dashscope_embedding_provider_batches_texts(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    seen_requests = []
    payloads = [
        {
            "output": {
                "embeddings": [
                    {"embedding": [0.1, 0.2, 0.3]},
                    {"embedding": [0.4, 0.5, 0.6]},
                ]
            }
        }
    ]
    provider = DashScopeEmbeddingProvider(
        client_factory=lambda: _FakeClient(payloads, seen_requests),
        model="multimodal-embedding-v1",
    )

    embeddings = provider.embed_texts(["hello", "world"])

    assert provider.is_enabled() is True
    assert provider.model_name() == "multimodal-embedding-v1"
    assert embeddings == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert len(seen_requests) == 1
    assert seen_requests[0]["url"].endswith("/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding")
    assert seen_requests[0]["json"]["input"] == {
        "contents": [
            {"text": "hello"},
            {"text": "world"},
        ]
    }
    assert seen_requests[0]["json"]["model"] == "multimodal-embedding-v1"
    assert seen_requests[0]["headers"]["Authorization"] == "Bearer test-key"

    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)


def test_dashscope_embedding_provider_uses_compatible_endpoint_for_text_models(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    seen_requests = []
    payloads = [
        {
            "data": [
                {"embedding": [0.1, 0.2, 0.3]},
                {"embedding": [0.4, 0.5, 0.6]},
            ]
        }
    ]
    provider = DashScopeEmbeddingProvider(
        client_factory=lambda: _FakeClient(payloads, seen_requests),
        model="text-embedding-v4",
    )

    embeddings = provider.embed_texts(["hello", "world"])

    assert embeddings == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert len(seen_requests) == 1
    assert seen_requests[0]["url"].endswith("/compatible-mode/v1/embeddings")
    assert seen_requests[0]["json"]["input"] == ["hello", "world"]
    assert seen_requests[0]["json"]["model"] == "text-embedding-v4"

    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)


def test_dashscope_embedding_provider_uses_multimodal_endpoint_for_qwen3_vl(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    seen_requests = []
    payloads = [
        {
            "output": {
                "embeddings": [
                    {"embedding": [0.1, 0.2, 0.3]},
                ]
            }
        }
    ]
    provider = DashScopeEmbeddingProvider(
        client_factory=lambda: _FakeClient(payloads, seen_requests),
        model="qwen3-vl-embedding",
    )

    embeddings = provider.embed_texts(["hello"])

    assert embeddings == [[0.1, 0.2, 0.3]]
    assert len(seen_requests) == 1
    assert seen_requests[0]["url"].endswith("/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding")
    assert seen_requests[0]["json"]["input"] == {"contents": [{"text": "hello"}]}
    assert seen_requests[0]["json"]["model"] == "qwen3-vl-embedding"

    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
