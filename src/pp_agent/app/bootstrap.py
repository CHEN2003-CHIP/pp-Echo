# @Author: CHEN
# @Desc: PP-Echo 运行时核心模块，负责扩展管理、能力发现、会话创建、存储初始化、MCP集成等核心逻辑
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pp_agent.app.extensions_runtime import discover_extension_resource_roots, load_executable_extensions
from pp_agent.app.resources import load_resource_manifest, manifest_extension_roots, manifest_skill_roots
from pp_agent.app.skills_runtime import SkillRuntime
from pp_agent.capabilities import (
    BuiltinToolCapabilityDiscoveryProvider,
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityDiscoveryProvider,
    SkillCapabilityDiscoveryProvider,
)
from pp_agent.domain.checkpoints import CheckpointEntry
from pp_agent.extensions import ExtensionDescriptor, ExtensionRegistry, load_extensions
from pp_agent.extensions.hooks import LifecycleSubscriber
from pp_agent.extensions.index import extension_search_roots
from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.llm.registry import create_llm_client
from pp_agent.mcp import MCPManager
from pp_agent.mcp.config import load_mcp_server_configs
from pp_agent.runtime.git_checkpoint import GitCheckpointManager
from pp_agent.runtime.hooks import BeforeToolCallDecision, RuntimeHooks
from pp_agent.runtime.lifecycle import CHECKPOINT_BEFORE_CREATE, CHECKPOINT_CREATED
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.runtime.session_host import SessionHost
from pp_agent.skills import skill_search_roots
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.checkpoints import CheckpointStore
from pp_agent.storage.models import StoredModelConfig, StoredProviderConfig
from pp_agent.storage.sessions import SessionRecord, SessionStore
from pp_agent.storage.settings import Settings
from pp_agent.storage.timeline import TimelineStore
from pp_agent.tools.registry import ToolRegistry


@dataclass
class _ExtensionCapabilitySource:
    """
    【私有】扩展能力源数据类
    负责Agent扩展的发现、注册、能力描述生成，是扩展能力接入的核心载体
    """

    # 工作空间根路径
    workspace: Path
    # 用户配置根路径
    user_root: Path
    # 扩展配置对象
    config: object
    # 扩展注册器实例
    registry: ExtensionRegistry
    # 扩展搜索根目录列表，默认空列表
    search_roots: list[object] = field(default_factory=list)

    def discover(self) -> list[CapabilityDescriptor]:
        """
        发现并加载所有扩展，生成扩展能力描述符列表
        :return: 扩展能力描述符集合()
        """
        for descriptor in load_extensions(
            self.workspace,
            self.user_root,
            config=self.config,
            search_roots=self.search_roots or None,
        ).values():
            self.registry.register(descriptor, status="discovered")
        # 过滤MCP适配器扩展，转换为标准能力描述符返回
        return [self._descriptor(binding) for binding in self.registry.list() if binding.descriptor.name != "mcp_adapter"]

    def reload(self) -> None:
        self.registry.clear()

    @staticmethod
    def _descriptor(binding) -> CapabilityDescriptor:
        """
        【私有静态】将扩展绑定对象转换为标准能力描述符
        :param binding: 扩展绑定对象
        :return: 标准化能力描述符
        """
        descriptor = binding.descriptor
        return CapabilityDescriptor(
            kind="extension",
            name=descriptor.name,
            description=descriptor.description,
            source=f"extension:{descriptor.name}",
            path=str(descriptor.path) if descriptor.path else None,
            status=binding.status,
            origin_type=descriptor.origin_type,
            risk_level="low",
            cost_hint="low",
            discoverability="listed",
            metadata={
                "origin": "extension",
                "entrypoint": descriptor.entrypoint,
                "provides": descriptor.provides,
                "root_name": descriptor.root_name,
                "precedence": descriptor.precedence,
                "declared_by_manifest": descriptor.declared_by_manifest,
                "error": binding.error,
                "loaded_tools": list(binding.loaded_tools),
                "loaded_commands": list(binding.loaded_commands),
                "loaded_resources": list(binding.loaded_resources),
                "hook_counts": dict(binding.hook_counts),
                "event_counts": dict(binding.event_counts),
                "resource_roots": {key: list(values) for key, values in binding.resource_roots.items()},
            },
        )


