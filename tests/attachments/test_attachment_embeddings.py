import pytest

from pp_agent.attachments.embeddings import DeterministicFakeEmbeddingProvider, UnavailableEmbeddingProvider


def test_unavailable_embedding_provider_fails_closed() -> None:
    provider = UnavailableEmbeddingProvider()

    assert provider.is_available() is False
    with pytest.raises(RuntimeError):
        provider.embed(["hello"])


def test_fake_embedding_provider_is_deterministic() -> None:
    provider = DeterministicFakeEmbeddingProvider()

    assert provider.is_available() is True
    assert provider.embed(["approval"]) == provider.embed(["approval"])
