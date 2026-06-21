from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pp_agent.storage.settings import Settings

ReloadPolicy = Literal["hot", "next_turn", "rebuild_runtime", "restart_required"]


@dataclass(frozen=True)
class ConfigField:
    path: str
    value_type: str
    category: str
    reload_policy: ReloadPolicy
    description: str = ""
    session_override: bool = True
    runtime_override: bool = False
    editor: str = "text"
    options: tuple[str, ...] = field(default_factory=tuple)
    minimum: float | None = None
    maximum: float | None = None
    item_type: str = "string"


_FIELDS: tuple[ConfigField, ...] = (
    ConfigField("execution_mode", "string", "general", "next_turn", "Runtime execution mode."),
    ConfigField("runtime_id", "string|null", "general", "next_turn", "Agent turn runtime profile id."),
    ConfigField("provider.name", "string", "model", "next_turn", "Provider adapter name.", editor="select", options=("openai", "deepseek", "qwen-dashscope", "xiaomi", "alibaba-bailian", "anthropic", "custom-openai-compatible")),
    ConfigField("provider.base_url", "string", "model", "next_turn", "OpenAI-compatible base URL."),
    ConfigField("provider.api_key_env", "string", "model", "restart_required", "Environment variable that stores the API key.", session_override=False),
    ConfigField("model.provider", "string", "model", "next_turn", session_override=True),
    ConfigField("model.model", "string", "model", "next_turn", session_override=True),
    ConfigField("model.temperature", "number", "model", "next_turn", session_override=True),
    ConfigField("model.max_tokens", "integer|null", "model", "next_turn", session_override=True),
    ConfigField("model.enable_thinking", "boolean", "model", "next_turn", session_override=True),
    ConfigField("tool_policy.shell_timeout_seconds", "integer", "tools", "rebuild_runtime", "Default shell command timeout.", minimum=1),
    ConfigField("tool_policy.permission_mode", "string", "tools", "rebuild_runtime", "Default filesystem/tool permission mode.", editor="select", options=("read-only", "workspace-write", "danger-full-access", "prompt")),
    ConfigField("tool_policy.allowed_tools", "array", "tools", "rebuild_runtime", "Tool allowlist. Empty means no allowlist."),
    ConfigField("tool_policy.denied_tools", "array", "tools", "rebuild_runtime", "Tool denylist."),
    ConfigField("tool_policy.ask_tools", "array", "tools", "rebuild_runtime", "Tools that should ask before running."),
    ConfigField("tool_policy.confirm_write_file", "boolean", "tools", "next_turn"),
    ConfigField("tool_policy.confirm_edit_file", "boolean", "tools", "next_turn"),
    ConfigField("tool_policy.confirm_run_shell", "boolean", "tools", "next_turn"),
    ConfigField("tool_policy.confirm_high_risk_plan", "boolean", "tools", "next_turn"),
    ConfigField("capabilities.builtin_tools.enable", "boolean", "tools", "rebuild_runtime"),
    ConfigField("capabilities.skills.enable_project", "boolean", "skills", "rebuild_runtime"),
    ConfigField("capabilities.skills.enable_user", "boolean", "skills", "rebuild_runtime"),
    ConfigField("capabilities.skills.enable_builtin", "boolean", "skills", "rebuild_runtime"),
    ConfigField("capabilities.skills.custom_directories", "array", "skills", "rebuild_runtime"),
    ConfigField("capabilities.skills.ignored", "array", "skills", "rebuild_runtime"),
    ConfigField("capabilities.skills.include", "array", "skills", "rebuild_runtime"),
    ConfigField("capabilities.mcp.enable", "boolean", "plugins", "rebuild_runtime"),
    ConfigField("capabilities.mcp.config_paths", "array", "plugins", "rebuild_runtime"),
    ConfigField("capabilities.mcp.server_filters", "array", "plugins", "rebuild_runtime"),
    ConfigField("capabilities.extensions.enable_project", "boolean", "plugins", "rebuild_runtime"),
    ConfigField("capabilities.extensions.enable_user", "boolean", "plugins", "rebuild_runtime"),
    ConfigField("capabilities.extensions.enable_builtin", "boolean", "plugins", "rebuild_runtime"),
    ConfigField("capabilities.extensions.custom_directories", "array", "plugins", "rebuild_runtime"),
    ConfigField("capabilities.extensions.ignored", "array", "plugins", "rebuild_runtime"),
    ConfigField("capabilities.extensions.include", "array", "plugins", "rebuild_runtime"),
    ConfigField("capabilities.browser.enable", "boolean", "browser_web", "rebuild_runtime"),
    ConfigField("capabilities.browser.browser_executable", "string", "browser_web", "restart_required", session_override=False),
    ConfigField("capabilities.browser.user_data_dir", "string", "browser_web", "restart_required", session_override=False),
    ConfigField("capabilities.browser.screenshot_dir", "string", "browser_web", "hot", runtime_override=True),
    ConfigField("capabilities.browser.launch_flags", "array", "browser_web", "restart_required"),
    ConfigField("capabilities.browser.allow_private_network", "boolean", "browser_web", "next_turn"),
    ConfigField("capabilities.browser.allowed_hostnames", "array", "browser_web", "next_turn"),
    ConfigField("capabilities.browser.deny_hostnames", "array", "browser_web", "next_turn"),
    ConfigField("capabilities.browser.allow_high_risk_actions", "boolean", "browser_web", "next_turn"),
    ConfigField("capabilities.browser.evaluate_enabled", "boolean", "browser_web", "next_turn"),
    ConfigField("capabilities.web.search_providers", "array", "browser_web", "next_turn"),
    ConfigField("capabilities.web.search_timeout_seconds", "integer", "browser_web", "next_turn"),
    ConfigField("capabilities.web.fetch_timeout_seconds", "integer", "browser_web", "next_turn"),
    ConfigField("storage.sessions_dir", "string", "storage", "restart_required", session_override=False),
    ConfigField("storage.timelines_dir", "string", "storage", "restart_required", session_override=False),
    ConfigField("storage.checkpoints_dir", "string", "storage", "restart_required", session_override=False),
    ConfigField("subagents.default_max_turns", "integer|null", "subagents", "next_turn"),
    ConfigField("subagents.max_turns", "object", "subagents", "next_turn"),
    ConfigField("subagents.enforce_orchestrated_edit_contract", "boolean", "subagents", "next_turn"),
    ConfigField("subagents.require_patch_artifact_for_code_change", "boolean", "subagents", "next_turn"),
    ConfigField("memory.enable", "boolean", "memory", "rebuild_runtime"),
    ConfigField("memory.backend", "string", "memory", "restart_required"),
    ConfigField("memory.sqlite_path", "string", "memory", "restart_required", session_override=False),
    ConfigField("memory.chunk_target_tokens", "integer", "memory", "next_turn"),
    ConfigField("memory.chunk_max_tokens", "integer", "memory", "next_turn"),
    ConfigField("memory.sqlite_busy_timeout_ms", "integer", "memory", "next_turn"),
    ConfigField("memory.embedding_enable", "boolean", "memory", "rebuild_runtime"),
    ConfigField("memory.embedding_provider", "string", "memory", "rebuild_runtime"),
    ConfigField("memory.embedding_model", "string", "memory", "rebuild_runtime"),
    ConfigField("memory.dashscope_api_key_env", "string", "memory", "restart_required", session_override=False),
    ConfigField("memory.embedding_batch_size", "integer", "memory", "next_turn"),
    ConfigField("memory.vector_enable", "boolean", "memory", "rebuild_runtime"),
    ConfigField("memory.vector_backend", "string", "memory", "restart_required"),
    ConfigField("memory.chroma_path", "string", "memory", "restart_required", session_override=False),
    ConfigField("memory.chroma_collection", "string", "memory", "restart_required", session_override=False),
    ConfigField("memory.chroma_collection_per_embedding", "boolean", "memory", "restart_required", session_override=False),
    ConfigField("memory.indexing_enable", "boolean", "memory", "next_turn"),
    ConfigField("memory.indexing_batch_size", "integer", "memory", "next_turn"),
    ConfigField("memory.file_memory_enable", "boolean", "memory", "rebuild_runtime"),
    ConfigField("memory.file_memory_search_enable", "boolean", "memory", "rebuild_runtime"),
    ConfigField("memory.file_memory_root", "string", "memory", "rebuild_runtime"),
    ConfigField("memory.file_memory_extra_paths", "array", "memory", "rebuild_runtime"),
    ConfigField("memory.file_memory_index_path", "string", "memory", "restart_required", session_override=False),
    ConfigField("memory.file_memory_chroma_collection", "string", "memory", "restart_required", session_override=False),
    ConfigField("memory.file_memory_chunk_target_chars", "integer", "memory", "next_turn"),
    ConfigField("memory.file_memory_chunk_overlap_lines", "integer", "memory", "next_turn"),
    ConfigField("memory.file_memory_top_k", "integer", "memory", "next_turn"),
    ConfigField("memory.file_memory_candidate_multiplier", "integer", "memory", "next_turn"),
    ConfigField("memory.file_memory_vector_weight", "number", "memory", "next_turn"),
    ConfigField("memory.file_memory_bm25_weight", "number", "memory", "next_turn"),
    ConfigField("memory.file_memory_max_per_file", "integer", "memory", "next_turn"),
    ConfigField("memory.file_memory_snippet_chars", "integer", "memory", "next_turn"),
    ConfigField("memory.file_memory_sync_on_search", "boolean", "memory", "next_turn"),
    ConfigField("memory.file_memory_allow_remote_embedding", "boolean", "memory", "next_turn"),
    ConfigField("memory.retrieval_enable", "boolean", "memory", "next_turn"),
    ConfigField("memory.retrieval_limit", "integer", "memory", "next_turn"),
    ConfigField("memory.retrieval_same_session_bias", "number", "memory", "next_turn"),
    ConfigField("memory.retrieval_max_per_session", "integer", "memory", "next_turn"),
    ConfigField("memory.retrieval_max_snippets", "integer", "memory", "next_turn"),
    ConfigField("memory.retrieval_max_chars", "integer", "memory", "next_turn"),
    ConfigField("memory.hybrid_enable", "boolean", "memory", "next_turn"),
    ConfigField("memory.hybrid_keyword_limit", "integer", "memory", "next_turn"),
    ConfigField("memory.hybrid_vector_limit", "integer", "memory", "next_turn"),
    ConfigField("memory.recent_dedup_enable", "boolean", "memory", "next_turn"),
    ConfigField("memory.recent_dedup_use_chunk_metadata", "boolean", "memory", "next_turn"),
    ConfigField("memory.snippet_categorize_enable", "boolean", "memory", "next_turn"),
    ConfigField("memory.reranker_enable", "boolean", "memory", "next_turn"),
    ConfigField("memory.reranker_backend", "string", "memory", "next_turn"),
    ConfigField("memory.reranker_limit", "integer", "memory", "next_turn"),
    ConfigField("memory.snippet_prioritize_long_term_preferences", "boolean", "memory", "next_turn"),
    ConfigField("memory.snippet_compress_error_stacks", "boolean", "memory", "next_turn"),
    ConfigField("memory.snippet_path_weight_boost", "number", "memory", "next_turn"),
    ConfigField("memory.core_memory.enabled", "boolean", "memory", "rebuild_runtime"),
    ConfigField("memory.core_memory.require_approval", "boolean", "memory", "next_turn"),
    ConfigField("memory.core_memory.auto_approve_explicit_user_memory", "boolean", "memory", "next_turn"),
    ConfigField("memory.core_memory.sqlite_path", "string", "memory", "restart_required", session_override=False),
    ConfigField("memory.core_memory.budgets.user_profile_chars", "integer", "memory", "next_turn"),
    ConfigField("memory.core_memory.budgets.project_profile_chars", "integer", "memory", "next_turn"),
    ConfigField("memory.core_memory.budgets.agent_notes_chars", "integer", "memory", "next_turn"),
    ConfigField("memory.core_memory.budgets.total_chars", "integer", "memory", "next_turn"),
    ConfigField("memory.core_memory.safety.enabled", "boolean", "memory", "next_turn"),
    ConfigField("memory.core_memory.dedupe.enabled", "boolean", "memory", "next_turn"),
    ConfigField("memory.core_memory.conflict_detection.enabled", "boolean", "memory", "next_turn"),
    ConfigField("memory.core_memory.automation.enabled", "boolean", "memory", "next_turn"),
    ConfigField("memory.core_memory.automation.use_llm_summary", "boolean", "memory", "next_turn"),
    ConfigField("memory.core_memory.automation.llm_summary_model", "string", "memory", "next_turn"),
    ConfigField("memory.core_memory.automation.max_merge_group_size", "integer", "memory", "next_turn"),
    ConfigField("memory.core_memory.automation.max_compaction_group_size", "integer", "memory", "next_turn"),
    ConfigField("memory.core_memory.provider.enabled", "boolean", "memory", "rebuild_runtime"),
    ConfigField("memory.core_memory.provider.backend", "string", "memory", "rebuild_runtime", options=["local", "noop"]),
    ConfigField("memory.core_memory.provider.sqlite_path", "string", "memory", "restart_required", session_override=False),
    ConfigField("memory.episodic_memory.enabled", "boolean", "memory", "next_turn"),
    ConfigField("memory.episodic_memory.max_snippets", "integer", "memory", "next_turn"),
    ConfigField("memory.episodic_memory.max_chars", "integer", "memory", "next_turn"),
    ConfigField("learning.enable", "boolean", "learning", "next_turn"),
    ConfigField("learning.auto_extract", "boolean", "learning", "next_turn"),
    ConfigField("learning.auto_apply_memory", "boolean", "learning", "next_turn"),
    ConfigField("learning.project_memory_enable", "boolean", "learning", "next_turn"),
)