@dataclass
class _MCPExtensionBackend:
    """
    【私有】MCP扩展后端数据类
    负责MCP服务器适配、集成，将MCP工具/资源/提示词暴露为Agent能力
    """

    # 工作空间根路径
    workspace: Path
    # MCP配置对象
    mcp_config: object
    registry: ExtensionRegistry
    # 传输工厂对象，可选
    transport_factory: object | None = None
    # 时间函数对象，可选
    time_fn: object | None = None
    # MCP管理器实例，初始化不赋值，内部使用
    _manager: MCPManager | None = field(default=None, init=False, repr=False)
    # 配置指纹，用于校验配置是否变更，内部使用
    _fingerprint: str | None = field(default=None, init=False, repr=False)

    def discover(self) -> list[CapabilityDescriptor]:
        """
        发现MCP扩展能力，加载MCP服务器并生成能力描述符
        :return: MCP相关能力描述符集合
        """

        # MCP未启用则清空并返回空列表
        if not getattr(self.mcp_config, "enable", False):
            self.reload()
            return []

        # 注册MCP适配器扩展
        extension_descriptor = ExtensionDescriptor(
            name="mcp_adapter",
            description="Expose MCP servers as extension-backed capabilities.",
            entrypoint="pp_agent.mcp",
            provides=["mcp_tool", "mcp_resource", "mcp_prompt"],
            origin_type="builtin",
            root_name="mcp_backend",
            precedence=-1,
            declared_by_manifest=False,
        )
        self.registry.register(extension_descriptor, status="loaded")
        try:
            # 获取当前配置的MCP管理器
            manager = self._manager_for_current_config()
        except Exception as exc:  # pragma: no cover - defensive path
            self.registry.mark_errored("mcp_adapter", str(exc))
            return []
        
        # 初始化MCP适配器能力描述符
        descriptors: list[CapabilityDescriptor] = [
            CapabilityDescriptor(
                kind="extension",
                name=extension_descriptor.name,
                description=extension_descriptor.description,
                source=f"extension:{extension_descriptor.name}",
                status="loaded",
                origin_type=extension_descriptor.origin_type,
                risk_level="low",
                cost_hint="low",
                discoverability="listed",
                metadata={
                    "origin": "extension",
                    "entrypoint": extension_descriptor.entrypoint,
                    "provides": extension_descriptor.provides,
                    "root_name": extension_descriptor.root_name,
                    "precedence": extension_descriptor.precedence,
                    "declared_by_manifest": extension_descriptor.declared_by_manifest,
                    "error": None,
                    "loaded_tools": [],
                    "loaded_commands": [],
                    "loaded_resources": [],
                    "hook_counts": {},
                    "event_counts": {},
                    "resource_roots": {},
                },
            )
        ]
        loaded_tools: list[str] = []
        loaded_resources: list[str] = []
        # 遍历所有MCP服务器，解析工具、资源、提示词能力
        for server_name in manager.server_names():
            if not self._includes_server(server_name):
                continue
            # 处理MCP工具
            for tool in manager.list_mcp_tools(server_name):
                qualified = self._qualified_name(server_name, tool.name)
                loaded_tools.append(qualified)
                descriptors.append(
                    #能力描述清单
                    CapabilityDescriptor(
                        kind="mcp_tool",
                        name=qualified,
                        description=tool.description,
                        source=f"extension:mcp_adapter:{server_name}:tool:{tool.name}",
                        status="loaded",
                        origin_type="extension",
                        risk_level=tool.risk_level,
                        cost_hint="medium" if tool.is_remote else "low",
                        discoverability="listed",
                        metadata={
                            "origin": "mcp_tool",
                            "origin_extension": "mcp_adapter",
                            "server_name": server_name,
                            "name": tool.name,
                            "qualified_name": qualified,
                            "is_remote": tool.is_remote,
                            "requires_auth": tool.requires_auth,
                            "is_destructive": tool.is_destructive,
                            "approval_mode": tool.approval_mode,
                            "input_schema": tool.input_schema,
                        },
                    )
                )
            for resource in manager.list_mcp_resources(server_name):
                resource_name = resource.name or resource.uri
                qualified = self._qualified_name(server_name, resource_name)
                loaded_resources.append(qualified)
                descriptors.append(
                    CapabilityDescriptor(
                        kind="mcp_resource",
                        name=qualified,
                        description=resource.description,
                        source=f"extension:mcp_adapter:{server_name}:resource:{resource.uri}",
                        status="loaded",
                        origin_type="extension",
                        risk_level=resource.risk_level,
                        cost_hint="medium" if resource.is_remote else "low",
                        discoverability="listed",
                        metadata={
                            "origin": "mcp_resource",
                            "origin_extension": "mcp_adapter",
                            "server_name": server_name,
                            "name": resource.name,
                            "qualified_name": qualified,
                            "uri": resource.uri,
                            "mime_type": resource.mime_type,
                            "is_remote": resource.is_remote,
                            "requires_auth": resource.requires_auth,
                            "approval_mode": resource.approval_mode,
                        },
                    )
                )
            for prompt in manager.list_mcp_prompts(server_name):
                qualified = self._qualified_name(server_name, prompt.name)
                loaded_resources.append(qualified)
                descriptors.append(
                    CapabilityDescriptor(
                        kind="mcp_prompt",
                        name=qualified,
                        description=prompt.description,
                        source=f"extension:mcp_adapter:{server_name}:prompt:{prompt.name}",
                        status="loaded",
                        origin_type="extension",
                        risk_level=prompt.risk_level,
                        cost_hint="medium" if prompt.is_remote else "low",
                        discoverability="listed",
                        metadata={
                            "origin": "mcp_prompt",
                            "origin_extension": "mcp_adapter",
                            "server_name": server_name,
                            "name": prompt.name,
                            "qualified_name": qualified,
                            "is_remote": prompt.is_remote,
                            "requires_auth": prompt.requires_auth,
                            "approval_mode": prompt.approval_mode,
                            "arguments_schema": prompt.arguments_schema,
                        },
                    )
                )
        # 更新MCP适配器扩展的加载状态
        self.registry.mark_loaded(
            "mcp_adapter",
            loaded_tools=loaded_tools,
            loaded_commands=[],
            loaded_resources=loaded_resources,
            hook_counts={},
            event_counts={},
            resource_roots={},
        )
        descriptors[0].metadata["loaded_tools"] = list(loaded_tools)
        descriptors[0].metadata["loaded_commands"] = []
        descriptors[0].metadata["loaded_resources"] = list(loaded_resources)
        descriptors[0].metadata["hook_counts"] = {}
        descriptors[0].metadata["event_counts"] = {}
        descriptors[0].metadata["resource_roots"] = {}
        return descriptors

    def reload(self) -> None:
        """重新加载MCP扩展，关闭所有会话、重置管理器和配置指纹"""
        if self._manager is not None:
            self._manager.close_all_sessions()
        binding = self.registry.get("mcp_adapter")
        if binding is not None:
            self.registry.register(binding.descriptor, status="discovered")
        self._manager = None
        self._fingerprint = None

    def _manager_for_current_config(self) -> MCPManager:
        """
        【私有】根据当前配置创建/获取MCP管理器，配置变更则重建
        :return: MCP管理器实例
        """
        project_dir = self.workspace.resolve() / ".pp-agent"
        config_paths = getattr(self.mcp_config, "resolved_config_paths")(project_dir)
        servers = [
            server
            for server in load_mcp_server_configs(project_dir, config_paths=config_paths)
            if self._includes_server(server.name)
        ]
        fingerprint = json.dumps([server.model_dump(mode="json") for server in servers], sort_keys=True)
        if self._manager is None or fingerprint != self._fingerprint:
            if self._manager is not None:
                self._manager.close_all_sessions()
            self._manager = MCPManager(servers, transport_factory=self.transport_factory, time_fn=self.time_fn)
            self._fingerprint = fingerprint
        return self._manager

    def _includes_server(self, server_name: str) -> bool:
        return getattr(self.mcp_config, "includes_server")(server_name)

    @staticmethod
    def _qualified_name(server_name: str, name: str) -> str:
        return f"{server_name}.{name}"


