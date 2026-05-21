from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
from typing import Literal, Optional, cast

from pydantic import BaseModel, Field

from pp_agent.learning.models import LearningSettings
from pp_agent.memory.config import MemorySettings
from pp_agent.storage.models import StoredModelConfig, StoredProviderConfig


DEFAULT_SYSTEM_PROMPT = """You are a careful personal coding agent running on Windows 10.
Use tools when needed, prefer reading before editing, and explain actions clearly.
For file changes, prefer staging a diff preview first and only applying it after confirmation.
For high-risk plans, pause at the planner layer and wait for approval before executing them."""

FILE_MEMORY_PROTOCOL_PROMPT = (
    "Use memory_search before answering questions about prior user preferences, previous project decisions, "
    "old bugs, long-running tasks, or remembered facts. Use memory_get when memory_search returns a relevant "
    "path and line range that needs exact detail. Do not use memory_get to read arbitrary workspace files."
)

SUBAGENT_ORCHESTRATION_PROMPT = (
    "Use orchestrate_agents for complex repository research, debugging, or implementation planning that benefits "
    "from parallel specialized subagents. For simple questions, answer directly. Set allow_edits=true only when "
    "the user explicitly allows subagents to stage file edits; staged edits still require normal approval. "
    "When the user explicitly requires orchestrate_agents or workflow=code_change with allow_edits=true, do not "
    "fall back to direct edit_file/write_file if orchestration produces no patch artifact; report the failure instead."
)

PERMISSION_MODES = {"read-only", "workspace-write", "danger-full-access", "prompt"}
PermissionModeName = Literal["read-only", "workspace-write", "danger-full-access", "prompt"]


class ToolPolicyConfig(BaseModel):
    """
    【AI工具调用安全策略】
    管控文件操作、Shell执行、高危计划的**人工确认规则**和**超时限制**
    所有确认项默认开启，遵循「最小权限、安全优先」原则
    """
    shell_timeout_seconds: int = 30
    permission_mode: PermissionModeName = "workspace-write"
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    ask_tools: list[str] = Field(default_factory=list)
    confirm_write_file: bool = True
    confirm_edit_file: bool = True
    confirm_run_shell: bool = True
    confirm_high_risk_plan: bool = True


class BuiltinToolCapabilityConfig(BaseModel):
    enable: bool = True


class SkillCapabilityConfig(BaseModel):
    """
    【AI Agent 技能能力配置】
    控制：启用哪些类型的技能、自定义技能路径、技能白名单/黑名单过滤
    用于精准管控 Agent 能加载、使用哪些技能
    """

    # 1. 技能启用开关（分层控制）
    enable_project: bool = True
    enable_user: bool = True
    enable_builtin: bool = True
    # 2. 自定义/路径配置
    custom_directories: list[str] = Field(default_factory=list)# 自定义技能目录（字符串路径）
    ignored: list[str] = Field(default_factory=list) # 技能黑名单（通配符匹配）
    include: list[str] = Field(default_factory=list)# 技能白名单（通配符匹配）


    def custom_paths(self) -> list[Path]:
        """将自定义字符串目录 → 标准化Path对象（支持~展开用户目录）"""
        return [Path(value).expanduser() for value in self.custom_directories]

    def includes_name(self, name: str) -> bool:
        """
        【核心过滤方法】判断技能名称是否允许加载
        规则：白名单优先 → 黑名单拦截
        支持 fnmatch 通配符（如 *file*, shell_*）
        """
        if self.include and not any(fnmatch.fnmatch(name, pattern) for pattern in self.include):
            return False
        if any(fnmatch.fnmatch(name, pattern) for pattern in self.ignored):
            return False
        return True


