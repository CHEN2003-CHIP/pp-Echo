from importlib import import_module

_MODULE_MAP = {
    "MemorySettings": "pp_agent.memory.config",
    "DashScopeEmbeddingProvider": "pp_agent.memory.embedding",
    "EmbeddingProvider": "pp_agent.memory.embedding",
    "NoopEmbeddingProvider": "pp_agent.memory.embedding",
    "HistoryIndexer": "pp_agent.memory.indexer",
    "MemoryIndexPipeline": "pp_agent.memory.index_pipeline",
    "MemoryProvider": "pp_agent.memory.provider",
    "NoopMemoryProvider": "pp_agent.memory.provider",
    "SQLiteMemoryProvider": "pp_agent.memory.provider",
    "RecallSnippetBuilder": "pp_agent.memory.recall_builder",
    "LightweightReranker": "pp_agent.memory.reranker",
    "NoopReranker": "pp_agent.memory.reranker",
    "Reranker": "pp_agent.memory.reranker",
    "HistoryRetriever": "pp_agent.memory.retrieval",
    "RetrievedChunk": "pp_agent.memory.retrieval",
    "RetrievedMessage": "pp_agent.memory.retrieval",
    "RetrievalRequest": "pp_agent.memory.retrieval",
    "RetrievalResult": "pp_agent.memory.retrieval",
    "MemoryRetrievalHook": "pp_agent.memory.retrieval_hook",
    "SQLiteHistoryStore": "pp_agent.memory.sqlite_store",
    "HistoryStore": "pp_agent.memory.store",
    "HistoryChunkInput": "pp_agent.memory.types",
    "HistoryChunkRecord": "pp_agent.memory.types",
    "HistoryMessageRecord": "pp_agent.memory.types",
    "IndexedChunk": "pp_agent.memory.types",
    "IndexingSummary": "pp_agent.memory.types",
    "VectorQueryResult": "pp_agent.memory.types",
    "ChromaVectorIndex": "pp_agent.memory.vector_index",
    "NoopVectorIndex": "pp_agent.memory.vector_index",
    "VectorIndex": "pp_agent.memory.vector_index",
}

__all__ = list(_MODULE_MAP)


def __getattr__(name: str):
    module_name = _MODULE_MAP.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name)
    return getattr(module, name)