def load_settings(workspace: Path) -> Settings:
    """
    加载工作空间的全局配置
    :param workspace: 工作空间路径
    :return: 配置实例
    """
    return Settings.load(workspace)


def create_session_store(settings: Settings) -> SessionStore:
    """
    创建会话存储实例，兼容全局/项目目录，处理权限异常
    :param settings: 配置实例
    :return: 会话存储实例
    :raises PermissionError: 无写入权限时抛出
    """
    candidates = [settings.global_dir / "sessions", settings.project_dir / "global" / "sessions"]
    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            return SessionStore(candidate)
        except PermissionError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise PermissionError("Unable to create a writable session tree store")


def session_store_for(workspace: Path) -> SessionStore:
    """
    根据工作空间获取会话存储实例
    :param workspace: 工作空间路径
    :return: 会话存储实例
    """
    return create_session_store(load_settings(workspace))


def timeline_store_for(workspace: Path) -> TimelineStore:
    """
    根据工作空间获取时间线存储实例
    :param workspace: 工作空间路径
    :return: 时间线存储实例
    :raises PermissionError: 无写入权限时抛出
    """
    settings = load_settings(workspace)
    candidates = [settings.global_dir / "timelines", settings.project_dir / "global" / "timelines"]
    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            return TimelineStore(candidate)
        except PermissionError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise PermissionError("Unable to create a writable timeline store")