class MCPCapabilityConfig(BaseModel):
    """
    【MCP（Model Context Protocol）能力配置】
    控制AI是否启用MCP协议扩展、MCP配置文件路径、允许连接的MCP服务器
    用于安全管控AI的外部服务连接能力
    """
    enable: bool = False
    config_paths: list[str] = Field(default_factory=list)
    server_filters: list[str] = Field(default_factory=list)

    def resolved_config_paths(self, project_dir: Path) -> list[Path]:
        """
        解析并返回标准化的MCP配置文件路径
        规则：用户自定义路径优先 → 无自定义则默认使用项目目录下的 mcp.json
        """
        if self.config_paths:
            return [Path(value).expanduser() for value in self.config_paths]
        return [project_dir / "mcp.json"]

    def includes_server(self, name: str) -> bool:
        """
        【核心过滤】判断是否允许连接指定名称的MCP服务器
        规则：无过滤器 → 全部允许；有过滤器 → 仅允许通配符匹配的服务器
        """
        if not self.server_filters:
            return True
        return any(fnmatch.fnmatch(name, pattern) for pattern in self.server_filters)


class ExtensionCapabilityConfig(BaseModel):
    """
    【AI Agent 扩展插件能力配置】
    控制 Agent 扩展插件的加载范围、启用层级、自定义路径与黑白名单过滤
    区别于 Skill（可执行技能），Extension 是框架级/功能级插件扩展
    """
    enable_project: bool = True
    enable_user: bool = True
    enable_builtin: bool = False
    custom_directories: list[str] = Field(default_factory=list)
    ignored: list[str] = Field(default_factory=list)
    include: list[str] = Field(default_factory=list)

    def custom_paths(self) -> list[Path]:
        """
        将自定义目录字符串转换为标准化 Path 对象
        支持 ~ 自动解析用户主目录
        """
        return [Path(value).expanduser() for value in self.custom_directories]

    def includes_name(self, name: str) -> bool:
        """
        【核心过滤】判断插件名称是否允许加载
        校验规则：白名单优先校验 → 黑名单拦截 → 放行合规插件
        支持 fnmatch 通配符匹配（* ? []）
        """
        if self.include and not any(fnmatch.fnmatch(name, pattern) for pattern in self.include):
            return False
        if any(fnmatch.fnmatch(name, pattern) for pattern in self.ignored):
            return False
        return True


class BrowserCapabilityConfig(BaseModel):
    """
    Local browser bridge configuration.
    """
    enable: bool = False
    browser_executable: str = ""
    user_data_dir: str = ""
    screenshot_dir: str = ""
    launch_flags: list[str] = Field(default_factory=list)
    default_profile: str = "isolated"
    allow_private_network: bool = False
    allowed_hostnames: list[str] = Field(default_factory=list)
    deny_hostnames: list[str] = Field(default_factory=list)
    allow_user_profile: bool = False
    allow_remote_profile: bool = False
    allow_high_risk_actions: bool = False
    evaluate_enabled: bool = False
    snapshot_defaults: dict[str, object] = Field(default_factory=dict)


class CapabilitySettings(BaseModel):
    """
    【AI Agent 能力配置总入口】
    聚合所有能力维度的配置，统一管理Agent的全部权限、功能、扩展开关
    是系统初始化能力模块的唯一顶层配置
    """
    builtin_tools: BuiltinToolCapabilityConfig = Field(default_factory=BuiltinToolCapabilityConfig)
    skills: SkillCapabilityConfig = Field(default_factory=SkillCapabilityConfig)
    mcp: MCPCapabilityConfig = Field(default_factory=MCPCapabilityConfig)
    extensions: ExtensionCapabilityConfig = Field(default_factory=ExtensionCapabilityConfig)
    browser: BrowserCapabilityConfig = Field(default_factory=BrowserCapabilityConfig)


class StorageSettings(BaseModel):
    sessions_dir: str = ""
    timelines_dir: str = ""
    checkpoints_dir: str = ""


class SubAgentSettings(BaseModel):
    default_max_turns: Optional[int] = None
    max_turns: dict[str, int] = Field(default_factory=dict)
    enforce_orchestrated_edit_contract: bool = True
    require_patch_artifact_for_code_change: bool = True

    def max_turns_for(self, name: str, fallback: int) -> int:
        configured = self.max_turns.get(name, self.default_max_turns)
        if configured is None:
            return fallback
        return max(1, int(configured))


