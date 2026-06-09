from __future__ import annotations

import hashlib
import math
from typing import Protocol


class AttachmentEmbeddingProvider(Protocol):
    """
    附件系统的 embedding provider 抽象。

    它负责把 attachment chunk 转换为向量表示，但不是检索的强依赖。
    当 provider 不可用或未配置时，AttachmentRetriever 会自动回退到关键词检索。
    这样 pp-Echo 可以在保持轻量教学向的同时，为后续 hybrid search 和 rerank
    留出扩展点。
    """

    def is_available(self) -> bool:
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class UnavailableEmbeddingProvider:
    """默认 embedding provider，占位但不可用，确保系统不会默认调用外部 API。"""

    def is_available(self) -> bool:
        return False

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("Attachment embedding provider is not configured.")


class DeterministicFakeEmbeddingProvider:
    """测试用本地 deterministic provider，不访问网络也不依赖向量数据库。"""

    def is_available(self) -> bool:
        return True

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_normalize(_hash_vector(text)) for text in texts]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """计算两个向量的余弦相似度，空向量时返回 0。"""

    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right)) or 1.0)


def _hash_vector(text: str, dims: int = 32) -> list[float]:
    digest = hashlib.sha256(text.lower().encode("utf-8")).digest()
    return [float(digest[index % len(digest)]) / 255.0 for index in range(dims)]


def _normalize(vector: list[float]) -> list[float]:
    length = math.sqrt(sum(item * item for item in vector)) or 1.0
    return [item / length for item in vector]
