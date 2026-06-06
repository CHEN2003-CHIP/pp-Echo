from __future__ import annotations

import logging

from pp_agent.memory.embedding import EmbeddingProvider
from pp_agent.memory.sqlite_store import SQLiteHistoryStore
from pp_agent.memory.types import IndexedChunk, IndexingSummary
from pp_agent.memory.vector_index import VectorIndex


logger = logging.getLogger(__name__)


class MemoryIndexPipeline:
    """
    memory chunks 的向量索引流水线。

    它从 SQLiteHistoryStore 中读取 pending chunks，
    调用 EmbeddingProvider 生成 embedding，
    再把 IndexedChunk 写入 VectorIndex，
    最后回写 SQLite 标记 embedded / indexed / failed 状态。

    它只负责索引，不负责：
    - 原始消息持久化；
    - chunk 切分；
    - 历史检索；
    - recall prompt 构造。

    Runtime 一轮结束后，AsyncMemoryIndexScheduler 会在后台调用
    index_pending_chunks()，让向量索引异步补齐，
    避免 embedding 阻塞 Agent 主循环。
    """
    def __init__(
        self,
        *,
        store: SQLiteHistoryStore,
        embedding_provider: EmbeddingProvider,
        vector_index: VectorIndex,
        embedding_batch_size: int = 16,
        indexing_batch_size: int = 100,
    ) -> None:
        self.store = store
        self.embedding_provider = embedding_provider
        self.vector_index = vector_index
        self.embedding_batch_size = max(1, embedding_batch_size)
        self.indexing_batch_size = max(1, indexing_batch_size)

    def index_pending_chunks(self, *, limit: int = 100) -> IndexingSummary:
        if not self.embedding_provider.is_enabled() or not self.vector_index.is_enabled():
            logger.debug("Memory indexing pipeline skipped because embedding or vector index is disabled")
            return IndexingSummary()
        pending = self.store.list_pending_chunks(limit=min(limit, self.indexing_batch_size))
        return self._index_records(pending)

    def rebuild_index_for_session(self, session_id: str) -> IndexingSummary:
        if not self.embedding_provider.is_enabled() or not self.vector_index.is_enabled():
            logger.debug("Memory rebuild skipped because embedding or vector index is disabled")
            return IndexingSummary()
        records = self.store.list_chunks_for_session(session_id=session_id)
        return self._index_records(records)

    def _index_records(self, records) -> IndexingSummary:
        """把一批 memory chunk 做向量化并写入向量索引，同时把处理状态回写到数据库。"""
        summary = IndexingSummary(scanned=len(records))
        if not records:
            return summary
        for start in range(0, len(records), self.embedding_batch_size):
            batch = records[start : start + self.embedding_batch_size]
            try:
                embeddings = self.embedding_provider.embed_texts([record.text for record in batch])
                indexed_chunks: list[IndexedChunk] = []
                for record, embedding in zip(batch, embeddings):
                    self.store.mark_chunk_embedded(
                        chunk_id=record.id,
                        embedding_model=self.embedding_provider.model_name(),
                        embedding_dim=len(embedding),
                    )
                    summary = summary.combine(IndexingSummary(embedded=1))
                    metadata = dict(record.metadata or {})
                    role = str(metadata.get("role") or record.source_kind)
                    indexed_chunks.append(
                        IndexedChunk(
                            chunk_id=record.id,
                            message_id=record.message_id,
                            session_id=record.session_id,
                            turn_id=record.turn_id,
                            role=role,
                            source_kind=record.source_kind,
                            text=record.text,
                            created_at=record.created_at,
                            embedding=embedding,
                            embedding_model=self.embedding_provider.model_name(),
                            metadata=metadata,
                        )
                    )
                upserted_ids = self.vector_index.upsert_chunks(indexed_chunks)
                for chunk_id in upserted_ids:
                    self.store.mark_chunk_indexed(chunk_id=chunk_id, vector_ref=chunk_id)
                    summary = summary.combine(IndexingSummary(indexed=1))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Memory indexing batch failed: %s", exc)
                for record in batch:
                    self.store.mark_chunk_failed(chunk_id=record.id, error=str(exc))
                    summary = summary.combine(IndexingSummary(failed=1))
        return summary