def pending_action_store_for(workspace: Path) -> PendingActionStore:
    """
    根据工作空间获取待执行动作存储实例
    :param workspace: 工作空间路径
    :return: 待执行动作存储实例
    """
    return PendingActionStore(workspace.resolve() / ".pp-agent" / "pending-edits")


def checkpoint_store_for(workspace: Path) -> CheckpointStore:
    """
    根据工作空间获取检查点存储实例
    :param workspace: 工作空间路径
    :return: 检查点存储实例
    :raises PermissionError: 无写入权限时抛出
    """
    settings = load_settings(workspace)
    candidates = [settings.global_dir / "checkpoints", settings.project_dir / "global" / "checkpoints"]
    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            return CheckpointStore(candidate)
        except PermissionError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise PermissionError("Unable to create a writable checkpoint store")


def create_tool_registry(workspace: Path) -> ToolRegistry:
    """
    创建工具注册器实例
    :param workspace: 工作空间路径
    :return: 工具注册器实例
    """
    settings = load_settings(workspace)
    return ToolRegistry(workspace, policy=settings.tool_policy)


def create_capability_catalog(
    workspace: Path,
    *,
    include_mcp: Optional[bool] = None,
    transport_factory=None,
    time_fn=None,
) -> CapabilityCatalog:
    """
    创建能力目录，整合所有能力提供者
    :param workspace: 工作空间路径
    :param include_mcp: 是否包含MCP能力，可选
    :param transport_factory: MCP传输工厂，可选
    :param time_fn: 时间函数，可选
    :return: 能力目录实例
    """
    settings = load_settings(workspace)
    providers = create_capability_providers(
        workspace,
        settings=settings,
        include_mcp=include_mcp,
        transport_factory=transport_factory,
        time_fn=time_fn,
    )
    return CapabilityCatalog(providers)


def create_capability_catalog_with_mcp(
    workspace: Path,
    *,
    transport_factory=None,
    time_fn=None,
) -> CapabilityCatalog:
    """
    创建包含MCP能力的能力目录
    :param workspace: 工作空间路径
    :param transport_factory: MCP传输工厂，可选
    :param time_fn: 时间函数，可选
    :return: 能力目录实例
    """
    return create_capability_catalog(workspace, include_mcp=True, transport_factory=transport_factory, time_fn=time_fn)


def create_capability_providers(
    workspace: Path,
    *,
    settings: Optional[Settings] = None,
    include_mcp: Optional[bool] = None,
    transport_factory=None,
    time_fn=None,
) -> list[CapabilityDiscoveryProvider]:
    """
    创建所有能力发现提供者（技能、扩展、内置工具、MCP）
    :param workspace: 工作空间路径
    :param settings: 配置实例，可选
    :param include_mcp: 是否包含MCP，可选
    :param transport_factory: MCP传输工厂，可选
    :param time_fn: 时间函数，可选
    :return: 能力发现提供者列表
    """
    settings = settings or load_settings(workspace)
    registry = ToolRegistry(workspace, policy=settings.tool_policy)
    extension_registry = ExtensionRegistry()
    skill_roots = _skill_roots_for(workspace.resolve(), settings)
    extension_roots = _extension_roots_for(workspace.resolve(), settings)
    providers: list[CapabilityDiscoveryProvider] = [
        SkillCapabilityDiscoveryProvider(
            workspace=workspace.resolve(),
            user_root=settings.global_dir,
            config=settings.capabilities.skills,
            search_roots=skill_roots,
        ),
        _ExtensionCapabilitySource(
            workspace=workspace.resolve(),
            user_root=settings.global_dir,
            config=settings.capabilities.extensions,
            registry=extension_registry,
            search_roots=extension_roots,
        ),
        BuiltinToolCapabilityDiscoveryProvider(
            registry=registry,
            enabled=settings.capabilities.builtin_tools.enable,
        ),
    ]
    mcp_enabled = settings.capabilities.mcp.enable if include_mcp is None else include_mcp
    if mcp_enabled:
        mcp_config = settings.capabilities.mcp.model_copy(deep=True)
        mcp_config.enable = True
        providers.append(
            _MCPExtensionBackend(
                workspace=workspace.resolve(),
                mcp_config=mcp_config,
                registry=extension_registry,
                transport_factory=transport_factory,
                time_fn=time_fn,
            )
        )
    return providers


def create_mcp_manager(
    workspace: Path,
    *,
    transport_factory=None,
    time_fn=None,
) -> MCPManager:
    """
    创建MCP管理器实例
    :param workspace: 工作空间路径
    :param transport_factory: 传输工厂，可选
    :param time_fn: 时间函数，可选
    :return: MCP管理器实例
    """
    settings = load_settings(workspace)
    config_paths = settings.capabilities.mcp.resolved_config_paths(settings.project_dir)
    return MCPManager.from_workspace(workspace, transport_factory=transport_factory, time_fn=time_fn, config_paths=config_paths)


