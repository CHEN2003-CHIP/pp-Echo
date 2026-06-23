from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.browser import BrowserRuntime
from pp_agent.web_tools import WebRuntime
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

_WEB_FETCH_TAGS = {
    "web",
    "url",
    "fetch",
    "article",
    "website",
    "webpage",
    "page",
    "link",
    "news",
    "content",
    "html",
    "markdown",
    "readable",
    "网页",
    "网站",
    "链接",
    "页面",
    "文章",
    "新闻",
    "网址",
    "抓取",
    "网页内容",
}
_WEB_CN_KEYWORDS = (
    "网页",
    "网站",
    "链接",
    "页面",
    "文章",
    "新闻",
    "网址",
    "抓取",
    "网页内容",
    "获取内容",
    "获取网页",
    "网页数据",
    "网页正文",
    "总结这个链接",
    "这个链接",
    "这篇文章",
    "这个网页",
)
_WEB_EN_KEYWORDS = (
    "fetch",
    "webpage",
    "website",
    "web page",
    "url",
    "link",
    "article",
    "read page",
    "readable",
    "html",
    "markdown",
    "summarize this webpage",
    "summarize this link",
)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
logger = logging.getLogger(__name__)


def _mcp_policy(runtime: "MCPRuntime"):
    return getattr(runtime, "subagent_mcp_policy", None)


def _policy_allows_server(policy, server_name: str) -> bool:
    if policy is None:
        return True
    if not bool(getattr(policy, "enabled", False)):
        return False
    allowed_servers = list(getattr(policy, "allowed_servers", []) or [])
    return not allowed_servers or server_name in allowed_servers


def _policy_allows_tool(policy, server_name: str, tool_name: str) -> bool:
    if not _policy_allows_server(policy, server_name):
        return False
    if policy is None:
        return True
    qualified = f"{server_name}.{tool_name}" if "." not in tool_name else tool_name
    allowed_tools = list(getattr(policy, "allowed_tools", []) or [])
    return not allowed_tools or qualified in allowed_tools


def _settings_allows_tool(settings: Settings, server_name: str, tool_name: str) -> bool:
    return settings.capabilities.mcp.includes_tool(server_name, tool_name)


def _policy_allows_dynamic_tools(policy) -> bool:
    return True if policy is None else bool(getattr(policy, "allow_dynamic_tools", False))


def _policy_injects_context(policy) -> bool:
    return True if policy is None else bool(getattr(policy, "enabled", False) and getattr(policy, "inject_context", False))