_FIELD_BY_PATH = {field.path: field for field in _FIELDS}
_POLICY_ORDER: dict[ReloadPolicy, int] = {
    "hot": 0,
    "next_turn": 1,
    "rebuild_runtime": 2,
    "restart_required": 3,
}


def config_schema() -> dict[str, Any]:
    return {
        "fields": [
            {
                "path": field.path,
                "type": field.value_type,
                "category": field.category,
                "reload_policy": field.reload_policy,
                "description": field.description,
                "session_override": field.session_override,
                "runtime_override": field.runtime_override,
                "editor": field.editor,
                "options": list(field.options),
                "minimum": field.minimum,
                "maximum": field.maximum,
                "item_type": field.item_type,
            }
            for field in _FIELDS
        ],
        "categories": sorted({field.category for field in _FIELDS}),
    }


def validate_project_config_paths(data: dict[str, Any]) -> None:
    unknown = [path for path in _leaf_paths(data) if not is_known_project_path(path)]
    if unknown:
        raise ConfigValidationError.from_paths("Unknown config path", unknown)


def validate_session_path(path: str) -> None:
    field = _FIELD_BY_PATH.get(path)
    if field is None or not field.session_override:
        raise ConfigValidationError([config_error(path, "scope", "Config path does not support session override")])


