from __future__ import annotations

import re

from pp_agent.attachments.schema import AttachmentChunk, AttachmentSearchResult


def rerank_attachment_results(results: list[AttachmentSearchResult], chunks_by_id: dict[str, AttachmentChunk], query: str) -> list[AttachmentSearchResult]:
    """使用轻量规则提升精确短 chunk、heading/source_ref 和 symbol 命中的排序。"""

    terms = [term.lower() for term in re.findall(r"[\w.-]+", query)]
    phrase = query.lower().strip()
    reranked: list[AttachmentSearchResult] = []
    for result in results:
        chunk = chunks_by_id.get(result.chunk_id)
        if chunk is None:
            reranked.append(result)
            continue
        haystack = " ".join([chunk.text, chunk.filename, chunk.source_ref or "", " ".join(chunk.heading_path), str(chunk.metadata.get("outline_hits") or "")]).lower()
        boost = 0.0
        if phrase and phrase in haystack:
            boost += 3.0
        if terms:
            boost += 1.5 * (sum(1 for term in terms if term in haystack) / len(terms))
        if chunk.heading_path or chunk.source_ref:
            boost += 0.5
        if chunk.metadata.get("outline_hits"):
            boost += 0.75
        if len(chunk.text) < 1200:
            boost += 0.25
        result.score += boost
        reranked.append(result)
    return sorted(reranked, key=lambda item: item.score, reverse=True)
