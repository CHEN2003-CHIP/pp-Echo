from __future__ import annotations

import re
from collections import Counter
from typing import Any

from pp_agent.attachments.schema import AttachmentChunk


def tokenize(text: str) -> list[str]:
    """生成简单关键词 token，英文按词切分，中文连续字符用 bigram 增强。"""

    lowered = text.lower()
    words = re.findall(r"[a-z0-9_]+", lowered)
    cjk = re.findall(r"[\u4e00-\u9fff]+", lowered)
    bigrams: list[str] = []
    for block in cjk:
        bigrams.extend(block[index : index + 2] for index in range(max(0, len(block) - 1)))
        if len(block) == 1:
            bigrams.append(block)
    return words + bigrams


def build_keyword_index(chunks: list[AttachmentChunk]) -> dict[str, Any]:
    """为 chunk 构建轻量本地关键词索引，第一版不依赖 embedding 或向量数据库。"""

    documents: list[dict[str, Any]] = []
    for chunk in chunks:
        terms = Counter(tokenize(" ".join([chunk.filename, " ".join(chunk.heading_path), chunk.text])))
        documents.append({"chunk_id": chunk.chunk_id, "terms": dict(terms), "length": sum(terms.values())})
    return {"index_type": "keyword", "document_count": len(documents), "documents": documents}