def validate_runtime_path(path: str) -> None:
    if path.startswith("debug."):
        return
    field = _FIELD_BY_PATH.get(path)
    if field is None or not field.runtime_override:
        raise ConfigValidationError([config_error(path, "scope", "Config path does not support runtime override")])


def validate_settings(settings: Settings) -> None:
    if not str(settings.model.model or "").strip():
        raise ConfigValidationError([config_error("model.model", "value", "model.model cannot be empty")])
    if settings.tool_policy.shell_timeout_seconds < 1:
        raise ConfigValidationError([config_error("tool_policy.shell_timeout_seconds", "minimum", "must be >= 1")])
    if settings.capabilities.web.search_timeout_seconds < 1:
        raise ConfigValidationError([config_error("capabilities.web.search_timeout_seconds", "minimum", "must be >= 1")])
    if settings.capabilities.web.fetch_timeout_seconds < 1:
        raise ConfigValidationError([config_error("capabilities.web.fetch_timeout_seconds", "minimum", "must be >= 1")])


def reload_policy_for_paths(paths: list[str]) -> ReloadPolicy:
    policy: ReloadPolicy = "hot"
    for path in paths:
        if path.startswith("debug."):
            candidate: ReloadPolicy = "hot"
        elif path == "active_profile":
            candidate = "next_turn"
        elif path.startswith("profiles."):
            parts = path.split(".", 2)
            field = _FIELD_BY_PATH.get(parts[2]) if len(parts) == 3 else None
            candidate = field.reload_policy if field is not None else "restart_required"
        else:
            field = _FIELD_BY_PATH.get(path)
            candidate = field.reload_policy if field is not None else "restart_required"
        if _POLICY_ORDER[candidate] > _POLICY_ORDER[policy]:
            policy = candidate
    return policy


