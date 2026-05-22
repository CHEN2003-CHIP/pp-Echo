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

    assert settings.system_prompt.startswith("repo system prompt")
    assert "File memory protocol:" in settings.system_prompt
    assert "Subagent orchestration protocol:" in settings.system_prompt


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


def test_subagent_settings_are_loaded_from_project_config(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"subagents":{"default_max_turns":5,"max_turns":{"memory-scout":2,"repo-researcher":6},'
        '"enforce_orchestrated_edit_contract":false,"require_patch_artifact_for_code_change":false}}',
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.subagents.default_max_turns == 5
    assert settings.subagents.max_turns == {"memory-scout": 2, "repo-researcher": 6}
    assert settings.subagents.max_turns_for("memory-scout", 4) == 2
    assert settings.subagents.max_turns_for("api-scout", 4) == 5
    assert settings.subagents.enforce_orchestrated_edit_contract is False
    assert settings.subagents.require_patch_artifact_for_code_change is False


def test_tool_policy_settings_are_loaded_from_project_config(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        (
            '{"tool_policy":{"permission_mode":"prompt","shell_timeout_seconds":17,'
            '"allowed_tools":["read_file","git_*"],"ask_tools":["run_shell"],"denied_tools":["fetch.*"],'
            '"tool_confirmation":{"write_file":false,"edit_file":true,"run_shell":false,"high_risk_plan":false}},'
            '"tool_confirmation":{"write_file":true}}'
        ),
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.tool_policy.permission_mode == "prompt"
    assert settings.tool_policy.shell_timeout_seconds == 17
    assert settings.tool_policy.allowed_tools == ["read_file", "git_*"]
    assert settings.tool_policy.ask_tools == ["run_shell"]
    assert settings.tool_policy.denied_tools == ["fetch.*"]
    assert settings.tool_policy.confirm_write_file is True
    assert settings.tool_policy.confirm_edit_file is True
    assert settings.tool_policy.confirm_run_shell is False
    assert settings.tool_policy.confirm_high_risk_plan is False


def test_capability_settings_are_loaded_from_project_config(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"capabilities":{"builtin_tools":{"enable":false},"skills":{"enable_builtin":false,"custom_directories":["C:/skills"],"include":["review*"],"ignored":["review-draft"]},"mcp":{"enable":true,"config_paths":["C:/mcp.json"],"server_filters":["github*"]},"extensions":{"enable_builtin":true,"custom_directories":["C:/ext"],"include":["adapter*"],"ignored":["draft*"]},"browser":{"enable":true,"browser_executable":"C:/Chrome/chrome.exe","user_data_dir":"C:/browser-profile","screenshot_dir":"C:/browser-shots","launch_flags":["--headless=new"]}}}',
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
    assert settings.capabilities.browser.enable is True
    assert settings.capabilities.browser.browser_executable == "C:/Chrome/chrome.exe"
    assert settings.capabilities.browser.user_data_dir == "C:/browser-profile"
    assert settings.capabilities.browser.screenshot_dir == "C:/browser-shots"
    assert settings.capabilities.browser.launch_flags == ["--headless=new"]


def test_browser_policy_settings_are_loaded_from_project_config(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"capabilities":{"browser":{"enable":true,"default_profile":"default","allow_private_network":true,'
        '"allowed_hostnames":["example.com"],"deny_hostnames":["*.internal"],"allow_user_profile":true,'
        '"allow_remote_profile":true,"allow_high_risk_actions":true,"evaluate_enabled":true,'
        '"snapshot_defaults":{"compact":true}}}}',
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.capabilities.browser.default_profile == "default"
    assert settings.capabilities.browser.allow_private_network is True
    assert settings.capabilities.browser.allowed_hostnames == ["example.com"]
    assert settings.capabilities.browser.deny_hostnames == ["*.internal"]
    assert settings.capabilities.browser.allow_user_profile is True
    assert settings.capabilities.browser.allow_remote_profile is True
    assert settings.capabilities.browser.allow_high_risk_actions is True
    assert settings.capabilities.browser.evaluate_enabled is True
    assert settings.capabilities.browser.snapshot_defaults == {"compact": True}


def test_browser_and_web_timeout_config(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir()
    (project_dir / "config.json").write_text(
        '{"capabilities":{"browser":{"connect_timeout_seconds":25,"navigation_timeout_ms":8000,'
        '"cdp_http_timeout_seconds":4,"cdp_response_timeout_seconds":12,"action_timeout_ms":2200,'
        '"shutdown_timeout_seconds":7},"web":{"search_providers":["baidu","duckduckgo"],'
        '"search_timeout_seconds":6,"fetch_timeout_seconds":8,"zhipu_api_key_env":"CUSTOM_ZHIPU"}}}',
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.capabilities.browser.connect_timeout_seconds == 25
    assert settings.capabilities.browser.navigation_timeout_ms == 8000
    assert settings.capabilities.browser.cdp_http_timeout_seconds == 4
    assert settings.capabilities.browser.cdp_response_timeout_seconds == 12
    assert settings.capabilities.browser.action_timeout_ms == 2200
    assert settings.capabilities.browser.shutdown_timeout_seconds == 7
    assert settings.capabilities.web.search_providers == ["baidu", "duckduckgo"]
    assert settings.capabilities.web.search_timeout_seconds == 6
    assert settings.capabilities.web.fetch_timeout_seconds == 8
    assert settings.capabilities.web.zhipu_api_key_env == "CUSTOM_ZHIPU"


def test_memory_settings_are_loaded_from_project_config(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"memory":{"enable":true,"backend":"sqlite","sqlite_path":"C:/history.db","chunk_target_tokens":222,"chunk_max_tokens":333,"sqlite_busy_timeout_ms":4444,"embedding_enable":true,"embedding_provider":"dashscope","embedding_model":"multimodal-embedding-v1","dashscope_api_key_env":"CUSTOM_KEY","embedding_batch_size":8,"vector_enable":true,"vector_backend":"chroma","chroma_path":"C:/chroma","chroma_collection":"hist","chroma_collection_per_embedding":false,"indexing_enable":true,"indexing_batch_size":64,"retrieval_enable":true,"retrieval_limit":9,"retrieval_same_session_bias":1.25,"retrieval_max_per_session":3,"retrieval_max_snippets":3,"retrieval_max_chars":1200,"hybrid_enable":true,"hybrid_keyword_limit":14,"hybrid_vector_limit":15,"recent_dedup_enable":false,"recent_dedup_use_chunk_metadata":false,"snippet_categorize_enable":false,"reranker_enable":true,"reranker_backend":"lightweight","reranker_limit":5,"snippet_prioritize_long_term_preferences":false,"snippet_compress_error_stacks":false,"snippet_path_weight_boost":1.5}}',
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
    assert settings.memory.chroma_collection_per_embedding is False
    assert settings.memory.indexing_enable is True
    assert settings.memory.indexing_batch_size == 64
    assert settings.memory.retrieval_enable is True
    assert settings.memory.retrieval_limit == 9
    assert settings.memory.retrieval_same_session_bias == 1.25
    assert settings.memory.retrieval_max_per_session == 3
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