def provider_config_for_llm(config: StoredProviderConfig) -> ProviderConfig:
    """
    转换存储的提供者配置为LLM运行时配置
    :param config: 存储的提供者配置
    :return: 运行时提供者配置
    """
    return ProviderConfig(**config.model_dump(mode="python"))


def model_config_for_llm(config: StoredModelConfig) -> ModelConfig:
    """
    转换存储的模型配置为LLM运行时配置
    :param config: 存储的模型配置
    :return: 运行时模型配置
    """
    return ModelConfig(**config.model_dump(mode="python"))


def confirm_tool_call(tool_name: str, args: dict) -> bool:
    """
    工具调用确认回调，支持命令行交互确认
    :param tool_name: 工具名称
    :param args: 工具参数
    :return: 确认通过返回True
    """
    try:
        import typer
    except ImportError:  # pragma: no cover
        typer = None
    preview = ", ".join(f"{key}={value!r}" for key, value in args.items())
    if typer:
        return typer.confirm(f"Allow tool `{tool_name}` with args: {preview}?", default=False)
    answer = input(f"Allow tool {tool_name} with args: {preview}? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def create_runtime_from_record(
    workspace: Path,
    record: SessionRecord,
    lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
) -> AgentRuntime:
    """
    根据会话记录创建Agent运行时实例
    :param workspace: 工作空间路径
    :param record: 会话记录
    :param lifecycle_subscribers: 生命周期订阅器，可选
    :return: Agent运行时实例
    """
    settings = load_settings(workspace)
    session_store = session_store_for(workspace)
    tool_registry = ToolRegistry(workspace, policy=settings.tool_policy)
    runtime_hooks = RuntimeHooks()
    agent = AgentRuntime(
        llm_client=create_llm_client(
            provider=provider_config_for_llm(settings.provider),
            model=model_config_for_llm(record.model),
        ),
        tool_registry=tool_registry,
        session_store=session_store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=confirm_tool_call,
        initial_compaction=record.compaction,
        initial_pending_tool_calls=record.pending_tool_calls,
        initial_pending_plan_token=record.pending_plan_token,
        initial_queued_messages=record.queued_messages,
        require_plan_approval=settings.tool_policy.confirm_high_risk_plan,
        runtime_hooks=runtime_hooks,
        timeline_store=timeline_store_for(workspace),
    )
    # 安装自动检查点钩子
    _install_auto_checkpoint_hook(
        agent=agent,
        workspace=workspace,
        manager=GitCheckpointManager(workspace, checkpoint_store_for(workspace), session_store),
    )
    # 保存运行时钩子基线快照
    setattr(agent, "_baseline_runtime_hooks_snapshot", agent.runtime_hooks.snapshot())
    # 加载可执行扩展
    extension_runtime = load_executable_extensions(
        workspace,
        settings=settings,
        tool_registry=tool_registry,
        runtime_hooks=agent.runtime_hooks,
        search_roots=_extension_roots_for(workspace.resolve(), settings),
    )
    # 发现扩展资源根目录
    extension_resource_roots = discover_extension_resource_roots(extension_runtime, workspace.resolve(), reason="startup")
    skill_runtime = SkillRuntime(
        workspace=workspace.resolve(),
        user_root=settings.global_dir,
        config=settings.capabilities.skills,
        search_roots=_skill_roots_for(workspace.resolve(), settings, extra_paths=extension_resource_roots["skill_paths"]),
    )
    # 注册上下文转换钩子
    agent.runtime_hooks.transform_context_hooks.append(skill_runtime.transform_context)
    setattr(agent, "extension_registry", extension_runtime.registry)
    setattr(agent, "extension_commands", extension_runtime.commands)
    setattr(agent, "extension_resources", extension_runtime.resources)
    setattr(agent, "extension_resource_roots", extension_resource_roots)
    setattr(agent, "mcp_runtime", extension_runtime.mcp_runtime)
    setattr(agent, "skill_runtime", skill_runtime)
    setattr(agent, "_extension_runtime", extension_runtime)
    for subscriber in lifecycle_subscribers or []:
        agent.subscribe(subscriber)
    return agent


