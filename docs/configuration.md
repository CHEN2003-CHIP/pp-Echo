# Configuration Guide

This page collects the configuration material that used to make the README home page too long. It covers environment variables, project config, resource manifests, and a complete sample JSON configuration.

## Resolution order

At a high level, pp-Echo loads configuration in this order:

1. built-in defaults from `Settings`
2. environment variable overrides
3. project overrides from `.pp-agent/config.json`
4. workspace instructions from `AGENTS.md`
5. optional `.pp-agent/SYSTEM.md`

Core implementation lives in `src/pp_agent/storage/settings.py`.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `PP_AGENT_API_KEY` | API key for the configured OpenAI-compatible provider |
| `PP_AGENT_BASE_URL` | Override provider base URL |
| `PP_AGENT_MODEL` | Override model name |
| `PP_AGENT_ENABLE_THINKING` | Toggle provider-specific thinking/reasoning flag |
| `PP_AGENT_HOME` | Override the global pp-Echo state directory |
| `PP_AGENT_SESSIONS_DIR` | Override session storage path |
| `PP_AGENT_TIMELINES_DIR` | Override timeline storage path |
| `PP_AGENT_CHECKPOINTS_DIR` | Override checkpoint storage path |

## Project config

Create `.pp-agent/config.json` for per-project overrides.

### Complete sample JSON

```json
{
  "model": "qwen3.5-plus",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "enable_thinking": false,
  "tool_policy": {
    "shell_timeout_seconds": 30,
    "permission_mode": "workspace-write",
    "allowed_tools": [],
    "ask_tools": [
      "run_shell",
      "write_file",
      "edit_file"
    ],
    "denied_tools": [],
    "tool_confirmation": {
      "write_file": true,
      "edit_file": true,
      "run_shell": true,
      "high_risk_plan": true
    }
  },
  "capabilities": {
    "builtin_tools": {
      "enable": true
    },
    "skills": {
      "enable_project": true,
      "enable_user": true,
      "enable_builtin": true,
      "custom_directories": [],
      "ignored": [],
      "include": []
    },
    "extensions": {
      "enable_project": true,
      "enable_user": true,
      "enable_builtin": false,
      "custom_directories": [],
      "ignored": [],
      "include": []
    },
    "mcp": {
      "enable": false,
      "config_paths": [],
      "server_filters": []
    },
    "browser": {
      "enable": false,
      "browser_executable": "",
      "user_data_dir": "",
      "screenshot_dir": "",
      "launch_flags": []
    }
  },
  "subagents": {
    "default_max_turns": 4,
    "max_turns": {
      "memory-scout": 3,
      "repo-researcher": 4,
      "api-scout": 4,
      "test-investigator": 4,
      "change-reviewer": 4,
      "implementation-planner": 4,
      "code-worker": 4
    },
    "enforce_orchestrated_edit_contract": true,
    "require_patch_artifact_for_code_change": true
  },
  "tool_confirmation": {
    "write_file": true,
    "edit_file": true,
    "run_shell": true,
    "high_risk_plan": true
  },
  "storage": {
    "sessions_dir": "./.pp-agent/sessions",
    "timelines_dir": "./.pp-agent/timelines",
    "checkpoints_dir": "./.pp-agent/checkpoints"
  },
  "memory": {
    "enable": false,
    "backend": "sqlite",
    "sqlite_path": "./.pp-agent/history.db",
    "chunk_target_tokens": 350,
    "chunk_max_tokens": 420,
    "sqlite_busy_timeout_ms": 5000,
    "embedding_enable": false,
    "embedding_provider": "dashscope",
    "embedding_model": "multimodal-embedding-v1",
    "dashscope_api_key_env": "DASHSCOPE_API_KEY",
    "embedding_batch_size": 16,
    "vector_enable": false,
    "vector_backend": "chroma",
    "chroma_path": "./.pp-agent/chroma",
    "chroma_collection": "pp_agent_history",
    "chroma_collection_per_embedding": true,
    "indexing_enable": false,
    "indexing_batch_size": 100,
    "retrieval_enable": false,
    "retrieval_limit": 6,
    "retrieval_same_session_bias": 1.0,
    "retrieval_max_per_session": 2,
    "retrieval_max_snippets": 4,
    "retrieval_max_chars": 1600,
    "hybrid_enable": false,
    "hybrid_keyword_limit": 12,
    "hybrid_vector_limit": 12,
    "recent_dedup_enable": true,
    "recent_dedup_use_chunk_metadata": true,
    "snippet_categorize_enable": true,
    "reranker_enable": false,
    "reranker_backend": "lightweight",
    "reranker_limit": 8,
    "snippet_prioritize_long_term_preferences": true,
    "snippet_compress_error_stacks": true,
    "snippet_path_weight_boost": 1.0,
    "file_memory_enable": true,
    "file_memory_search_enable": true,
    "file_memory_root": ".",
    "file_memory_extra_paths": [],
    "file_memory_index_path": "./.pp-agent/file-memory-index.json",
    "file_memory_chroma_collection": "pp_agent_file_memory",
    "file_memory_chunk_target_chars": 1600,
    "file_memory_chunk_overlap_lines": 3,
    "file_memory_top_k": 5,
    "file_memory_candidate_multiplier": 4,
    "file_memory_vector_weight": 0.7,
    "file_memory_bm25_weight": 0.3,
    "file_memory_max_per_file": 3,
    "file_memory_snippet_chars": 700,
    "file_memory_sync_on_search": true,
    "file_memory_allow_remote_embedding": true
  },
  "learning": {
    "enable": true,
    "auto_extract": true,
    "auto_apply_memory": true,
    "auto_apply_min_confidence": "medium",
    "project_memory_enable": true,
    "project_memory_char_limit": 4000,
    "detailed_memory_enable": true,
    "detailed_memory_char_limit": 12000,
    "detailed_memory_auto_consolidate": true,
    "detailed_memory_sync_index_after_write": true,
    "candidate_limit_per_turn": 3,
    "min_confidence_to_suggest": "medium",
    "llm_extractor_enable": true
  }
}
```

## Notes on compatibility

- `tool_confirmation` still exists for planner-era compatibility, but it is no longer the whole safety model on its own.
- Sensitive execution also passes through the execution-time policy gate and exact-effect review flow.
- `tool_policy.tool_confirmation` is the preferred nested location; the top-level compatibility block may still appear in older configs.

## Resource manifests and discovery

Project resources can be declared in:

- `.pp-agent/resources.json`
- `.pp-agent/package.json`

If no manifest is present, pp-Echo falls back to conventional directories such as:

- `.pp-agent/skills`
- `.pp-agent/extensions`
- `.pi/skills`
- `.agents/skills`

## Helpful commands

```powershell
python -m pp_agent.cli.main config show --workspace .
python -m pp_agent.cli.main capabilities list --workspace .
python -m pp_agent.cli.main skills list --workspace .
```

## Reference files in this repo

- `example-config.json`
- `example-config.jsonc`
- `example-mcp.json`
- `example-mcp.jsonc`
