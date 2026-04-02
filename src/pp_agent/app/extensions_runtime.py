from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.extensions import (
    ExtensionCommandRegistry,
    ExtensionDescriptor,
    ExtensionRegistry,
    LoadedExtension,
    load_extension_entrypoint,
    load_extensions,
)
from pp_agent.mcp import MCPManager
from pp_agent.runtime.hooks import RuntimeHooks
from pp_agent.runtime.state import AgentState
from pp_agent.storage.settings import Settings
from pp_agent.tools.base import ToolExecutionResult
from pp_agent.tools.registry import ToolRegistry


@dataclass
class MCPRuntime:
    workspace: Path
    settings: Settings
    tool_registry: ToolRegistry
    registry: ExtensionRegistry
    transport_factory: object | None = None
    time_fn: object | None = None
    _manager: MCPManager | None = field(default=None, init=False, repr=False)
    _registered_tool_names: list[str] = field(default_factory=list, init=False, repr=False)
    _resource_names: list[str] = field(default_factory=list, init=False, repr=False)
    _server_summaries: dict[str, dict[str, object]] = field(default_factory=dict, init=False, repr=False)
    _discovered_servers: set[str] = field(default_factory=set, init=False, repr=False)
    _last_auto_servers: list[str] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self.registry.register(self._descriptor(), status="discovered")

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "server_count": len(self._manager_or_config_names()),
            "servers": self._manager_or_config_names(),
            "discovered": bool(self._discovered_servers),
            "active_sessions": self._manager.active_session_names() if self._manager is not None else [],
            "tool_count": len(self._registered_tool_names),
            "resource_count": len(self._resource_names),
            "auto_servers": list(self._last_auto_servers),
        }

    def list_servers(self) -> list[dict[str, object]]:
        self.ensure_discovered()
        return [dict(self._server_summaries[name]) for name in sorted(self._server_summaries)]

    def call_tool(self, qualified_name: str, arguments: dict[str, object]) -> ToolExecutionResult:
        if "." not in qualified_name:
            raise ValueError("MCP tool name must be qualified as <server>.<tool>")
        server_name, tool_name = qualified_name.split(".", 1)
        self.ensure_server_ready(server_name)
        result = self._manager_for_current_config().call_mcp_tool(server_name, tool_name, arguments)
        return _mcp_result_to_tool_execution(result, tool_name=qualified_name)

    def reload(self) -> None:
        if self._manager is not None:
            self._manager.close_all_sessions()
        self._manager = None
        self._registered_tool_names = []
        self._resource_names = []
        self._server_summaries = {}
        self._discovered_servers = set()
        self._last_auto_servers = []
        self.registry.register(self._descriptor(), status="discovered")

    def close(self) -> None:
        if self._manager is not None:
            self._manager.close_all_sessions()
        self._manager = None

    def ensure_discovered(self) -> None:
        for server_name in self._manager_for_current_config().server_names():
            if self.settings.capabilities.mcp.includes_server(server_name):
                self.ensure_server_ready(server_name)

    def ensure_server_ready(self, server_name: str) -> None:
        if server_name in self._discovered_servers:
            return
        manager = self._manager_for_current_config()
        if server_name not in manager.server_names():
            raise ValueError(f"Unknown MCP server: {server_name}")
        if not self.settings.capabilities.mcp.includes_server(server_name):
            raise ValueError(f"MCP server is filtered out: {server_name}")
        tools = manager.list_mcp_tools(server_name)
        resources = manager.list_mcp_resources(server_name)
        prompts = manager.list_mcp_prompts(server_name)
        for tool in tools:
            qualified_name = f"{server_name}.{tool.name}"
            if qualified_name in self._registered_tool_names:
                continue
            self._registered_tool_names.append(qualified_name)
            self.tool_registry.register_function_tool(
                name=qualified_name,
                description=tool.description,
                parameters=tool.input_schema or {"type": "object", "properties": {}},
                executor=lambda _workspace, arguments, server=server_name, tool_name=tool.name: _mcp_result_to_tool_execution(
                    manager.call_mcp_tool(server, tool_name, arguments),
                    tool_name=f"{server}.{tool_name}",
                ),
                category="mcp",
                requires_confirmation=tool.is_destructive,
                replace=True,
            )
        for item in resources:
            qualified = f"{server_name}.{item.name or item.uri}"
            if qualified not in self._resource_names:
                self._resource_names.append(qualified)
        for item in prompts:
            qualified = f"{server_name}.{item.name}"
            if qualified not in self._resource_names:
                self._resource_names.append(qualified)
        self._server_summaries[server_name] = {
            "server": server_name,
            "description": manager.server_config(server_name).description,
            "tool_count": len(tools),
            "resource_count": len(resources),
            "prompt_count": len(prompts),
            "session_active": server_name in manager.active_session_names(),
            "tools": [f"{server_name}.{tool.name}" for tool in tools],
        }
        self._discovered_servers.add(server_name)
        self.registry.mark_loaded(
            "mcp_adapter",
            loaded_tools=list(self._registered_tool_names),
            loaded_resources=list(self._resource_names),
            loaded_commands=[],
            hook_counts={"transform_context": 1},
        )

    def transform_context(self, state: AgentState, messages: list[ChatMessage]) -> list[ChatMessage]:
        text = self._latest_user_text(state)
        if not text:
            self._last_auto_servers = []
            return messages
        matched = self._match_server_names(text)
        if not matched:
            self._last_auto_servers = []
            return messages
        activated: list[str] = []
        for server_name in matched[:1]:
            already_ready = server_name in self._discovered_servers
            self.ensure_server_ready(server_name)
            activated.append(server_name)
            if already_ready:
                continue
        self._last_auto_servers = activated
        if not activated:
            return messages
        lines = ["Relevant MCP server loaded for this turn:"]
        for server_name in activated:
            summary = self._server_summaries.get(server_name, {"tools": []})
            tools = ", ".join(summary.get("tools", [])) or "no tools"
            lines.append(f"- {server_name}: {tools}")
        directive = ChatMessage(
            role="system",
            content=[TextPart(text="\n".join(lines))],
            timestamp=time.time(),
        )
        return [messages[0], directive, *messages[1:]] if messages else [directive]

    def _match_server_names(self, text: str) -> list[str]:
        lowered = text.lower()
        explicit: list[tuple[int, str]] = []
        manager = self._manager_for_current_config()
        for server_name in manager.server_names():
            if not self.settings.capabilities.mcp.includes_server(server_name):
                continue
            pos = _mention_position(lowered, server_name)
            if pos is not None:
                explicit.append((pos, server_name))
        if explicit:
            return [name for _, name in sorted(explicit, key=lambda item: (item[0], item[1]))]

        user_terms = _match_terms(text)
        candidates: list[tuple[float, str]] = []
        for server_name in manager.server_names():
            if not self.settings.capabilities.mcp.includes_server(server_name):
                continue
            server = manager.server_config(server_name)
            score = 0.0
            name_terms = _match_terms(server.name.replace("-", " ").replace("_", " "))
            description_terms = _description_terms(server.description)
            name_overlap = len(name_terms & user_terms)
            description_overlap = len(description_terms & user_terms)
            score += float(name_overlap) * 2.0
            score += float(description_overlap)
            if description_overlap >= 2:
                score += 1.0
            score += _phrase_bonus(text, server.description)
            if score >= 2.0:
                candidates.append((score, server_name))
        return [name for _, name in sorted(candidates, key=lambda item: (-item[0], item[1]))]

    def _manager_for_current_config(self) -> MCPManager:
        if self._manager is None:
            config_paths = self.settings.capabilities.mcp.resolved_config_paths(self.settings.project_dir)
            self._manager = MCPManager.from_workspace(
                self.workspace,
                transport_factory=self.transport_factory,
                time_fn=self.time_fn,
                config_paths=config_paths,
            )
        return self._manager

    def _manager_or_config_names(self) -> list[str]:
        return [
            name
            for name in self._manager_for_current_config().server_names()
            if self.settings.capabilities.mcp.includes_server(name)
        ]

    @staticmethod
    def _latest_user_text(state: AgentState) -> str:
        for message in reversed(state.messages):
            if message.role != "user":
                continue
            parts = [part.text.strip() for part in message.content if getattr(part, "text", "").strip()]
            if parts:
                return " ".join(parts)
        return ""

    @staticmethod
    def _descriptor() -> ExtensionDescriptor:
        return ExtensionDescriptor(
            name="mcp_adapter",
            description="Expose MCP servers as extension-backed runtime tools and resources.",
            entrypoint="pp_agent.mcp",
            provides=["mcp_tool", "mcp_resource", "mcp_prompt"],
            origin_type="builtin",
            root_name="mcp_backend",
            precedence=-1,
            declared_by_manifest=False,
        )