def is_known_project_path(path: str) -> bool:
    if path == "active_profile":
        return True
    if path.startswith("profiles."):
        parts = path.split(".", 2)
        return len(parts) == 3 and is_known_project_path(parts[2])
    if path in {"model", "provider", "base_url", "enable_thinking", "shell_timeout_seconds", "tool_confirmation"}:
        return True
    if path.startswith("tool_confirmation."):
        return path.split(".", 1)[1] in {"write_file", "edit_file", "run_shell", "high_risk_plan"}
    return path in _FIELD_BY_PATH


def field_for_path(path: str) -> ConfigField | None:
    return _FIELD_BY_PATH.get(path)


def known_config_paths() -> set[str]:
    return set(_FIELD_BY_PATH)


def config_error(path: str, code: str, message: str) -> dict[str, str]:
    return {"path": path, "code": code, "message": message}


class ConfigValidationError(ValueError):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        message = "; ".join(f"{item.get('path', '')}: {item.get('message', '')}" for item in errors)
        super().__init__(message or "Invalid config")

    @classmethod
    def from_paths(cls, message: str, paths: list[str]) -> "ConfigValidationError":
        return cls([config_error(path, "unknown_path", message) for path in sorted(paths)])


def _leaf_paths(data: Any, prefix: str = "") -> list[str]:
    if not isinstance(data, dict):
        return [prefix] if prefix else []
    paths: list[str] = []
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and value:
            paths.extend(_leaf_paths(value, path))
        else:
            paths.append(path)
    return paths
