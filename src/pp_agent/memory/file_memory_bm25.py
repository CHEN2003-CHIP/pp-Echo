from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from pp_agent.memory.file_memory_chunker import FileMemoryChunk


try:  # pragma: no cover - exercised when optional dependency is installed
    from rank_bm25 import BM25Okapi as _RankBM25Okapi
except ImportError:  # pragma: no cover - fallback is covered by local tests
    _RankBM25Okapi = None


_TOKEN_RE = re.compile(r"[A-Za-z0-9_./:\\-]+|[\u4e00-\u9fff]")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


@dataclass(frozen=True)
class BM25Hit:
    chunk_id: str
    score: float
    raw_score: float


class _FallbackBM25Okapi:
    def __init__(self, corpus: list[list[str]], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.corpus = corpus
        self.k1 = k1
        self.b = b
        self.doc_len = [len(doc) for doc in corpus]
        self.avgdl = sum(self.doc_len) / len(self.doc_len) if self.doc_len else 0.0
        self.term_freqs = [Counter(doc) for doc in corpus]
        dfs: Counter[str] = Counter()
        for doc in corpus:
            dfs.update(set(doc))
        n = len(corpus)
        self.idf = {
            term: math.log(1.0 + (n - df + 0.5) / (df + 0.5))
            for term, df in dfs.items()
        }

    def get_scores(self, query_tokens: list[str]) -> list[float]:
        scores: list[float] = []
        for index, term_freq in enumerate(self.term_freqs):
            score = 0.0
            doc_len = self.doc_len[index]
            for term in query_tokens:
                freq = term_freq.get(term, 0)
                if freq <= 0:
                    continue
                denom = freq + self.k1 * (1.0 - self.b + self.b * doc_len / (self.avgdl or 1.0))
                score += self.idf.get(term, 0.0) * (freq * (self.k1 + 1.0)) / denom
            scores.append(score)
        return scores


class FileMemoryBM25Index:
    def __init__(self, chunks: list[FileMemoryChunk]) -> None:
        self.chunks = list(chunks)
        self._tokens = [tokenize_file_memory_text(self._document_text(chunk)) for chunk in self.chunks]
        engine_cls = _RankBM25Okapi or _FallbackBM25Okapi
        self._engine = engine_cls(self._tokens) if self._tokens else None

    @property
    def is_available(self) -> bool:
        return bool(self.chunks) and self._engine is not None

    def search(self, query: str, *, limit: int) -> list[BM25Hit]:
        """BM25 search for a query string."""
        if not self.is_available or limit <= 0:
            return []
        query_tokens = tokenize_file_memory_text(query)
        if not query_tokens:
            return []
        raw_scores = [float(score) for score in self._engine.get_scores(query_tokens)]
        scored = [
            (chunk, raw)
            for chunk, raw in zip(self.chunks, raw_scores)
            if raw > 0.0
        ]
        if not scored:
            return []
        normalized = _normalize_scores([raw for _chunk, raw in scored])
        hits = [
            BM25Hit(chunk_id=chunk.chunk_id, score=score, raw_score=raw)
            for (chunk, raw), score in zip(scored, normalized)
        ]
        return sorted(hits, key=lambda item: (-item.score, -item.raw_score, item.chunk_id))[:limit]

    @staticmethod
    def _document_text(chunk: FileMemoryChunk) -> str:
        heading = " ".join(chunk.heading_path)
        return f"{chunk.path}\n{heading}\n{chunk.text}"


def tokenize_file_memory_text(text: str) -> list[str]:
    """转为BM25的token"""
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text or ""):
        token = raw.lower()
        if not token:
            continue
        tokens.append(token)
        if "/" in token or "\\" in token:
            tokens.extend(part for part in re.split(r"[\\/]+", token) if part)
        if "_" in token or "-" in token or "." in token or ":" in token:
            tokens.extend(part for part in re.split(r"[_\-.:]+", token) if part)
        if len(raw) > 2 and any(char.isupper() for char in raw[1:]):
            tokens.extend(part.lower() for part in _CAMEL_RE.split(raw) if part)
    deduped: list[str] = []
    seen_at_position: set[tuple[int, str]] = set()
    for index, token in enumerate(tokens):
        marker = (index, token)
        if marker in seen_at_position:
            continue
        seen_at_position.add(marker)
        deduped.append(token)
    return deduped


def _normalize_scores(raw_scores: list[float]) -> list[float]:
    if not raw_scores:
        return []
    minimum = min(raw_scores)
    maximum = max(raw_scores)
    if math.isclose(minimum, maximum):
        return [1.0 if score > 0 else 0.0 for score in raw_scores]
    return [(score - minimum) / (maximum - minimum) for score in raw_scores]