def reload_runtime_extensions(
    agent: AgentRuntime,
    workspace: Path,
    *,
    include_mcp: Optional[bool] = None,
    transport_factory=None,
    time_fn=None,
) -> dict[str, object]:
    """
    重新加载运行时扩展，重置缓存、重建扩展/技能实例
    :param agent: Agent运行时实例
    :param workspace: 工作空间路径
    :param include_mcp: 是否包含MCP，可选
    :param transport_factory: MCP传输工厂，可选
    :param time_fn: 时间函数，可选
    :return: 扩展加载统计信息
    """
    settings = load_settings(workspace)
    previous_runtime = getattr(agent, "_extension_runtime", None)
    if previous_runtime is not None:
        previous_runtime.close()
    agent.tool_registry.reset_dynamic_registrations()
    extension_commands = getattr(agent, "extension_commands", None)
    if extension_commands is not None:
        extension_commands.clear()
    extension_resources = getattr(agent, "extension_resources", None)
    if isinstance(extension_resources, dict):
        extension_resources.clear()
    extension_registry = getattr(agent, "extension_registry", None)
    if extension_registry is not None:
        extension_registry.clear()
    baseline_snapshot = getattr(agent, "_baseline_runtime_hooks_snapshot", None)
    if baseline_snapshot is not None:
        agent.runtime_hooks.restore(baseline_snapshot)
    extension_runtime = load_executable_extensions(
        workspace,
        settings=settings,
        tool_registry=agent.tool_registry,
        runtime_hooks=agent.runtime_hooks,
        search_roots=_extension_roots_for(workspace.resolve(), settings),
        include_mcp=include_mcp,
        transport_factory=transport_factory,
        time_fn=time_fn,
    )
    extension_resource_roots = discover_extension_resource_roots(extension_runtime, workspace.resolve(), reason="reload")
    skill_runtime = SkillRuntime(
        workspace=workspace.resolve(),
        user_root=settings.global_dir,
        config=settings.capabilities.skills,
        search_roots=_skill_roots_for(workspace.resolve(), settings, extra_paths=extension_resource_roots["skill_paths"]),
    )
    agent.runtime_hooks.transform_context_hooks.append(skill_runtime.transform_context)
    setattr(agent, "extension_registry", extension_runtime.registry)
    setattr(agent, "extension_commands", extension_runtime.commands)
    setattr(agent, "extension_resources", extension_runtime.resources)
    setattr(agent, "extension_resource_roots", extension_resource_roots)
    setattr(agent, "mcp_runtime", extension_runtime.mcp_runtime)
    setattr(agent, "skill_runtime", skill_runtime)
    setattr(agent, "_extension_runtime", extension_runtime)
    builtin_tool_names = {
        "read_file",
        "write_file",
        "edit_file",
        "preview_pending_action",
        "approve_pending_action",
        "reject_pending_action",
        "list_pending_actions",
        "list_files",
        "search_text",
        "grep_code",
        "git_status",
        "git_diff_worktree",
        "run_shell",
    }
    return {
        "extension_count": len(extension_runtime.registry.items),
        "command_count": len(extension_runtime.commands.commands),
        "resource_count": sum(len(values) for values in extension_runtime.resources.values()),
        "tool_count": len([name for name in agent.tool_registry.metadata() if name not in builtin_tool_names]),
        "skill_count": len(skill_runtime.available_skills()),
        "active_skill_count": len(skill_runtime.active_skills()),
        "mcp_enabled": extension_runtime.mcp_runtime is not None,
        "mcp_discovered": extension_runtime.mcp_runtime.status()["discovered"] if extension_runtime.mcp_runtime is not None else False,
    }


def session_defaults_for(workspace: Path) -> dict[str, object]:
    """
    获取会话默认配置（系统提示词、模型）
    :param workspace: 工作空间路径
    :return: 会话默认配置字典
    """
    settings = load_settings(workspace)
    return {"system_prompt": settings.system_prompt, "model": settings.model.model_copy(deep=True)}


def create_session_host(workspace: Path) -> SessionHost:
    """
    创建会话宿主实例，统一管理会话生命周期
    :param workspace: 工作空间路径
    :return: 会话宿主实例
    """
    _ = workspace
    return SessionHost(
        runtime_factory=create_runtime_from_record,
        session_store_factory=session_store_for,
        pending_action_store_factory=pending_action_store_for,
        session_defaults_factory=session_defaults_for,
        checkpoint_store_factory=checkpoint_store_for,
    )


def build_agent(
    workspace: Path,
    session_id: Optional[str] = None,
    lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
) -> AgentRuntime:
    """
    构建Agent运行时（创建新会话/恢复历史会话）
    :param workspace: 工作空间路径
    :param session_id: 会话ID，可选（不传则创建新会话）
    :param lifecycle_subscribers: 生命周期订阅器，可选
    :return: Agent运行时实例
    """
    host = create_session_host(workspace)
    if session_id:
        return host.restore_session(workspace, session_id, lifecycle_subscribers=lifecycle_subscribers)
    return host.create_session(workspace, lifecycle_subscribers=lifecycle_subscribers)