@dataclass
class ExecutableExtensions:
    registry: ExtensionRegistry = field(default_factory=ExtensionRegistry)
    commands: ExtensionCommandRegistry = field(default_factory=ExtensionCommandRegistry)
    resources: dict[str, list[str]] = field(default_factory=dict)
    cleanup_callbacks: list[Callable[[], object]] = field(default_factory=list)
    mcp_runtime: MCPRuntime | None = None

    def close(self) -> None:
        if self.mcp_runtime is not None:
            self.mcp_runtime.close()
        while self.cleanup_callbacks:
            callback = self.cleanup_callbacks.pop()
            callback()


def load_executable_extensions(
    workspace: Path,
    *,
    settings: Settings,
    tool_registry: ToolRegistry,
    runtime_hooks: RuntimeHooks,
    search_roots: Optional[list[object]] = None,
    include_mcp: Optional[bool] = None,
    transport_factory=None,
    time_fn=None,
) -> ExecutableExtensions:
    runtime = ExecutableExtensions()
    descriptors = load_extensions(
        workspace.resolve(),
        settings.global_dir,
        config=settings.capabilities.extensions,
        search_roots=search_roots,
    )
    for descriptor in descriptors.values():
        _load_extension_descriptor(descriptor, runtime, tool_registry, runtime_hooks)

    mcp_enabled = settings.capabilities.mcp.enable if include_mcp is None else include_mcp
    if mcp_enabled:
        runtime.mcp_runtime = MCPRuntime(
            workspace=workspace.resolve(),
            settings=settings,
            tool_registry=tool_registry,
            registry=runtime.registry,
            transport_factory=transport_factory,
            time_fn=time_fn,
        )
        runtime_hooks.transform_context_hooks.append(runtime.mcp_runtime.transform_context)
    return runtime


