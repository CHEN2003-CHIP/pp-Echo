from pathlib import Path

from storage.settings import Settings


def test_runtime_storage_defaults_stay_inside_project(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)

    assert settings.session_store_dir() == (tmp_path / ".pp-agent" / "sessions")
    assert settings.timeline_store_dir() == (tmp_path / ".pp-agent" / "timelines")
    assert settings.checkpoint_store_dir() == (tmp_path / ".pp-agent" / "checkpoints")
    assert settings.history_db_path() == (tmp_path / ".pp-agent" / "history.db")
    assert settings.chroma_dir_path() == (tmp_path / ".pp-agent" / "chroma")


def test_system_md_overrides_default_system_prompt(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "SYSTEM.md").write_text("repo system prompt", encoding="utf-8")

    settings = Settings.load(tmp_path)

    assert settings.system_prompt == "repo system prompt"


def test_project_config_overrides_defaults(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"model":"qwen3.5-plus","enable_thinking":false,"shell_timeout_seconds":42,"tool_confirmation":{"write_file":false}}',
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.model.model == "qwen3.5-plus"
    assert settings.model.enable_thinking is False
    assert settings.tool_policy.shell_timeout_seconds == 42
    assert settings.tool_policy.confirm_write_file is False


def test_capability_settings_are_loaded_from_project_config(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"capabilities":{"builtin_tools":{"enable":false},"skills":{"enable_builtin":false,"custom_directories":["C:/skills"],"include":["review*"],"ignored":["review-draft"]},"mcp":{"enable":true,"config_paths":["C:/mcp.json"],"server_filters":["github*"]},"extensions":{"enable_builtin":true,"custom_directories":["C:/ext"],"include":["adapter*"],"ignored":["draft*"]}}}',
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.capabilities.builtin_tools.enable is False
    assert settings.capabilities.skills.enable_builtin is False
    assert settings.capabilities.skills.custom_directories == ["C:/skills"]
    assert settings.capabilities.skills.include == ["review*"]
    assert settings.capabilities.skills.ignored == ["review-draft"]
    assert settings.capabilities.mcp.enable is True
    assert settings.capabilities.mcp.config_paths == ["C:/mcp.json"]
    assert settings.capabilities.mcp.server_filters == ["github*"]
    assert settings.capabilities.extensions.enable_builtin is True
    assert settings.capabilities.extensions.custom_directories == ["C:/ext"]
    assert settings.capabilities.extensions.include == ["adapter*"]
    assert settings.capabilities.extensions.ignored == ["draft*"]


def test_memory_settings_are_loaded_from_project_config(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"memory":{"enable":true,"backend":"sqlite","sqlite_path":"C:/history.db","chunk_target_tokens":222,"chunk_max_tokens":333,"sqlite_busy_timeout_ms":4444,"embedding_enable":true,"embedding_provider":"dashscope","embedding_model":"multimodal-embedding-v1","dashscope_api_key_env":"CUSTOM_KEY","embedding_batch_size":8,"vector_enable":true,"vector_backend":"chroma","chroma_path":"C:/chroma","chroma_collection":"hist","indexing_enable":true,"indexing_batch_size":64,"retrieval_enable":true,"retrieval_limit":9,"retrieval_same_session_bias":1.25,"retrieval_max_snippets":3,"retrieval_max_chars":1200,"hybrid_enable":true,"hybrid_keyword_limit":14,"hybrid_vector_limit":15,"recent_dedup_enable":false,"recent_dedup_use_chunk_metadata":false,"snippet_categorize_enable":false,"reranker_enable":true,"reranker_backend":"lightweight","reranker_limit":5,"snippet_prioritize_long_term_preferences":false,"snippet_compress_error_stacks":false,"snippet_path_weight_boost":1.5}}',
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.memory.enable is True
    assert settings.memory.backend == "sqlite"
    assert settings.memory.sqlite_path == "C:/history.db"
    assert settings.memory.chunk_target_tokens == 222
    assert settings.memory.chunk_max_tokens == 333
    assert settings.memory.sqlite_busy_timeout_ms == 4444
    assert settings.memory.embedding_enable is True
    assert settings.memory.embedding_provider == "dashscope"
    assert settings.memory.embedding_model == "multimodal-embedding-v1"
    assert settings.memory.dashscope_api_key_env == "CUSTOM_KEY"
    assert settings.memory.embedding_batch_size == 8
    assert settings.memory.vector_enable is True
    assert settings.memory.vector_backend == "chroma"
    assert settings.memory.chroma_path == "C:/chroma"
    assert settings.memory.chroma_collection == "hist"
    assert settings.memory.indexing_enable is True
    assert settings.memory.indexing_batch_size == 64
    assert settings.memory.retrieval_enable is True
    assert settings.memory.retrieval_limit == 9
    assert settings.memory.retrieval_same_session_bias == 1.25
    assert settings.memory.retrieval_max_snippets == 3
    assert settings.memory.retrieval_max_chars == 1200
    assert settings.memory.hybrid_enable is True
    assert settings.memory.hybrid_keyword_limit == 14
    assert settings.memory.hybrid_vector_limit == 15
    assert settings.memory.recent_dedup_enable is False
    assert settings.memory.recent_dedup_use_chunk_metadata is False
    assert settings.memory.snippet_categorize_enable is False
    assert settings.memory.reranker_enable is True
    assert settings.memory.reranker_backend == "lightweight"
    assert settings.memory.reranker_limit == 5
    assert settings.memory.snippet_prioritize_long_term_preferences is False
    assert settings.memory.snippet_compress_error_stacks is False
    assert settings.memory.snippet_path_weight_boost == 1.5