@dataclass
class MCPRuntime:
    """"
    把 MCPManager 发现到的外部 MCP 能力，
    动态注册成 pp-Echo Runtime 可以调用的普通 Tool，并在上下文构建时按需提示模型优先使用相关 MCP 工具。
    """
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
    _last_match_details: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.registry.register(self._descriptor(), status="discovered")

    def status(self) -> dict[str, object]:
        return {
            "enabled": _mcp_policy(self) is None or bool(getattr(_mcp_policy(self), "enabled", False)),
            "server_count": len(self._manager_or_config_names()),
            "servers": self._manager_or_config_names(),
            "discovered": bool(self._discovered_servers),
            "active_sessions": self._manager.active_session_names() if self._manager is not None else [],
            "tool_count": len(self._registered_tool_names),
            "resource_count": len(self._resource_names),
            "auto_servers": list(self._last_auto_servers),
            "last_match": dict(self._last_match_details),
        }

    def list_servers(self) -> list[dict[str, object]]:
        self.ensure_discovered()
        return [dict(self._server_summaries[name]) for name in sorted(self._server_summaries)]

    def call_tool(self, qualified_name: str, arguments: dict[str, object]) -> ToolExecutionResult:
        if "." not in qualified_name:
            raise ValueError("MCP tool name must be qualified as <server>.<tool>")
        server_name, tool_name = qualified_name.split(".", 1)
        policy = _mcp_policy(self)
        if not _settings_allows_tool(self.settings, server_name, tool_name):
            raise PermissionError(f"MCP tool is filtered out by settings: {qualified_name}")
        if not _policy_allows_tool(policy, server_name, tool_name):
            raise PermissionError(f"MCP tool is not allowed by the active policy: {qualified_name}")
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
        self._last_match_details = {}
        self.registry.register(self._descriptor(), status="discovered")

    def close(self) -> None:
        if self._manager is not None:
            self._manager.close_all_sessions()
        self._manager = None

    def ensure_discovered(self) -> None:
        policy = _mcp_policy(self)
        if policy is not None and not bool(getattr(policy, "enabled", False)):
            logger.debug("MCP discovery denied by subagent policy")
            return
        for server_name in self._manager_for_current_config().server_names():
            if self.settings.capabilities.mcp.includes_server(server_name) and _policy_allows_server(policy, server_name):
                self.ensure_server_ready(server_name)

    def ensure_server_ready(self, server_name: str) -> None:
        policy = _mcp_policy(self)
        if policy is not None and not bool(getattr(policy, "enabled", False)):
            logger.debug("MCP server denied because policy disabled", extra={"server": server_name})
            return
        if not _policy_allows_server(policy, server_name):
            logger.debug("MCP server denied by policy", extra={"server": server_name})
            return
        if server_name in self._discovered_servers:
            return
        manager = self._manager_for_current_config()
        if server_name not in manager.server_names():
            raise ValueError(f"Unknown MCP server: {server_name}")
        if not self.settings.capabilities.mcp.includes_server(server_name):
            raise ValueError(f"MCP server is filtered out: {server_name}")
        tools = manager.list_mcp_tools(server_name)
        resources = manager.list_mcp_resources(server_name) if self.settings.capabilities.mcp.expose_resources else []
        prompts = manager.list_mcp_prompts(server_name) if self.settings.capabilities.mcp.expose_prompts else []
        for tool in tools:
            qualified_name = f"{server_name}.{tool.name}"
            if not _settings_allows_tool(self.settings, server_name, tool.name):
                logger.debug("MCP tool denied by settings", extra={"server": server_name, "tool": qualified_name})
                continue
            if not _policy_allows_tool(policy, server_name, tool.name):
                logger.debug("MCP tool denied by policy", extra={"server": server_name, "tool": qualified_name})
                continue
            if not _policy_allows_dynamic_tools(policy):
                logger.debug("MCP tool dynamic registration denied by policy", extra={"server": server_name, "tool": qualified_name})
                continue
            if qualified_name in self._registered_tool_names:
                continue
            self._registered_tool_names.append(qualified_name)
            requests_network_hint = self._looks_fetch_like(manager.server_config(server_name)) or any(
                keyword in f"{qualified_name} {tool.description}".lower()
                for keyword in ("fetch", "web", "url", "http", "https", "remote")
            )
            self.tool_registry._register_dynamic_tool_internal(
                name=qualified_name,
                description=tool.description,
                parameters=tool.input_schema or {"type": "object", "properties": {}},
                executor=lambda _workspace, arguments, server=server_name, tool_name=tool.name: _mcp_result_to_tool_execution(
                    manager.call_mcp_tool(server, tool_name, arguments),
                    tool_name=f"{server}.{tool_name}",
                ),
                category="mcp",
                requires_confirmation=tool.is_destructive,
                tool_family="mcp",
                exact_effect_mode="required" if requests_network_hint or tool.is_destructive else "auto",
                non_side_effectful=False,
                known_safe_inspect=False,
                requests_network_hint=requests_network_hint,
                touches_external_hint=False,
                risk_overrides={"destructive_hint": True} if tool.is_destructive else {},
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
        visible_tools = [
            f"{server_name}.{tool.name}"
            for tool in tools
            if _settings_allows_tool(self.settings, server_name, tool.name)
            and _policy_allows_tool(policy, server_name, tool.name)
        ]
        self._server_summaries[server_name] = {
            "server": server_name,
            "description": manager.server_config(server_name).description,
            "tool_count": len(tools),
            "resource_count": len(resources),
            "prompt_count": len(prompts),
            "session_active": server_name in manager.active_session_names(),
            "tools": visible_tools,
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
        policy = _mcp_policy(self)
        if policy is not None and not bool(getattr(policy, "enabled", False)):
            self._last_auto_servers = []
            self._last_match_details = {}
            logger.debug("MCP context transform denied because policy disabled")
            return messages
        if not _policy_injects_context(policy):
            self._last_auto_servers = []
            self._last_match_details = {}
            logger.debug("MCP context injection denied by policy")
            return messages
        text = self._latest_user_text(state)
        if not text:
            self._last_auto_servers = []
            self._last_match_details = {}
            return messages
        matched = self._match_servers(text)
        if not matched:
            self._last_auto_servers = []
            self._last_match_details = {}
            return messages
        activated: list[tuple[str, str, str]] = []
        for server_name, matched_by, reason in matched[:1]:
            if _policy_allows_server(policy, server_name):
                self.ensure_server_ready(server_name)
                activated.append((server_name, matched_by, reason))
        self._last_auto_servers = [server_name for server_name, _, _ in activated]
        self._last_match_details = {
            "matched_server": activated[0][0],
            "matched_by": activated[0][1],
            "mcp_match_reason": activated[0][2],
        }
        if not activated:
            return messages
        lines = ["Relevant MCP server loaded for this turn:"]
        for server_name, matched_by, reason in activated:
            summary = self._server_summaries.get(server_name, {"tools": []})
            tools = list(summary.get("tools", []))
            rendered_tools = ", ".join(tools) or "no tools"
            lines.append(f"- {server_name}: {rendered_tools}")
            lines.append(f"  matched_by={matched_by}; reason={reason}")
            preferred = self._preferred_tools_for_request(server_name, tools, text)
            if preferred:
                lines.append(f"  preferred_tools={', '.join(preferred)}")
        lines.append("")
        lines.append("MCP routing guidance:")
        if self._looks_like_web_fetch_request(text):
            lines.append("- This request matches webpage/link retrieval. Prefer a fetch MCP tool before answering.")
            lines.append("- Prefer readable or markdown page extraction when the user asked for a summary.")
            lines.append("- Do not say you cannot access the internet when one of these MCP tools can satisfy the request.")
            lines.append("- If the fetch tool fails, explain the fetch error or site limitation instead of denying capability.")
        else:
            lines.append("- Prefer the matched MCP tools when they directly satisfy the user request.")
        directive = ChatMessage(
            role="system",
            content=[TextPart(text="\n".join(lines))],
            timestamp=time.time(),
        )
        return [messages[0], directive, *messages[1:]] if messages else [directive]

    def _match_servers(self, text: str) -> list[tuple[str, str, str]]:
        explicit = self._explicit_server_matches(text)
        if explicit:
            return explicit
        intent = self._intent_router_matches(text)
        if intent:
            return intent
        return self._description_matches(text)

    def _explicit_server_matches(self, text: str) -> list[tuple[str, str, str]]:
        lowered = text.lower()
        explicit: list[tuple[int, str]] = []
        manager = self._manager_for_current_config()
        for server_name in manager.server_names():
            if not self.settings.capabilities.mcp.includes_server(server_name) or not _policy_allows_server(_mcp_policy(self), server_name):
                continue
            pos = _mention_position(lowered, server_name)
            if pos is not None:
                explicit.append((pos, server_name))
        return [(name, "name", f"explicit server name mention: {name}") for _, name in sorted(explicit, key=lambda item: (item[0], item[1]))]

    def _intent_router_matches(self, text: str) -> list[tuple[str, str, str]]:
        if not self._looks_like_web_fetch_request(text):
            return []
        manager = self._manager_for_current_config()
        candidates: list[tuple[float, str, str]] = []
        for server_name in manager.server_names():
            if not self.settings.capabilities.mcp.includes_server(server_name) or not _policy_allows_server(_mcp_policy(self), server_name):
                continue
            server = manager.server_config(server_name)
            score, matched_by, reason = self._intent_score(server, text)
            if score <= 0:
                continue
            candidates.append((score, server_name, f"{matched_by}:{reason}"))
        ordered = sorted(candidates, key=lambda item: (-item[0], item[1]))
        return [(server_name, reason.split(":", 1)[0], reason.split(":", 1)[1]) for _, server_name, reason in ordered]

    def _description_matches(self, text: str) -> list[tuple[str, str, str]]:
        user_terms = _match_terms(text)
        candidates: list[tuple[float, str, str]] = []
        manager = self._manager_for_current_config()
        for server_name in manager.server_names():
            if not self.settings.capabilities.mcp.includes_server(server_name) or not _policy_allows_server(_mcp_policy(self), server_name):
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
                candidates.append((score, server_name, f"description overlap score={score:.1f}"))
        return [(name, "description", reason) for score, name, reason in sorted(candidates, key=lambda item: (-item[0], item[1], item[2]))]

    def _intent_score(self, server, text: str) -> tuple[float, str, str]:
        lowered = text.lower()
        score = 0.0
        reasons: list[str] = []
        tag_hits = [tag for tag in server.intent_tags if tag and tag.lower() in lowered]
        if tag_hits:
            score += 8.0 + float(len(tag_hits))
            reasons.append(f"tag hit {', '.join(tag_hits[:3])}")
        example_hits = [example for example in server.auto_match_examples if example and example.lower() in lowered]
        if example_hits:
            score += 7.0 + float(len(example_hits))
            reasons.append(f"example hit {', '.join(example_hits[:2])}")
        server_tags = {tag.lower() for tag in server.intent_tags}
        if _URL_RE.search(text) and (server_tags & _WEB_FETCH_TAGS or self._looks_fetch_like(server)):
            score += 6.0
            reasons.append("URL present with web-capable server")
        if self._looks_fetch_like(server):
            score += 4.0
            reasons.append("server looks like fetch/web reader")
        if score > 0:
            matched_by = "tags" if tag_hits or example_hits else "url_intent"
            return score, matched_by, "; ".join(reasons)
        return 0.0, "", ""

    def _preferred_tools_for_request(self, server_name: str, tools: list[str], text: str) -> list[str]:
        if not tools:
            return []
        lowered = text.lower()
        if self._looks_like_web_fetch_request(text):
            preferred = [tool for tool in tools if tool.endswith(".fetch_readable") or tool.endswith(".fetch_markdown")]
            if preferred:
                return preferred
            preferred = [tool for tool in tools if tool.endswith(".fetch_txt") or tool.endswith(".fetch_html")]
            if preferred:
                return preferred
        return tools[:2]

    def _looks_like_web_fetch_request(self, text: str) -> bool:
        lowered = text.lower()
        if _URL_RE.search(text):
            return True
        if any(keyword in text for keyword in _WEB_CN_KEYWORDS):
            return True
        return any(keyword in lowered for keyword in _WEB_EN_KEYWORDS)

    @staticmethod
    def _looks_fetch_like(server) -> bool:
        lowered_name = server.name.lower()
        lowered_desc = server.description.lower()
        lowered_tags = {tag.lower() for tag in server.intent_tags}
        return (
            lowered_name == "fetch"
            or "fetch" in lowered_name
            or bool(lowered_tags & _WEB_FETCH_TAGS)
            or any(term in lowered_desc for term in ("web page", "webpage", "website", "url", "article", "html", "markdown", "readable"))
        )

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
            if self.settings.capabilities.mcp.includes_server(name) and _policy_allows_server(_mcp_policy(self), name)
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
    resource_roots: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    resource_discovery_handlers: dict[str, list[Callable[[dict[str, Any]], Optional[dict[str, list[str]]]]]] = field(default_factory=dict)
    cleanup_callbacks: list[Callable[[], object]] = field(default_factory=list)
    mcp_runtime: MCPRuntime | None = None
    browser_runtime: BrowserRuntime | None = None
    web_runtime: WebRuntime | None = None

    def close(self) -> None:
        if self.mcp_runtime is not None:
            self.mcp_runtime.close()
        if self.browser_runtime is not None:
            self.browser_runtime.close()
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
    browser_controller_factory=None,
    include_extensions: bool = True,
    transport_factory=None,
    time_fn=None,
) -> ExecutableExtensions:
    runtime = ExecutableExtensions()
    if include_extensions:
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
        runtime_hooks.add_transform_context_hook("mcp_runtime", "mcp", runtime.mcp_runtime.transform_context)
    if settings.capabilities.browser.enable:
        runtime.browser_runtime = BrowserRuntime(
            workspace=workspace.resolve(),
            settings=settings,
            tool_registry=tool_registry,
            controller_factory=browser_controller_factory,
        )
    runtime.web_runtime = WebRuntime(
        workspace=workspace.resolve(),
        tool_registry=tool_registry,
        settings=settings,
    )
    runtime_hooks.add_transform_context_hook("web_runtime", "web", runtime.web_runtime.transform_context)
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
        tool_registry._register_dynamic_tool_internal(
            name=tool.name,
            description=tool.spec.description,
            parameters=tool.spec.parameters,
            executor=tool.handler,
            category=tool.category,
            requires_confirmation=tool.spec.requires_confirmation,
            permission_domain=tool.spec.permission_domain,
            sensitive=tool.spec.sensitive,
            model_callable=tool.spec.model_callable,
            tool_family="extension",
            exact_effect_mode=tool.exact_effect_mode,
            non_side_effectful=tool.non_side_effectful,
            known_safe_inspect=tool.known_safe_inspect,
            requests_network_hint=tool.requests_network_hint,
            touches_external_hint=tool.touches_external_hint,
            risk_overrides={"destructive_hint": True} if (tool.spec.sensitive and tool.spec.permission_domain != "read") else {},
        )
    for command in loaded.commands:
        runtime.commands.register(command)
    for index, hook in enumerate(loaded.transform_context_hooks):
        runtime_hooks.add_transform_context_hook(
            f"extension:{loaded.descriptor.name}:transform:{index}",
            "extension",
            hook,
        )
    runtime_hooks.before_tool_call_hooks.extend(loaded.before_tool_call_hooks)
    runtime_hooks.after_tool_call_hooks.extend(loaded.after_tool_call_hooks)
    runtime_hooks.on_tool_error_hooks.extend(loaded.tool_error_hooks)
    runtime_hooks.lifecycle_event_hooks.extend(loaded.lifecycle_event_hooks)
    runtime.resources[loaded.descriptor.name] = list(loaded.resources)
    runtime.resource_discovery_handlers[loaded.descriptor.name] = list(loaded.resource_discovery_handlers)
    runtime.resource_roots.setdefault(loaded.descriptor.name, {})
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
            "lifecycle_event": len(loaded.lifecycle_event_hooks),
        },
        event_counts=dict(loaded.event_counts),
        resource_roots=runtime.resource_roots.get(loaded.descriptor.name, {}),
    )