class Settings(BaseModel):
    """
    【AI Agent 系统顶层总配置】
    聚合：环境路径、模型服务、安全策略、能力开关、AI指令
    是整个系统**唯一的、完整的**配置来源
    """
    workspace: Path
    global_dir: Path
    project_dir: Path
    provider: StoredProviderConfig = Field(default_factory=StoredProviderConfig)
    model: StoredModelConfig = Field(default_factory=StoredModelConfig)
    tool_policy: ToolPolicyConfig = Field(default_factory=ToolPolicyConfig)
    capabilities: CapabilitySettings = Field(default_factory=CapabilitySettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    subagents: SubAgentSettings = Field(default_factory=SubAgentSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    learning: LearningSettings = Field(default_factory=LearningSettings)
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    @classmethod
    def load(cls, workspace: Path) -> "Settings":
        # 1. 将工作区路径转换为【绝对路径】，消除相对路径/符号链接风险
        workspace = workspace.resolve()
        # 2. 定义项目专属配置目录：工作区下的隐藏文件夹 .pp-agent
        project_dir = workspace / ".pp-agent"
        # 3. 递归创建项目目录，已存在则不报错（安全创建）
        project_dir.mkdir(parents=True, exist_ok=True)
        # 4. 解析全局配置目录（用户级，跨项目共享）
        global_dir = cls._resolve_global_dir(project_dir)

        # 5. 初始化 Settings 总配置对象（传入核心路径）
        settings = cls(workspace=workspace, global_dir=global_dir, project_dir=project_dir)
        #应用环境变量覆盖和项目配置覆盖，确保最终配置正确反映用户意图和项目需求
        settings._apply_environment_overrides()
        #应用本地配置
        settings._apply_project_config()

        agents_md = workspace / "AGENTS.md"
        system_md = project_dir / "SYSTEM.md"
        if system_md.exists():
            settings.system_prompt = system_md.read_text(encoding="utf-8")
        
        if agents_md.exists():
            settings.system_prompt += "\n\nWorkspace instructions:\n" + agents_md.read_text(encoding="utf-8")
        if settings.memory.file_memory_enable and settings.memory.file_memory_search_enable:
            settings.system_prompt += "\n\nFile memory protocol:\n" + FILE_MEMORY_PROTOCOL_PROMPT
        settings.system_prompt += "\n\nSubagent orchestration protocol:\n" + SUBAGENT_ORCHESTRATION_PROMPT
        return settings

    @staticmethod
    def _resolve_global_dir(project_dir: Path) -> Path:
        """
        【核心】自动解析并创建 全局配置目录（跨项目共享）
        按优先级寻找可写入的目录，Windows 优先，兼容自定义环境变量
        """
        # 1. 获取 Windows 系统的本地应用数据目录（LOCALAPPDATA）
        # 无环境变量时，使用默认路径：用户目录/AppData/Local
        local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        # 2. 定义【候选目录列表】（按优先级从高到低排序）
        candidates = []
        # 优先级1：用户自定义环境变量 PP_AGENT_HOME（最高优先级）
        if os.getenv("PP_AGENT_HOME"):
            candidates.append(Path(os.environ["PP_AGENT_HOME"]))
        # 优先级2：Windows 系统级全局目录
        candidates.extend([
            local_app_data / "pp-agent",
            # 优先级3：项目配置目录内的 global 文件夹（兜底方案）
            project_dir / "global",
        ])
        # 3. 遍历候选目录列表，尝试创建目录，成功则返回
        for candidate in candidates:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except PermissionError:
                continue
        raise PermissionError("Unable to create a writable pp-agent state directory")

    def _apply_environment_overrides(self) -> None:
        """
        【环境变量覆盖配置】
        读取系统环境变量，动态覆盖模型/服务商的默认配置
        仅在环境变量存在时生效，不修改原有默认配置
        """
        if os.getenv("PP_AGENT_BASE_URL"):
            self.provider.base_url = os.environ["PP_AGENT_BASE_URL"]
        if os.getenv("PP_AGENT_MODEL"):
            self.model.model = os.environ["PP_AGENT_MODEL"]
        if os.getenv("PP_AGENT_ENABLE_THINKING"):
            self.model.enable_thinking = os.environ["PP_AGENT_ENABLE_THINKING"].strip().lower() in {"1", "true", "yes", "on"}

    def _apply_project_config(self) -> None:
        """
        加载并应用【项目专属配置文件】
        配置文件路径：工作区/.pp-agent/config.json
        优先级：高于默认配置、环境变量，低于SYSTEM.md
        """
        config_path = self.project_dir / "config.json"
        if not config_path.exists():
            return
        # 读取并解析JSON配置文件
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if "model" in data:
            self.model.model = data["model"]
        if "base_url" in data:
            self.provider.base_url = data["base_url"]
        if "enable_thinking" in data:
            self.model.enable_thinking = bool(data["enable_thinking"])
        if "shell_timeout_seconds" in data:
            self.tool_policy.shell_timeout_seconds = int(data["shell_timeout_seconds"])
        tool_policy = data.get("tool_policy", {})
        if tool_policy:
            self._apply_tool_policy_config(tool_policy)
        tool_confirm = data.get("tool_confirmation", {})
        if "write_file" in tool_confirm:
            self.tool_policy.confirm_write_file = bool(tool_confirm["write_file"])
        if "edit_file" in tool_confirm:
            self.tool_policy.confirm_edit_file = bool(tool_confirm["edit_file"])
        if "run_shell" in tool_confirm:
            self.tool_policy.confirm_run_shell = bool(tool_confirm["run_shell"])
        if "high_risk_plan" in tool_confirm:
            self.tool_policy.confirm_high_risk_plan = bool(tool_confirm["high_risk_plan"])

        capability_config = data.get("capabilities", {})
        if capability_config:
            self._apply_capability_config(capability_config)
        storage_config = data.get("storage", {})
        if storage_config:
            self._apply_storage_config(storage_config)
        subagent_config = data.get("subagents", {})
        if subagent_config:
            self._apply_subagent_config(subagent_config)
        memory_config = data.get("memory", {})
        if memory_config:
            self._apply_memory_config(memory_config)
        learning_config = data.get("learning", {})
        if learning_config:
            self._apply_learning_config(learning_config)

    def _apply_tool_policy_config(self, tool_policy: dict) -> None:
        if "shell_timeout_seconds" in tool_policy:
            self.tool_policy.shell_timeout_seconds = int(tool_policy["shell_timeout_seconds"])
        if "permission_mode" in tool_policy:
            permission_mode = str(tool_policy["permission_mode"])
            if permission_mode not in PERMISSION_MODES:
                raise ValueError(f"Invalid tool_policy.permission_mode: {permission_mode}")
            self.tool_policy.permission_mode = cast(PermissionModeName, permission_mode)
        if "allowed_tools" in tool_policy:
            self.tool_policy.allowed_tools = [str(value) for value in tool_policy["allowed_tools"]]
        if "denied_tools" in tool_policy:
            self.tool_policy.denied_tools = [str(value) for value in tool_policy["denied_tools"]]
        if "ask_tools" in tool_policy:
            self.tool_policy.ask_tools = [str(value) for value in tool_policy["ask_tools"]]
        tool_confirm = tool_policy.get("tool_confirmation", {})
        if "write_file" in tool_confirm:
            self.tool_policy.confirm_write_file = bool(tool_confirm["write_file"])
        if "edit_file" in tool_confirm:
            self.tool_policy.confirm_edit_file = bool(tool_confirm["edit_file"])
        if "run_shell" in tool_confirm:
            self.tool_policy.confirm_run_shell = bool(tool_confirm["run_shell"])
        if "high_risk_plan" in tool_confirm:
            self.tool_policy.confirm_high_risk_plan = bool(tool_confirm["high_risk_plan"])

    def _apply_storage_config(self, storage_config: dict) -> None:
        if "sessions_dir" in storage_config:
            self.storage.sessions_dir = str(storage_config["sessions_dir"])
        if "timelines_dir" in storage_config:
            self.storage.timelines_dir = str(storage_config["timelines_dir"])
        if "checkpoints_dir" in storage_config:
            self.storage.checkpoints_dir = str(storage_config["checkpoints_dir"])

    def _apply_subagent_config(self, subagent_config: dict) -> None:
        if "default_max_turns" in subagent_config:
            self.subagents.default_max_turns = max(1, int(subagent_config["default_max_turns"]))
        if "max_turns" in subagent_config:
            self.subagents.max_turns = {
                str(name): max(1, int(value))
                for name, value in dict(subagent_config["max_turns"]).items()
            }
        if "enforce_orchestrated_edit_contract" in subagent_config:
            self.subagents.enforce_orchestrated_edit_contract = bool(subagent_config["enforce_orchestrated_edit_contract"])
        if "require_patch_artifact_for_code_change" in subagent_config:
            self.subagents.require_patch_artifact_for_code_change = bool(subagent_config["require_patch_artifact_for_code_change"])

    def _apply_capability_config(self, capability_config: dict) -> None:
        """
        解析并应用 config.json 中的 capabilities 能力配置
        逐项覆盖：内置工具、技能、MCP、扩展插件 的所有配置项
        仅覆盖配置文件中存在的字段，不修改未配置的默认值
        """
        #1. 内置工具能力配置
        builtin_tools = capability_config.get("builtin_tools", {})
        if "enable" in builtin_tools:
            self.capabilities.builtin_tools.enable = bool(builtin_tools["enable"])

        #2. 技能能力配置
        skill_config = capability_config.get("skills", {})
        if "enable_project" in skill_config:
            self.capabilities.skills.enable_project = bool(skill_config["enable_project"])
        if "enable_user" in skill_config:
            self.capabilities.skills.enable_user = bool(skill_config["enable_user"])
        if "enable_builtin" in skill_config:
            self.capabilities.skills.enable_builtin = bool(skill_config["enable_builtin"])
        if "custom_directories" in skill_config:
            self.capabilities.skills.custom_directories = [str(value) for value in skill_config["custom_directories"]]
        if "ignored" in skill_config:
            self.capabilities.skills.ignored = [str(value) for value in skill_config["ignored"]]
        if "include" in skill_config:
            self.capabilities.skills.include = [str(value) for value in skill_config["include"]]
        
        #3. MCP能力配置
        mcp_config = capability_config.get("mcp", {})
        if "enable" in mcp_config:
            self.capabilities.mcp.enable = bool(mcp_config["enable"])
        if "config_paths" in mcp_config:
            self.capabilities.mcp.config_paths = [str(value) for value in mcp_config["config_paths"]]
        if "server_filters" in mcp_config:
            self.capabilities.mcp.server_filters = [str(value) for value in mcp_config["server_filters"]]

        #4. 扩展插件能力配置
        extension_config = capability_config.get("extensions", {})
        if "enable_project" in extension_config:
            self.capabilities.extensions.enable_project = bool(extension_config["enable_project"])
        if "enable_user" in extension_config:
            self.capabilities.extensions.enable_user = bool(extension_config["enable_user"])
        if "enable_builtin" in extension_config:
            self.capabilities.extensions.enable_builtin = bool(extension_config["enable_builtin"])
        if "custom_directories" in extension_config:
            self.capabilities.extensions.custom_directories = [str(value) for value in extension_config["custom_directories"]]
        if "ignored" in extension_config:
            self.capabilities.extensions.ignored = [str(value) for value in extension_config["ignored"]]
        if "include" in extension_config:
            self.capabilities.extensions.include = [str(value) for value in extension_config["include"]]

        browser_config = capability_config.get("browser", {})
        if "enable" in browser_config:
            self.capabilities.browser.enable = bool(browser_config["enable"])
        if "browser_executable" in browser_config:
            self.capabilities.browser.browser_executable = str(browser_config["browser_executable"])
        if "user_data_dir" in browser_config:
            self.capabilities.browser.user_data_dir = str(browser_config["user_data_dir"])
        if "screenshot_dir" in browser_config:
            self.capabilities.browser.screenshot_dir = str(browser_config["screenshot_dir"])
        if "launch_flags" in browser_config:
            self.capabilities.browser.launch_flags = [str(value) for value in browser_config["launch_flags"]]
        if "default_profile" in browser_config:
            self.capabilities.browser.default_profile = str(browser_config["default_profile"])
        if "allow_private_network" in browser_config:
            self.capabilities.browser.allow_private_network = bool(browser_config["allow_private_network"])
        if "allowed_hostnames" in browser_config:
            self.capabilities.browser.allowed_hostnames = [str(value).lower() for value in browser_config["allowed_hostnames"]]
        if "deny_hostnames" in browser_config:
            self.capabilities.browser.deny_hostnames = [str(value).lower() for value in browser_config["deny_hostnames"]]
        if "allow_user_profile" in browser_config:
            self.capabilities.browser.allow_user_profile = bool(browser_config["allow_user_profile"])
        if "allow_remote_profile" in browser_config:
            self.capabilities.browser.allow_remote_profile = bool(browser_config["allow_remote_profile"])
        if "allow_high_risk_actions" in browser_config:
            self.capabilities.browser.allow_high_risk_actions = bool(browser_config["allow_high_risk_actions"])
        if "evaluate_enabled" in browser_config:
            self.capabilities.browser.evaluate_enabled = bool(browser_config["evaluate_enabled"])
        if "snapshot_defaults" in browser_config:
            self.capabilities.browser.snapshot_defaults = dict(browser_config["snapshot_defaults"])

    def _apply_memory_config(self, memory_config: dict) -> None:
        if "enable" in memory_config:
            self.memory.enable = bool(memory_config["enable"])
        if "backend" in memory_config:
            self.memory.backend = str(memory_config["backend"])
        if "sqlite_path" in memory_config:
            self.memory.sqlite_path = str(memory_config["sqlite_path"])
        if "chunk_target_tokens" in memory_config:
            self.memory.chunk_target_tokens = int(memory_config["chunk_target_tokens"])
        if "chunk_max_tokens" in memory_config:
            self.memory.chunk_max_tokens = int(memory_config["chunk_max_tokens"])
        if "sqlite_busy_timeout_ms" in memory_config:
            self.memory.sqlite_busy_timeout_ms = int(memory_config["sqlite_busy_timeout_ms"])
        if "embedding_enable" in memory_config:
            self.memory.embedding_enable = bool(memory_config["embedding_enable"])
        if "embedding_provider" in memory_config:
            self.memory.embedding_provider = str(memory_config["embedding_provider"])
        if "embedding_model" in memory_config:
            self.memory.embedding_model = str(memory_config["embedding_model"])
        if "dashscope_api_key_env" in memory_config:
            self.memory.dashscope_api_key_env = str(memory_config["dashscope_api_key_env"])
        if "embedding_batch_size" in memory_config:
            self.memory.embedding_batch_size = int(memory_config["embedding_batch_size"])
        if "vector_enable" in memory_config:
            self.memory.vector_enable = bool(memory_config["vector_enable"])
        if "vector_backend" in memory_config:
            self.memory.vector_backend = str(memory_config["vector_backend"])
        if "chroma_path" in memory_config:
            self.memory.chroma_path = str(memory_config["chroma_path"])
        if "chroma_collection" in memory_config:
            self.memory.chroma_collection = str(memory_config["chroma_collection"])
        if "chroma_collection_per_embedding" in memory_config:
            self.memory.chroma_collection_per_embedding = bool(memory_config["chroma_collection_per_embedding"])
        if "indexing_enable" in memory_config:
            self.memory.indexing_enable = bool(memory_config["indexing_enable"])
        if "indexing_batch_size" in memory_config:
            self.memory.indexing_batch_size = int(memory_config["indexing_batch_size"])
        if "retrieval_enable" in memory_config:
            self.memory.retrieval_enable = bool(memory_config["retrieval_enable"])
        if "retrieval_limit" in memory_config:
            self.memory.retrieval_limit = int(memory_config["retrieval_limit"])
        if "retrieval_same_session_bias" in memory_config:
            self.memory.retrieval_same_session_bias = float(memory_config["retrieval_same_session_bias"])
        if "retrieval_max_per_session" in memory_config:
            self.memory.retrieval_max_per_session = int(memory_config["retrieval_max_per_session"])
        if "retrieval_max_snippets" in memory_config:
            self.memory.retrieval_max_snippets = int(memory_config["retrieval_max_snippets"])
        if "retrieval_max_chars" in memory_config:
            self.memory.retrieval_max_chars = int(memory_config["retrieval_max_chars"])
        if "hybrid_enable" in memory_config:
            self.memory.hybrid_enable = bool(memory_config["hybrid_enable"])
        if "hybrid_keyword_limit" in memory_config:
            self.memory.hybrid_keyword_limit = int(memory_config["hybrid_keyword_limit"])
        if "hybrid_vector_limit" in memory_config:
            self.memory.hybrid_vector_limit = int(memory_config["hybrid_vector_limit"])
        if "recent_dedup_enable" in memory_config:
            self.memory.recent_dedup_enable = bool(memory_config["recent_dedup_enable"])
        if "recent_dedup_use_chunk_metadata" in memory_config:
            self.memory.recent_dedup_use_chunk_metadata = bool(memory_config["recent_dedup_use_chunk_metadata"])
        if "snippet_categorize_enable" in memory_config:
            self.memory.snippet_categorize_enable = bool(memory_config["snippet_categorize_enable"])
        if "reranker_enable" in memory_config:
            self.memory.reranker_enable = bool(memory_config["reranker_enable"])
        if "reranker_backend" in memory_config:
            self.memory.reranker_backend = str(memory_config["reranker_backend"])
        if "reranker_limit" in memory_config:
            self.memory.reranker_limit = int(memory_config["reranker_limit"])
        if "snippet_prioritize_long_term_preferences" in memory_config:
            self.memory.snippet_prioritize_long_term_preferences = bool(memory_config["snippet_prioritize_long_term_preferences"])
        if "snippet_compress_error_stacks" in memory_config:
            self.memory.snippet_compress_error_stacks = bool(memory_config["snippet_compress_error_stacks"])
        if "snippet_path_weight_boost" in memory_config:
            self.memory.snippet_path_weight_boost = float(memory_config["snippet_path_weight_boost"])
        if "file_memory_enable" in memory_config:
            self.memory.file_memory_enable = bool(memory_config["file_memory_enable"])
        if "file_memory_search_enable" in memory_config:
            self.memory.file_memory_search_enable = bool(memory_config["file_memory_search_enable"])
        if "file_memory_root" in memory_config:
            self.memory.file_memory_root = str(memory_config["file_memory_root"])
        if "file_memory_extra_paths" in memory_config:
            self.memory.file_memory_extra_paths = [str(value) for value in memory_config["file_memory_extra_paths"]]
        if "file_memory_index_path" in memory_config:
            self.memory.file_memory_index_path = str(memory_config["file_memory_index_path"])
        if "file_memory_chroma_collection" in memory_config:
            self.memory.file_memory_chroma_collection = str(memory_config["file_memory_chroma_collection"])
        if "file_memory_chunk_target_chars" in memory_config:
            self.memory.file_memory_chunk_target_chars = int(memory_config["file_memory_chunk_target_chars"])
        if "file_memory_chunk_overlap_lines" in memory_config:
            self.memory.file_memory_chunk_overlap_lines = int(memory_config["file_memory_chunk_overlap_lines"])
        if "file_memory_top_k" in memory_config:
            self.memory.file_memory_top_k = int(memory_config["file_memory_top_k"])
        if "file_memory_candidate_multiplier" in memory_config:
            self.memory.file_memory_candidate_multiplier = int(memory_config["file_memory_candidate_multiplier"])
        if "file_memory_vector_weight" in memory_config:
            self.memory.file_memory_vector_weight = float(memory_config["file_memory_vector_weight"])
        if "file_memory_bm25_weight" in memory_config:
            self.memory.file_memory_bm25_weight = float(memory_config["file_memory_bm25_weight"])
        if "file_memory_max_per_file" in memory_config:
            self.memory.file_memory_max_per_file = int(memory_config["file_memory_max_per_file"])
        if "file_memory_snippet_chars" in memory_config:
            self.memory.file_memory_snippet_chars = int(memory_config["file_memory_snippet_chars"])
        if "file_memory_sync_on_search" in memory_config:
            self.memory.file_memory_sync_on_search = bool(memory_config["file_memory_sync_on_search"])
        if "file_memory_allow_remote_embedding" in memory_config:
            self.memory.file_memory_allow_remote_embedding = bool(memory_config["file_memory_allow_remote_embedding"])

    def _apply_learning_config(self, learning_config: dict) -> None:
        if "enable" in learning_config:
            self.learning.enable = bool(learning_config["enable"])
        if "auto_extract" in learning_config:
            self.learning.auto_extract = bool(learning_config["auto_extract"])
        if "auto_apply_memory" in learning_config:
            self.learning.auto_apply_memory = bool(learning_config["auto_apply_memory"])
        if "auto_apply_min_confidence" in learning_config:
            self.learning.auto_apply_min_confidence = str(learning_config["auto_apply_min_confidence"])
        if "project_memory_enable" in learning_config:
            self.learning.project_memory_enable = bool(learning_config["project_memory_enable"])
        if "project_memory_char_limit" in learning_config:
            self.learning.project_memory_char_limit = int(learning_config["project_memory_char_limit"])
        if "detailed_memory_enable" in learning_config:
            self.learning.detailed_memory_enable = bool(learning_config["detailed_memory_enable"])
        if "detailed_memory_char_limit" in learning_config:
            self.learning.detailed_memory_char_limit = int(learning_config["detailed_memory_char_limit"])
        if "detailed_memory_auto_consolidate" in learning_config:
            self.learning.detailed_memory_auto_consolidate = bool(learning_config["detailed_memory_auto_consolidate"])
        if "detailed_memory_sync_index_after_write" in learning_config:
            self.learning.detailed_memory_sync_index_after_write = bool(learning_config["detailed_memory_sync_index_after_write"])
        if "candidate_limit_per_turn" in learning_config:
            self.learning.candidate_limit_per_turn = int(learning_config["candidate_limit_per_turn"])
        if "min_confidence_to_suggest" in learning_config:
            self.learning.min_confidence_to_suggest = str(learning_config["min_confidence_to_suggest"])
        if "llm_extractor_enable" in learning_config:
            self.learning.llm_extractor_enable = bool(learning_config["llm_extractor_enable"])

    def session_store_dir(self) -> Path:
        return self._resolve_runtime_path(
            env_var="PP_AGENT_SESSIONS_DIR",
            configured=self.storage.sessions_dir,
            default=self.project_dir / "sessions",
        )

    def timeline_store_dir(self) -> Path:
        return self._resolve_runtime_path(
            env_var="PP_AGENT_TIMELINES_DIR",
            configured=self.storage.timelines_dir,
            default=self.project_dir / "timelines",
        )

    def checkpoint_store_dir(self) -> Path:
        return self._resolve_runtime_path(
            env_var="PP_AGENT_CHECKPOINTS_DIR",
            configured=self.storage.checkpoints_dir,
            default=self.project_dir / "checkpoints",
        )

    def history_db_path(self) -> Path:
        return self._resolve_runtime_path(
            env_var="PP_AGENT_MEMORY_SQLITE_PATH",
            configured=self.memory.sqlite_path,
            default=self.project_dir / "history.db",
        )

    def chroma_dir_path(self) -> Path:
        return self._resolve_runtime_path(
            env_var="PP_AGENT_CHROMA_PATH",
            configured=self.memory.chroma_path,
            default=self.project_dir / "chroma",
        )

    def file_memory_index_path(self) -> Path:
        return self._resolve_runtime_path(
            env_var="PP_AGENT_FILE_MEMORY_INDEX_PATH",
            configured=self.memory.file_memory_index_path,
            default=self.project_dir / "file-memory.db",
        )

    def file_memory_root_path(self) -> Path:
        configured = self.memory.file_memory_root
        if configured and configured.strip():
            return self._resolve_configured_path(configured)
        return self.workspace

    def _resolve_runtime_path(self, *, env_var: str, configured: str, default: Path) -> Path:
        raw_value = os.getenv(env_var)
        if raw_value and raw_value.strip():
            return self._resolve_configured_path(raw_value)
        if configured and configured.strip():
            return self._resolve_configured_path(configured)
        return default

    def _resolve_configured_path(self, raw_value: str) -> Path:
        path = Path(raw_value).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        return path.resolve(strict=False)