def _load_extension_descriptor(
    descriptor: ExtensionDescriptor,
    runtime: ExecutableExtensions,
    tool_registry: ToolRegistry,
    runtime_hooks: RuntimeHooks,
) -> None:
    runtime.registry.register(descriptor, status="discovered")
    try:
        loaded = load_extension_entrypoint(descriptor)
        _apply_loaded_extension(loaded, runtime, tool_registry, runtime_hooks)
    except Exception as exc:  # pragma: no cover - defensive path
        runtime.registry.mark_errored(descriptor.name, str(exc))


def _apply_loaded_extension(
    loaded: LoadedExtension,
    runtime: ExecutableExtensions,
    tool_registry: ToolRegistry,
    runtime_hooks: RuntimeHooks,
) -> None:
    for tool in loaded.tools:
        tool_registry.register_function_tool(
            name=tool.name,
            description=tool.spec.description,
            parameters=tool.spec.parameters,
            executor=tool.handler,
            category=tool.category,
            requires_confirmation=tool.spec.requires_confirmation,
        )
    for command in loaded.commands:
        runtime.commands.register(command)
    runtime_hooks.transform_context_hooks.extend(loaded.transform_context_hooks)
    runtime_hooks.before_tool_call_hooks.extend(loaded.before_tool_call_hooks)
    runtime_hooks.after_tool_call_hooks.extend(loaded.after_tool_call_hooks)
    runtime_hooks.on_tool_error_hooks.extend(loaded.tool_error_hooks)
    runtime.resources[loaded.descriptor.name] = list(loaded.resources)
    runtime.cleanup_callbacks.extend(loaded.cleanup_callbacks)
    runtime.registry.mark_loaded(
        loaded.descriptor.name,
        loaded_tools=[tool.name for tool in loaded.tools],
        loaded_commands=[command.name for command in loaded.commands],
        loaded_resources=list(loaded.resources),
        hook_counts={
            "transform_context": len(loaded.transform_context_hooks),
            "before_tool_call": len(loaded.before_tool_call_hooks),
            "after_tool_call": len(loaded.after_tool_call_hooks),
            "tool_error": len(loaded.tool_error_hooks),
        },
    )


def _mcp_result_to_tool_execution(result, *, tool_name: str) -> ToolExecutionResult:
    content = result.content
    if isinstance(content, list):
        rendered = "\n".join(str(item) for item in content)
    elif content is None:
        rendered = ""
    else:
        rendered = str(content)
    details = dict(result.metadata)
    details["payload"] = result.payload
    return ToolExecutionResult(
        tool_call_id="",
        tool_name=tool_name,
        content=rendered or str(result.payload),
        is_error=result.is_error,
        details=details,
    )


def _match_terms(text: str) -> set[str]:
    return {_normalize_term(item) for item in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(item) >= 3}


def _description_terms(text: str) -> set[str]:
    stopwords = {"the", "and", "for", "with", "that", "this", "into", "from", "your", "using"}
    return {item for item in _match_terms(text) if item not in stopwords}


def _mention_position(text: str, name: str) -> Optional[int]:
    variants = {
        name.lower(),
        name.lower().replace("_", " "),
        name.lower().replace("-", " "),
        name.lower().replace("_", "-"),
    }
    positions = [text.find(variant) for variant in variants if variant and text.find(variant) >= 0]
    if not positions:
        return None
    return min(positions)


def _phrase_bonus(text: str, description: str) -> float:
    normalized_text = " ".join(sorted(_match_terms(text)))
    normalized_desc = " ".join(sorted(_description_terms(description)))
    if not normalized_text or not normalized_desc:
        return 0.0
    shared = len(set(normalized_text.split()) & set(normalized_desc.split()))
    return 0.5 if shared >= 3 else 0.0


def _normalize_term(term: str) -> str:
    value = term.lower()
    if value.endswith("ies") and len(value) > 4:
        return value[:-3] + "y"
    if value.endswith("ing") and len(value) > 5:
        return value[:-3]
    if value.endswith("ed") and len(value) > 4:
        return value[:-2]
    if value.endswith("es") and len(value) > 4:
        return value[:-2]
    if value.endswith("s") and len(value) > 3:
        return value[:-1]
    return value


__all__ = ["ExecutableExtensions", "MCPRuntime", "load_executable_extensions"]
