from __future__ import annotations

from pydantic import BaseModel


class MemorySettings(BaseModel):
    enable: bool = False
    backend: str = "sqlite"
    sqlite_path: str = ""
    chunk_target_tokens: int = 350
    chunk_max_tokens: int = 420
    sqlite_busy_timeout_ms: int = 5000
    embedding_enable: bool = False
    embedding_provider: str = "dashscope"
    embedding_model: str = "multimodal-embedding-v1"
    dashscope_api_key_env: str = "DASHSCOPE_API_KEY"
    embedding_batch_size: int = 16
    vector_enable: bool = False
    vector_backend: str = "chroma"
    chroma_path: str = ""
    chroma_collection: str = "pp_agent_history"
    chroma_collection_per_embedding: bool = True
    indexing_enable: bool = False
    indexing_batch_size: int = 100
    retrieval_enable: bool = False
    retrieval_limit: int = 6
    retrieval_same_session_bias: float = 1.0
    retrieval_max_per_session: int = 2
    retrieval_max_snippets: int = 4
    retrieval_max_chars: int = 1600
    hybrid_enable: bool = False
    hybrid_keyword_limit: int = 12
    hybrid_vector_limit: int = 12
    recent_dedup_enable: bool = True
    recent_dedup_use_chunk_metadata: bool = True
    snippet_categorize_enable: bool = True
    reranker_enable: bool = False
    reranker_backend: str = "lightweight"
    reranker_limit: int = 8
    snippet_prioritize_long_term_preferences: bool = True
    snippet_compress_error_stacks: bool = True
    snippet_path_weight_boost: float = 1.0
