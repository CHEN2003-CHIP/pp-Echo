from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any, Optional

from pp_agent.domain import ChatMessage
from pp_agent.llm.models import ModelConfig, ProviderConfig


class LLMClientError(RuntimeError):
    pass


class BaseLLMClient(ABC):
    def __init__(
        self,
        provider: Optional[ProviderConfig] = None,
        model: Optional[ModelConfig] = None,
    ) -> None:
        self.provider = provider or ProviderConfig()
        self.model = model or ModelConfig()

    @abstractmethod
    def stream_chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> Iterator[dict[str, Any]]:
        raise NotImplementedError
