from __future__ import annotations

from pydantic import BaseModel, Field


class CoreMemoryBudgetSettings(BaseModel):
    user_profile_chars: int = 1200
    project_profile_chars: int = 2000
    agent_notes_chars: int = 1500
    total_chars: int = 4000


class CoreMemoryFeatureToggle(BaseModel):
    enabled: bool = True


class CoreMemoryAutomationSettings(BaseModel):
    enabled: bool = True
    use_llm_summary: bool = False
    llm_summary_model: str = ""
    max_merge_group_size: int = 8
    max_compaction_group_size: int = 8


class CoreMemoryProviderSettings(BaseModel):
    enabled: bool = True
    backend: str = "local"
    sqlite_path: str = ""


class CoreMemorySettings(BaseModel):
    enabled: bool = True
    require_approval: bool = True
    auto_approve_explicit_user_memory: bool = False
    sqlite_path: str = ""
    budgets: CoreMemoryBudgetSettings = Field(default_factory=CoreMemoryBudgetSettings)
    safety: CoreMemoryFeatureToggle = Field(default_factory=CoreMemoryFeatureToggle)
    dedupe: CoreMemoryFeatureToggle = Field(default_factory=CoreMemoryFeatureToggle)
    conflict_detection: CoreMemoryFeatureToggle = Field(default_factory=CoreMemoryFeatureToggle)
    automation: CoreMemoryAutomationSettings = Field(default_factory=CoreMemoryAutomationSettings)
    provider: CoreMemoryProviderSettings = Field(default_factory=CoreMemoryProviderSettings)


class EpisodicMemorySettings(BaseModel):
    enabled: bool = True
    max_snippets: int = 4
    max_chars: int = 3000


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
    file_memory_enable: bool = True
    file_memory_search_enable: bool = True
    file_memory_root: str = ""
    file_memory_extra_paths: list[str] = []
    file_memory_index_path: str = ""
    file_memory_chroma_collection: str = "pp_agent_file_memory"
    file_memory_chunk_target_chars: int = 1600
    file_memory_chunk_overlap_lines: int = 3
    file_memory_top_k: int = 5
    file_memory_candidate_multiplier: int = 4
    file_memory_vector_weight: float = 0.7
    file_memory_bm25_weight: float = 0.3
    file_memory_max_per_file: int = 3
    file_memory_snippet_chars: int = 700
    file_memory_sync_on_search: bool = True
    file_memory_allow_remote_embedding: bool = True
    core_memory: CoreMemorySettings = Field(default_factory=CoreMemorySettings)
    episodic_memory: EpisodicMemorySettings = Field(default_factory=EpisodicMemorySettings)
