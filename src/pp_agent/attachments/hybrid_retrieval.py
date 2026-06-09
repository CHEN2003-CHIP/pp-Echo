from __future__ import annotations

from pp_agent.attachments.embeddings import AttachmentEmbeddingProvider, cosine_similarity
from pp_agent.attachments.retrieval import search_chunks
from pp_agent.attachments.rerank import rerank_attachment_results
from pp_agent.attachments.schema import AttachmentChunk, AttachmentSearchResult


def hybrid_search_chunks(
    chunks: list[AttachmentChunk],
    query: str,
    *,
    top_k: int = 5,
    embedding_provider: AttachmentEmbeddingProvider,
) -> tuple[list[AttachmentSearchResult], dict[str, object]]:
    """
    执行 optional hybrid retrieval。

    关键词检索永远先运行；只有 embedding_provider 可用时才追加本地向量分支。
    函数返回结果和 trace metadata，调用方可以记录 fallback_reason 等审计字段。
    """

    keyword = search_chunks(chunks, query, top_k=max(top_k * 3, top_k))
    if not embedding_provider.is_available():
        chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        return rerank_attachment_results(keyword, chunks_by_id, query)[:top_k], {
            "search_mode": "keyword",
            "index_type": "keyword",
            "embedding_available": False,
            "fallback_reason": "embedding_provider_unavailable",
            "keyword_result_count": len(keyword),
            "vector_result_count": 0,
            "rerank_applied": True,
        }
    vector = _vector_results(chunks, query, embedding_provider=embedding_provider, top_k=max(top_k * 3, top_k))
    merged: dict[str, AttachmentSearchResult] = {item.chunk_id: item for item in keyword}
    for item in vector:
        existing = merged.get(item.chunk_id)
        if existing is None:
            merged[item.chunk_id] = item
        else:
            existing.score += item.score
            existing.match_type = "hybrid"
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    final = rerank_attachment_results(list(merged.values()), chunks_by_id, query)[:top_k]
    return final, {
        "search_mode": "hybrid",
        "index_type": "hybrid",
        "embedding_available": True,
        "fallback_reason": None,
        "keyword_result_count": len(keyword),
        "vector_result_count": len(vector),
        "rerank_applied": True,
    }


def _vector_results(chunks: list[AttachmentChunk], query: str, *, embedding_provider: AttachmentEmbeddingProvider, top_k: int) -> list[AttachmentSearchResult]:
    query_vector = embedding_provider.embed([query])[0]
    chunk_vectors = embedding_provider.embed([chunk.text for chunk in chunks])
    results: list[AttachmentSearchResult] = []
    for chunk, vector in zip(chunks, chunk_vectors):
        score = cosine_similarity(query_vector, vector)
        if score <= 0:
            continue
        results.append(
            AttachmentSearchResult(
                chunk_id=chunk.chunk_id,
                attachment_id=chunk.attachment_id,
                filename=chunk.filename,
                score=score,
                match_type="vector",
                snippet=chunk.text[:280],
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
                source_ref=chunk.source_ref,
                section_title=chunk.section_title,
            )
        )
    return sorted(results, key=lambda item: item.score, reverse=True)[:top_k]
