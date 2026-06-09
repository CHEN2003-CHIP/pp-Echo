from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from pp_agent.attachments.index import tokenize
from pp_agent.attachments.schema import AttachmentChunk, AttachmentSearchResult


def load_chunks(path: Path) -> list[AttachmentChunk]:
    """从 jsonl 文件加载 chunks，忽略空行并保持原始顺序。"""

    if not path.exists():
        return []
    return [AttachmentChunk.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_chunks(path: Path, chunks: Iterable[AttachmentChunk]) -> None:
    """把 chunks 以 jsonl 写入磁盘，方便按行流式读取和调试。"""

    path.write_text("\n".join(chunk.model_dump_json() for chunk in chunks), encoding="utf-8")


def search_chunks(chunks: list[AttachmentChunk], query: str, *, top_k: int = 5) -> list[AttachmentSearchResult]:
    """在 chunk 列表中执行轻量关键词检索，并返回来源范围和短 snippet。"""

    query_terms = tokenize(query)
    if not query_terms:
        return []
    results: list[AttachmentSearchResult] = []
    for chunk in chunks:
        haystack = " ".join([chunk.filename, " ".join(chunk.heading_path), chunk.text]).lower()
        score = 0.0
        for term in query_terms:
            count = haystack.count(term.lower())
            if count:
                score += count
        if chunk.heading_path and any(term in " ".join(chunk.heading_path).lower() for term in query_terms):
            score += 2.0
        if any(term in chunk.filename.lower() for term in query_terms):
            score += 1.5
        if score <= 0:
            continue
        results.append(
            AttachmentSearchResult(
                chunk_id=chunk.chunk_id,
                attachment_id=chunk.attachment_id,
                filename=chunk.filename,
                score=score,
                match_type="keyword",
                snippet=make_snippet(chunk.text, query_terms),
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
                source_ref=chunk.source_ref,
                section_title=chunk.section_title,
            )
        )
    return sorted(results, key=lambda item: item.score, reverse=True)[: max(1, min(20, top_k))]


def make_snippet(text: str, terms: list[str], limit: int = 280) -> str:
    """生成围绕第一个命中词的短片段，避免工具返回完整 chunk。"""

    lowered = text.lower()
    hit = min([lowered.find(term.lower()) for term in terms if lowered.find(term.lower()) >= 0] or [0])
    start = max(0, hit - limit // 3)
    snippet = re.sub(r"\s+", " ", text[start : start + limit]).strip()
    return snippet


def dump_index(path: Path, index: dict) -> None:
    """写入关键词索引 JSON，便于 inspect 和后续替换为 hybrid retrieval。"""

    path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