def discover_extension_resource_roots(
    runtime: ExecutableExtensions,
    workspace: Path,
    *,
    reason: str,
) -> dict[str, list[Path]]:
    merged: dict[str, list[Path]] = {
        "skill_paths": [],
        "prompt_paths": [],
        "theme_paths": [],
        "extension_paths": [],
    }
    for extension_name, handlers in runtime.resource_discovery_handlers.items():
        resource_roots = {
            "skill_paths": [],
            "prompt_paths": [],
            "theme_paths": [],
            "extension_paths": [],
        }
        payload = {"cwd": str(workspace.resolve()), "workspace": workspace.resolve(), "reason": reason}
        for handler in handlers:
            contribution = handler(payload) or {}
            for key in resource_roots:
                values = [_safe_resolve(Path(value)) for value in contribution.get(key, [])]
                resource_roots[key].extend(value for value in values if value not in resource_roots[key])
        runtime.resource_roots[extension_name] = {key: [str(value) for value in values] for key, values in resource_roots.items() if values}
        binding = runtime.registry.get(extension_name)
        if binding is not None:
            runtime.registry.mark_loaded(
                extension_name,
                loaded_tools=binding.loaded_tools,
                loaded_commands=binding.loaded_commands,
                loaded_resources=binding.loaded_resources,
                hook_counts=binding.hook_counts,
                event_counts=binding.event_counts,
                resource_roots=runtime.resource_roots.get(extension_name, {}),
            )
        for key, values in resource_roots.items():
            for value in values:
                if value not in merged[key]:
                    merged[key].append(value)
    return merged


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


__all__ = ["ExecutableExtensions", "MCPRuntime", "discover_extension_resource_roots", "load_executable_extensions"]


def _safe_resolve(path: Path) -> Path:
    candidate = path.expanduser()
    try:
        return candidate.resolve()
    except (OSError, PermissionError):
        return candidate.absolute()