def test_storage_settings_are_loaded_from_project_config(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"storage":{"sessions_dir":"state/sessions","timelines_dir":"state/timelines","checkpoints_dir":"state/checkpoints"}}',
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.session_store_dir() == (tmp_path / "state" / "sessions")
    assert settings.timeline_store_dir() == (tmp_path / "state" / "timelines")
    assert settings.checkpoint_store_dir() == (tmp_path / "state" / "checkpoints")


def test_runtime_storage_paths_allow_absolute_project_config_values(tmp_path: Path) -> None:
    absolute_sessions = tmp_path / "custom-sessions-abs"
    absolute_timelines = tmp_path / "custom-timelines-abs"
    absolute_checkpoints = tmp_path / "custom-checkpoints-abs"
    absolute_history = tmp_path / "custom-history-abs.db"
    absolute_chroma = tmp_path / "custom-chroma-abs"

    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        (
            '{"storage":{"sessions_dir":"%s","timelines_dir":"%s","checkpoints_dir":"%s"},'
            '"memory":{"sqlite_path":"%s","chroma_path":"%s"}}'
        )
        % (
            absolute_sessions.as_posix(),
            absolute_timelines.as_posix(),
            absolute_checkpoints.as_posix(),
            absolute_history.as_posix(),
            absolute_chroma.as_posix(),
        ),
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.session_store_dir() == absolute_sessions.resolve()
    assert settings.timeline_store_dir() == absolute_timelines.resolve()
    assert settings.checkpoint_store_dir() == absolute_checkpoints.resolve()
    assert settings.history_db_path() == absolute_history.resolve()
    assert settings.chroma_dir_path() == absolute_chroma.resolve()


def test_runtime_storage_paths_resolve_relative_project_config_values_from_workspace(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"storage":{"sessions_dir":"state/sessions","timelines_dir":"state/timelines","checkpoints_dir":"state/checkpoints"},"memory":{"sqlite_path":"state/history.db","chroma_path":"state/chroma"}}',
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.session_store_dir() == (tmp_path / "state" / "sessions")
    assert settings.timeline_store_dir() == (tmp_path / "state" / "timelines")
    assert settings.checkpoint_store_dir() == (tmp_path / "state" / "checkpoints")
    assert settings.history_db_path() == (tmp_path / "state" / "history.db")
    assert settings.chroma_dir_path() == (tmp_path / "state" / "chroma")


def test_runtime_storage_environment_variables_override_project_config(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"storage":{"sessions_dir":"cfg/sessions","timelines_dir":"cfg/timelines","checkpoints_dir":"cfg/checkpoints"},"memory":{"sqlite_path":"cfg/history.db","chroma_path":"cfg/chroma"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("PP_AGENT_SESSIONS_DIR", "env/sessions")
    monkeypatch.setenv("PP_AGENT_TIMELINES_DIR", "env/timelines")
    monkeypatch.setenv("PP_AGENT_CHECKPOINTS_DIR", "env/checkpoints")
    monkeypatch.setenv("PP_AGENT_MEMORY_SQLITE_PATH", "env/history.db")
    monkeypatch.setenv("PP_AGENT_CHROMA_PATH", "env/chroma")

    settings = Settings.load(tmp_path)

    assert settings.session_store_dir() == (tmp_path / "env" / "sessions")
    assert settings.timeline_store_dir() == (tmp_path / "env" / "timelines")
    assert settings.checkpoint_store_dir() == (tmp_path / "env" / "checkpoints")
    assert settings.history_db_path() == (tmp_path / "env" / "history.db")
    assert settings.chroma_dir_path() == (tmp_path / "env" / "chroma")