def switch_session_head(workspace: Path, session_id: str, head_id: Optional[str], subscribers: Optional[list[LifecycleSubscriber]] = None) -> str:
    """
    切换会话的头节点（版本回滚/切换）
    :param workspace: 工作空间路径
    :param session_id: 会话ID
    :param head_id: 头节点ID
    :param subscribers: 生命周期订阅器，可选
    :return: 切换后的会话ID
    """
    host = create_session_host(workspace)
    runtime = host.switch_session(workspace, session_id, session_id, target_head_id=head_id, lifecycle_subscribers=subscribers)
    return runtime.session_id


def fork_session(workspace: Path, source_session_id: str, source_turn_id: Optional[str] = None, subscribers: Optional[list[LifecycleSubscriber]] = None) -> str:
    """
    从指定会话分叉出新会话
    :param workspace: 工作空间路径
    :param source_session_id: 源会话ID
    :param source_turn_id: 源回合ID，可选
    :param subscribers: 生命周期订阅器，可选
    :return: 新会话ID
    """
    host = create_session_host(workspace)
    result = host.fork_session(workspace, source_session_id, head_id=source_turn_id, lifecycle_subscribers=subscribers)
    return result.session_id


def view_session_tree(workspace: Path, session_id: Optional[str] = None, subscribers: Optional[list[LifecycleSubscriber]] = None) -> None:
    """
    查看会话树结构（版本历史）
    :param workspace: 工作空间路径
    :param session_id: 会话ID，可选
    :param subscribers: 生命周期订阅器，可选
    """
    create_session_host(workspace).get_tree(workspace, session_id=session_id, lifecycle_subscribers=subscribers)


def rewind_session_with_events(
    workspace: Path,
    source_session_id: str,
    *,
    message_count: Optional[int] = None,
    turn_count: Optional[int] = None,
    subscribers: Optional[list[LifecycleSubscriber]] = None,
) -> str:
    """
    回滚会话（按消息数/回合数）
    :param workspace: 工作空间路径
    :param source_session_id: 源会话ID
    :param message_count: 回滚消息数，可选
    :param turn_count: 回滚回合数，可选
    :param subscribers: 生命周期订阅器，可选
    :return: 回滚后的会话ID
    """
    result = create_session_host(workspace).rewind_session(
        workspace,
        source_session_id,
        message_count=message_count,
        turn_count=turn_count,
        lifecycle_subscribers=subscribers,
    )
    return result.session_id


def _skill_roots_for(
    workspace: Path,
    settings: Settings,
    extra_paths: Optional[list[Path]] = None,
) -> list[object]:
    """
    【私有】获取技能搜索根目录，整合清单、扩展、自定义路径
    :param workspace: 工作空间路径
    :param settings: 配置实例
    :param extra_paths: 额外路径，可选
    :return: 技能根目录列表
    """
    manifest = load_resource_manifest(settings.project_dir)
    roots = skill_search_roots(workspace, settings.global_dir, config=settings.capabilities.skills)
    replaced = _replace_project_skill_roots(roots, settings, manifest.skills)
    return _append_extension_skill_roots(replaced, extra_paths or [])


def _extension_roots_for(workspace: Path, settings: Settings) -> list[object]:
    """
    【私有】获取扩展搜索根目录，整合清单路径
    :param workspace: 工作空间路径
    :param settings: 配置实例
    :return: 扩展根目录列表
    """
    manifest = load_resource_manifest(settings.project_dir)
    roots = extension_search_roots(workspace, settings.global_dir, config=settings.capabilities.extensions)
    return _replace_project_extension_roots(roots, settings, manifest.extensions)


def _replace_project_skill_roots(roots: list[object], settings: Settings, manifest_entries: list[str]) -> list[object]:
    """
    【私有】替换项目技能根目录为清单配置的路径
    :param roots: 原始根目录列表
    :param settings: 配置实例
    :param manifest_entries: 清单条目
    :return: 替换后的根目录列表
    """
    if not manifest_entries:
        return roots
    custom_count = len(settings.capabilities.skills.custom_directories)
    replaced = [root for root in roots if root.origin_type != "project"]
    replaced.extend(manifest_skill_roots(settings.project_dir, manifest_entries, precedence_start=custom_count))
    return replaced


def _append_extension_skill_roots(roots: list[object], extra_paths: list[Path]) -> list[object]:
    """
    【私有】追加扩展技能根目录
    :param roots: 原始根目录列表
    :param extra_paths: 额外路径
    :return: 追加后的根目录列表
    """
    if not extra_paths:
        return roots
    existing = {str(getattr(root, "path", "")) for root in roots}
    precedence = max((int(getattr(root, "precedence", -1)) for root in roots), default=-1) + 1
    for path in extra_paths:
        candidate = path.resolve() if path.exists() else path
        if str(candidate) in existing:
            continue
        roots.append(
            type(
                "SkillRoot",
                (),
                {
                    "path": candidate,
                    "origin_type": "extension",
                    "root_name": candidate.name or "extension_skills",
                    "precedence": precedence,
                    "declared_by_manifest": False,
                    "discovery_root": str(candidate),
                    "discovery_mode": "extension_resource",
                },
            )()
        )
        existing.add(str(candidate))
        precedence += 1
    return roots


def _replace_project_extension_roots(roots: list[object], settings: Settings, manifest_entries: list[str]) -> list[object]:
    """
    【私有】替换项目扩展根目录为清单配置的路径
    :param roots: 原始根目录列表
    :param settings: 配置实例
    :param manifest_entries: 清单条目
    :return: 替换后的根目录列表
    """
    if not manifest_entries:
        return roots
    custom_count = len(settings.capabilities.extensions.custom_directories)
    replaced = [root for root in roots if getattr(root, "origin_type", None) != "project"]
    replaced.extend(manifest_extension_roots(settings.project_dir, manifest_entries, precedence_start=custom_count))
    return replaced


def _install_auto_checkpoint_hook(*, agent: AgentRuntime, workspace: Path, manager: GitCheckpointManager) -> None:
    """
    【私有】安装自动检查点钩子，高危工具调用前自动创建快照
    :param agent: Agent运行时实例
    :param workspace: 工作空间路径
    :param manager: Git检查点管理器
    """
    def before_tool_call(state, call, _registry):
        if not _should_auto_checkpoint(workspace, call.name, call.arguments):
            return BeforeToolCallDecision(action="allow")
        if not manager.is_git_repository():
            return BeforeToolCallDecision(action="allow")
        turn_key = f"turn-{state.turn.turn_id}"
        if getattr(agent, "_auto_checkpoint_turn_key", None) == turn_key:
            return BeforeToolCallDecision(action="allow")
        head_id, turn_id = manager.current_head_context(agent.session_id)
        list(
            agent._emit(
                agent._event(
                    CHECKPOINT_BEFORE_CREATE,
                    details={
                        "checkpoint_id": None,
                        "snapshot_type": "head_snapshot",
                        "session_id": agent.session_id,
                        "head_id": head_id,
                        "turn_id": turn_id,
                        "reason": f"auto:{call.name}",
                        "has_dirty_workspace": False,
                        "affected_file_count": 0,
                    },
                )
            )
        )
        entry = manager.create_head_snapshot(
            session_id=agent.session_id,
            head_id=head_id,
            turn_id=turn_id,
            reason=f"auto:{call.name}",
            summary=f"Automatic checkpoint before {call.name}",
        )
        setattr(agent, "_auto_checkpoint_turn_key", turn_key)
        list(agent._emit(agent._event(CHECKPOINT_CREATED, details=_checkpoint_event_details(entry))))
        return BeforeToolCallDecision(action="allow", details={"checkpoint_id": entry.checkpoint_id})

    agent.runtime_hooks.before_tool_call_hooks.insert(0, before_tool_call)


def _should_auto_checkpoint(workspace: Path, tool_name: str, arguments: dict) -> bool:
    """
    【私有】判断是否需要自动创建检查点（文件修改、shell执行等高危操作）
    :param workspace: 工作空间路径
    :param tool_name: 工具名称
    :param arguments: 工具参数
    :return: 需要检查点返回True
    """
    if tool_name in {"write_file", "edit_file"}:
        return bool(arguments.get("apply"))
    if tool_name == "run_shell":
        return bool(arguments.get("apply"))
    if tool_name != "approve_pending_action":
        return False
    token = arguments.get("token")
    if not token:
        return False
    try:
        payload = pending_action_store_for(workspace).load(token)
    except FileNotFoundError:
        return False
    return payload["action_type"] in {"write_file", "edit_file", "run_shell"}


def _checkpoint_event_details(entry: CheckpointEntry) -> dict[str, object]:
    return {
        "checkpoint_id": entry.checkpoint_id,
        "snapshot_type": entry.snapshot_type,
        "session_id": entry.session_id,
        "head_id": entry.head_id,
        "turn_id": entry.turn_id,
        "reason": entry.reason,
        "has_dirty_workspace": entry.file_stats.has_dirty_workspace,
        "affected_file_count": entry.file_stats.changed_file_count,
    }
