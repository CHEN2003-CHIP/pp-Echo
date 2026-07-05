from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Union

from pp_agent.domain import ToolCall, ToolSpec
from pp_agent.observability.hooks import ObservabilityHooks
from pp_agent.observability.noop import NoopObservabilityHooks
from pp_agent.observability.redaction import redact_mapping, safe_preview, sanitize_tool_args
from pp_agent.runtime.execution_context import (
    RuntimeExecutionContext,
    check_runtime_guardrails,
    increment_runtime_counter,
    runtime_counters_to_dict,
    runtime_guardrail_check_to_dict,
)
from pp_agent.runtime.tool_context import ToolExecutionContext
from pp_agent.sandbox.base import SandboxExecutor
from pp_agent.storage.settings import ToolPolicyConfig
from pp_agent.tools.base import BaseTool, ToolExecutionResult
from pp_agent.tools.file_tools import (
    ApprovePendingActionTool,
    EditFileTool,
    ListFilesTool,
    ListPendingActionsTool,
    PreviewPendingActionTool,
    ReadFileTool,
    RejectPendingActionTool,
    WriteFileTool,
    reject_symlink_edit_path,
    validate_text_edit_target,
)
from pp_agent.tools.effects import (
    analyze_extension_call,
    analyze_file_call,
    analyze_mcp_call,
    build_file_effect,
    build_dynamic_tool_effect,
    build_shell_effect,
    content_digest,
    dynamic_tool_declarations,
)
from pp_agent.tools.metadata import ToolMetadata
from pp_agent.tools.policy import ALLOW, ASK, PermissionDomain, ToolPolicyDecision, ToolPolicyEvaluator
from pp_agent.tools.repo_tools import GitDiffWorktreeTool, GitStatusTool, GrepCodeTool
from pp_agent.tools.search_tool import SearchTextTool
from pp_agent.tools.session_tools import ExecuteSafeRewindTool, PreviewSafeRewindTool
from pp_agent.tools.shell_tool import PowerShellTool
from pp_agent.tools.shell_tool import default_local_sandbox_executor
from pp_agent.attachments.tools import (
    InspectAttachmentTool,
    ListAttachmentsTool,
    ReadAttachmentChunkTool,
    ReadAttachmentRangeTool,
    ReadAttachmentTextTool,
    ReadAttachmentSymbolTool,
    SearchAttachmentTool,
    SearchAttachmentSymbolsTool,
)


SpecFactory = Callable[[], ToolSpec]
ToolFactory = Callable[[], BaseTool]
ToolExecutor = Callable[[Path, dict[str, Any]], Union[ToolExecutionResult, str]]
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pp_agent.subagents.capabilities import SubAgentProfile


_WRITE_TOOLS = {"write_file", "edit_file", "run_shell", "execute_safe_rewind"}
_APPROVAL_EXECUTE_TOOLS = {"approve_pending_action", "reject_pending_action"}
_ATTACHMENT_TOOLS = {
    "list_attachments",
    "inspect_attachment",
    "search_attachment",
    "read_attachment_chunk",
    "read_attachment_text",
    "read_attachment_range",
    "search_attachment_symbols",
    "read_attachment_symbol",
}


def _allow_mcp_tool(policy: Any, server_name: str, tool_name: str) -> bool:
    if policy is None:
        return True
    if not bool(getattr(policy, "enabled", False)):
        return False
    allowed_servers = list(getattr(policy, "allowed_servers", []) or [])
    if allowed_servers and server_name not in allowed_servers:
        return False
    qualified = f"{server_name}.{tool_name}" if "." not in tool_name else tool_name
    allowed_tools = list(getattr(policy, "allowed_tools", []) or [])
    return not allowed_tools or qualified in allowed_tools


def _allow_tool(profile: Any, tool_name: str, *, tool_family: str | None = None, category: str | None = None) -> bool:
    if profile is None:
        return True
    tool_policy = getattr(profile, "tool", None)
    denylist = list(getattr(tool_policy, "denylist", []) or [])
    allowlist = list(getattr(tool_policy, "allowlist", []) or [])
    if tool_name in denylist:
        return False
    if allowlist and tool_name not in allowlist:
        return False
    workspace = getattr(profile, "workspace", None)
    mode = str(getattr(workspace, "mode", "read_only"))
    if mode == "read_only" and tool_name in _WRITE_TOOLS | _APPROVAL_EXECUTE_TOOLS:
        return False
    if mode == "staged_edits" and tool_name in _APPROVAL_EXECUTE_TOOLS:
        return False
    if mode == "worktree":
        if tool_name in _APPROVAL_EXECUTE_TOOLS:
            return False
        if tool_name in _WRITE_TOOLS and not bool(getattr(workspace, "allow_write_tools", False)):
            return False
    if tool_family == "mcp" or category == "mcp":
        if "." not in tool_name:
            return False
        server_name, mcp_tool = tool_name.split(".", 1)
        return _allow_mcp_tool(getattr(profile, "mcp", None), server_name, mcp_tool)
    return True


def _allow_dynamic_registration(profile: Any, *, name: str, tool_family: str | None, category: str | None) -> bool:
    if profile is None:
        return True
    family = tool_family or ("mcp" if category == "mcp" else "extension" if category == "extension" else category)
    if family == "mcp" or category == "mcp":
        mcp_policy = getattr(profile, "mcp", None)
        if not bool(getattr(mcp_policy, "allow_dynamic_tools", False)):
            return False
        if "." not in name:
            return False
        server_name, mcp_tool = name.split(".", 1)
        return _allow_mcp_tool(mcp_policy, server_name, mcp_tool)
    if family == "extension" or category == "extension":
        if category == "memory" and name in {"memory_search", "memory_get"}:
            return _allow_tool(profile, name, tool_family=family, category=category)
        tool_policy = getattr(profile, "tool", None)
        return bool(getattr(tool_policy, "allow_dynamic_tools", False)) and _allow_tool(
            profile,
            name,
            tool_family=family,
            category=category,
        )
    return _allow_tool(profile, name, tool_family=family, category=category)


def _tool_trace_attributes(tool_name: str, tool: object, spec: object | None, metadata: object | None) -> dict[str, Any]:
    """
    从工具定义、ToolSpec 和 ToolMetadata 中提取适合进入 Trace 的结构化属性。

    该 helper 服务于 ToolRegistry middleware 生成的 tool.call span，用来连接 TraceInspect、
    summary.py 和后续 artifact/approval/effect 线索。它必须容忍内置工具、MCP 工具、browser 工具、
    subagent 工具和未来插件工具的字段差异；缺失字段返回 None，不允许因为观测 metadata 不完整而
    影响工具执行。返回值只包含分类、权限、schema key 等摘要，不保存完整参数、文件内容或敏感信息。
    """

    _ = tool
    parameters = getattr(spec, "parameters", None)
    schema_keys = None
    if isinstance(parameters, dict):
        properties = parameters.get("properties")
        if isinstance(properties, dict):
            schema_keys = sorted(str(key) for key in properties)
    tool_family = getattr(metadata, "tool_family", None)
    category = getattr(metadata, "category", None)
    permission_domain = getattr(metadata, "permission_domain", None) or getattr(spec, "permission_domain", None)
    return {
        "tool_name": tool_name,
        "tool_origin": tool_family or category,
        "tool_family": tool_family,
        "tool_category": category,
        "requires_confirmation": getattr(metadata, "requires_confirmation", None)
        if metadata is not None
        else getattr(spec, "requires_confirmation", None),
        "permission_domain": permission_domain,
        "description": safe_preview(getattr(spec, "description", None), 500) if spec is not None else None,
        "schema_keys": schema_keys,
        "is_mcp_tool": tool_family == "mcp" or category == "mcp" or "." in tool_name,
        "is_subagent_tool": tool_name in {"spawn_subagent", "orchestrate_agents"} or tool_family == "subagent",
        "source": "tool_registry_middleware",
        "span_kind": "tool_execution",
        "phase": "execution",
    }


def _tool_trace_output(result: ToolExecutionResult) -> dict[str, Any]:
    """
    生成工具执行结果的 trace 输出摘要。

    输出仅保留状态、短 preview、审批/artifact token、changed_paths、exit_code 等审计字段。
    details 会先经过统一 redaction，再裁剪到 16KB 以内，避免 stdout/stderr、文件内容、token 或
    私密字段把 trace 文件撑大或泄露到 TraceInspect。
    """

    raw_details = dict(result.details or {})
    details = _attachment_trace_details(result) if result.tool_name in _ATTACHMENT_TOOLS else redact_mapping(raw_details)
    content_preview = _attachment_trace_content_preview(result, details) if result.tool_name in _ATTACHMENT_TOOLS else safe_preview(_redact_tool_content(result.content, raw_details), 2000)
    approval_token = raw_details.get("token") or raw_details.get("approval_token")
    return {
        "is_error": bool(result.is_error),
        "content_preview": content_preview,
        "details": safe_preview(json.dumps(details, ensure_ascii=False, default=str), 16 * 1024),
        "artifact_token": details.get("artifact_token"),
        "approval_token": details.get("token") or details.get("approval_token"),
        "approval_token_hash": _stable_token_hash(approval_token),
        "changed_paths": _trace_changed_paths(raw_details, details),
        "exit_code": details.get("exit_code") or details.get("returncode"),
    }


def _redact_tool_content(content: str, details: dict[str, Any]) -> str:
    text = str(content or "")
    for token_key in ("token", "approval_token", "artifact_token"):
        token = str(details.get(token_key) or "")
        if token:
            text = text.replace(token, "[REDACTED]")
    return text


def _stable_token_hash(token: object) -> str | None:
    value = str(token or "").strip()
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _trace_changed_paths(raw_details: dict[str, Any], redacted_details: dict[str, Any]) -> list[str] | None:
    explicit = redacted_details.get("changed_paths") or redacted_details.get("affected_paths")
    if isinstance(explicit, list):
        return [str(path) for path in explicit if str(path).strip()]
    effect = raw_details.get("effect") if isinstance(raw_details.get("effect"), dict) else {}
    normalized = effect.get("normalized_arguments") if isinstance(effect.get("normalized_arguments"), dict) else {}
    path = normalized.get("path") or raw_details.get("path")
    if path:
        return [str(path)]
    return None


def _attachment_trace_content_preview(result: ToolExecutionResult, details: dict[str, Any]) -> str:
    """
    为附件工具生成 Trace 预览，避免 read chunk/range 的完整文本进入 TraceInspect。
    """

    if result.tool_name == "search_attachment":
        snippets = [str(item.get("snippet", ""))[:240] for item in details.get("results", []) if isinstance(item, dict)]
        return safe_preview(json.dumps({"result_count": len(snippets), "snippets": snippets}, ensure_ascii=False), 2000)
    if result.tool_name in {"read_attachment_chunk", "read_attachment_text", "read_attachment_range", "read_attachment_symbol"}:
        return safe_preview(json.dumps({key: value for key, value in details.items() if key != "text"}, ensure_ascii=False, default=str), 2000)
    return safe_preview(json.dumps(details, ensure_ascii=False, default=str), 2000)


def _attachment_trace_details(result: ToolExecutionResult) -> dict[str, Any]:
    """
    脱敏附件工具 details，保留可审计 metadata/snippet，移除完整 chunk/range 文本。
    """

    details = dict(result.details or {})
    if "text" in details:
        text = str(details.pop("text") or "")
        details["text_preview"] = safe_preview(text, 240)
        details["text_length"] = len(text)
    chunk = details.get("chunk")
    if isinstance(chunk, dict) and "text" in chunk:
        chunk = dict(chunk)
        text = str(chunk.pop("text") or "")
        chunk["text_preview"] = safe_preview(text, 240)
        chunk["text_length"] = len(text)
        details["chunk"] = chunk
    return redact_mapping(details)


@dataclass
class ToolRegistration:
    """Register tool metadata and materializers without instantiating the tool."""

    name: str
    category: str
    spec_factory: SpecFactory
    tool_factory: ToolFactory
    metadata: ToolMetadata


class ToolRegistry:
    """
    ToolRegistry 是工具系统的统一注册、暴露和执行入口。

    它管理内置工具与动态工具，负责：
    - 注册工具及其 ToolSpec / ToolMetadata；
    - 生成 openapi_specs()，把可被模型调用的工具暴露给 LLM；
    - 根据 capability profile 和 model_callable 过滤工具；
    - 在 execute() 前进行 effect analysis 和 ToolPolicyEvaluator 安全评估；
    - 根据 allow / ask / deny 决策决定直接执行、进入审批或拒绝；
    - 懒加载并缓存具体工具实例；
    - 支持 MCP、extension、memory、browser、subagent 等动态工具接入。

    ToolRegistry 不负责 Agent 主循环；
    AgentRuntime 负责决定何时调用工具，
    ToolRegistry 负责管理“有哪些工具、能不能调用、怎么调用”。
    """
    def __init__(
        self,
        workspace: Path,
        policy: Optional[ToolPolicyConfig] = None,
        current_session_id: Optional[str] = None,
        capability_profile: Optional["SubAgentProfile"] = None,
        observability: ObservabilityHooks | None = None,
        sandbox_config: Any | None = None,
        sandbox_executor: SandboxExecutor | None = None,
    ) -> None:
        """
        初始化工具注册中心
        :param workspace: 工作空间根目录（工具操作的安全边界）
        :param policy: 工具安全策略（确认弹窗、执行超时等）
        """
        self.workspace = workspace.resolve()
        self.capability_profile = capability_profile
        self.policy = policy or ToolPolicyConfig()
        self.policy_evaluator = ToolPolicyEvaluator(
            self.workspace,
            permission_mode=self.policy.permission_mode,
            allowed_tools=self.policy.allowed_tools,
            denied_tools=self.policy.denied_tools,
            ask_tools=self.policy.ask_tools,
        )
        self.current_session_id = current_session_id
        self.sandbox_config = sandbox_config
        self.sandbox_executor = sandbox_executor or default_local_sandbox_executor()
        self._runtime_event_emitter: Optional[Callable[[Any], None]] = None
        self.observability: ObservabilityHooks = observability or NoopObservabilityHooks()
        self._runtime_event_lock = threading.RLock()
        self._cancellation_token: Any = None
        self._tool_execution_context = ToolExecutionContext()
        self._instances: dict[str, BaseTool] = {}
        self._confirmation_overrides = {
            "write_file": self.policy.confirm_write_file,
            "edit_file": self.policy.confirm_edit_file,
            "approve_pending_action": True,
            "reject_pending_action": True,
            "run_shell": self.policy.confirm_run_shell,
        }
        self._registrations = self._build_builtin_registrations()
        self._builtin_registration_names = set(self._registrations)

    def set_capability_profile(self, profile: Optional["SubAgentProfile"]) -> None:
        self.capability_profile = profile.model_copy(deep=True) if profile is not None else None

    def register(self, registration: ToolRegistration, *, replace: bool = False) -> None:
        """
        【公共方法】注册工具
        :param registration: 工具注册项
        :param replace: 是否允许覆盖已存在工具
        :raises ValueError: 工具已存在且不允许覆盖时抛出
        """
        if not replace and registration.name in self._registrations:
            raise ValueError(f"Tool already registered: {registration.name}")
        self._registrations[registration.name] = registration
        self._instances.pop(registration.name, None)

    def reset_dynamic_registrations(self) -> None:
        """
        【公共方法】重置动态注册的工具
        【业务功能】清除插件/扩展工具，保留内置工具，用于会话隔离
        """
        dynamic_names = [name for name in self._registrations if name not in self._builtin_registration_names]
        for name in dynamic_names:
            self._registrations.pop(name, None)
            self._instances.pop(name, None)

    def register_function_tool(
        self,
        *,
        name: str,
        description: str,
        parameters: Optional[dict[str, Any]] = None,
        executor: ToolExecutor,
        category: str = "extension",
        requires_confirmation: bool = False,
        permission_domain: str = PermissionDomain.READ,
        sensitive: bool = False,
        model_callable: bool = True,
        tool_family: str | None = None,
        exact_effect_mode: str = "auto",
        non_side_effectful: bool = False,
        known_safe_inspect: bool = False,
        requests_network_hint: bool = False,
        touches_external_hint: bool = False,
        replace: bool = False,
        **deprecated_kwargs: Any,
    ) -> None:
        """
        【扩展方法】动态注册函数式工具（插件机制）
        【业务功能】允许外部传入普通函数，自动包装为标准AI工具
         - :param name: 工具名
         - :param description: 工具描述（给AI看）
         - :param parameters: 入参定义
         - :param executor: 执行函数
         - :param category: 分类
         - :param requires_confirmation: 是否需要确认
         - :param replace: 是否覆盖
        """
        if deprecated_kwargs:
            unexpected = ", ".join(sorted(deprecated_kwargs))
            raise TypeError(f"register_function_tool() got unexpected keyword argument(s): {unexpected}")
        self._register_dynamic_tool_internal(
            name=name,
            description=description,
            parameters=parameters,
            executor=executor,
            category=category,
            requires_confirmation=requires_confirmation,
            permission_domain=permission_domain,
            sensitive=sensitive,
            model_callable=model_callable,
            tool_family=tool_family,
            risk_overrides=None,
            exact_effect_mode=exact_effect_mode,
            non_side_effectful=non_side_effectful,
            known_safe_inspect=known_safe_inspect,
            requests_network_hint=requests_network_hint,
            touches_external_hint=touches_external_hint,
            replace=replace,
        )

    def _register_dynamic_tool_internal(
        self,
        *,
        name: str,
        description: str,
        parameters: Optional[dict[str, Any]] = None,
        executor: ToolExecutor,
        category: str = "extension",
        requires_confirmation: bool = False,
        permission_domain: str = PermissionDomain.READ,
        sensitive: bool = False,
        model_callable: bool = True,
        tool_family: str | None = None,
        risk_overrides: Optional[dict[str, bool]] = None,
        exact_effect_mode: str = "auto",
        non_side_effectful: bool = False,
        known_safe_inspect: bool = False,
        requests_network_hint: bool = False,
        touches_external_hint: bool = False,
        replace: bool = False,
    ) -> None:
        if not _allow_dynamic_registration(
            self.capability_profile,
            name=name,
            tool_family=tool_family,
            category=category,
        ):
            logger.debug(
                "tool dynamic registration denied by capability profile",
                extra={"tool_name": name, "category": category, "tool_family": tool_family},
            )
            print(f"tool dynamic registration denied by capability profile: {name}")
            return
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=parameters or {"type": "object", "properties": {}},
            requires_confirmation=requires_confirmation,
            permission_domain=permission_domain,
            sensitive=sensitive,
            model_callable=model_callable,
        )

        class _FunctionTool(BaseTool):
            def _execute_executor(self, arguments: dict[str, Any]) -> ToolExecutionResult:
                result = executor(self.workspace, arguments)
                if isinstance(result, ToolExecutionResult):
                    return result
                if hasattr(result, "model_dump"):
                    payload = result.model_dump(mode="python")
                    return ToolExecutionResult(**payload)
                return ToolExecutionResult(tool_call_id="", tool_name=name, content=str(result))

            def execute_host_approved(self, arguments: dict[str, Any]) -> ToolExecutionResult:
                result = self._execute_executor(arguments)
                result.tool_name = name
                return result

            @property
            def spec(self) -> ToolSpec:
                return spec.model_copy(deep=True)

            def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
                decision, analysis = self_registry._evaluate_dynamic_call(name, arguments)
                metadata = self_registry._registrations[name].metadata
                if decision.action == "deny":
                    raise PermissionError(decision.reason)
                if decision.action == ALLOW and metadata.tool_family in {"browser", "web"}:
                    return self.execute_host_approved(arguments)
                if decision.action == ALLOW and metadata.exact_effect_mode == "required":
                    return self_registry._stage_or_fail_dynamic_call(
                        name=name,
                        arguments=arguments,
                        decision=decision,
                        analysis=analysis,
                    )
                if decision.action == ALLOW and self_registry._dynamic_direct_allow_eligible(name, analysis):
                    return self.execute_host_approved(arguments)
                if decision.action == ASK:
                    return self_registry._stage_or_fail_dynamic_call(
                        name=name,
                        arguments=arguments,
                        decision=decision,
                        analysis=analysis,
                    )
                raise PermissionError("Dynamic tool execution is blocked by policy.")

        self_registry = self

        self.register(
            ToolRegistration(
                name=name,
                category=category,
                spec_factory=lambda: spec.model_copy(deep=True),
                tool_factory=lambda: _FunctionTool(self.workspace),
                metadata=ToolMetadata(
                    name=name,
                    category=category,
                    requires_confirmation=requires_confirmation,
                    permission_domain=permission_domain,
                    sensitive=sensitive,
                    model_callable=model_callable,
                    tool_family=tool_family or ("mcp" if category == "mcp" else "extension"),
                    risk_overrides=dict(risk_overrides or {}),
                    exact_effect_mode=exact_effect_mode,
                    non_side_effectful=non_side_effectful,
                    known_safe_inspect=known_safe_inspect,
                    requests_network_hint=requests_network_hint,
                    touches_external_hint=touches_external_hint,
                ),
            ),
            replace=replace,
        )

    def get_spec(self, name: str) -> ToolSpec:
        """
        【公共方法】获取工具规范（供AI调用使用）
        :param name: 工具名
        :return: 标准化工具规范
        """
        registration = self._registrations[name]
        spec = registration.spec_factory().model_copy(deep=True)
        if name in self._confirmation_overrides:
            spec.requires_confirmation = self._confirmation_overrides[name]
        return spec

    def has_tool(self, name: str) -> bool:
        """Return whether a tool is registered without materializing it."""

        return name in self._registrations

    def metadata(self) -> dict[str, ToolMetadata]:
        """
        【公共方法】获取所有工具元数据（供前端展示/权限面板）
        """
        return {
            name: registration.metadata.model_copy(deep=True)
            for name, registration in self._registrations.items()
        }

    def set_runtime_event_emitter(self, emitter: Callable[[Any], None]) -> None:
        self._runtime_event_emitter = emitter

    def emit_runtime_event(
        self,
        event_type: str,
        *,
        message: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        tool_name: Optional[str] = None,
        is_error: bool = False,
    ) -> None:
        if self._runtime_event_emitter is None:
            return
        from pp_agent.runtime.state import AgentEvent

        with self._runtime_event_lock:
            self._runtime_event_emitter(
                AgentEvent(
                    type=event_type,
                    session_id=self.current_session_id or "",
                    message=message,
                    details=details or {},
                    tool_name=tool_name,
                    is_error=is_error,
                )
            )

    def set_cancellation_token(self, token: Any) -> None:
        self._cancellation_token = token

    def set_observability(self, observability: ObservabilityHooks | None) -> None:
        """
        为 ToolRegistry 注入可观测性 hook。

        Runtime 创建或刷新 TraceRecorder 后通过该方法把同一套 ObservabilityHooks 传给工具执行层，
        让统一 execute() 入口能够生成 tool.call middleware span。传入 None 时回落到 Noop，不改变
        任何工具执行语义。该方法只建立观测关联，不保存工具参数原文或敏感输出。
        """

        self.observability = observability or NoopObservabilityHooks()

    def set_tool_execution_context(self, context: ToolExecutionContext | None) -> None:
        """Attach optional runtime guardrail context without changing legacy tool behavior.

        A missing RuntimeExecutionContext means guardrail checks are skipped and the existing
        ToolRegistry path continues. This does not replace ToolPolicy, approval, sandbox, or payload
        digest semantics.
        """

        self._tool_execution_context = context or ToolExecutionContext()

    def set_runtime_execution_context(self, context: RuntimeExecutionContext | None) -> None:
        """Set the optional RuntimeExecutionContext consumed by tool guardrail checks.

        The context is runtime-owned and keeps tools from importing coding contracts. Passing None
        restores legacy skipped-guardrail behavior.
        """

        self._tool_execution_context = ToolExecutionContext(runtime_execution_context=context)

    def runtime_execution_context(self) -> RuntimeExecutionContext | None:
        """Return the optional RuntimeExecutionContext currently attached to this registry."""

        return self._tool_execution_context.runtime_execution_context

    def _set_runtime_execution_context(self, context: RuntimeExecutionContext | None) -> None:
        self._tool_execution_context.runtime_execution_context = context

    def _runtime_context_details(self) -> dict[str, Any]:
        context = self.runtime_execution_context()
        return {
            "runtime_execution_context_present": context is not None,
            **({"execution_session_id": context.session_id} if context is not None else {}),
            **({"runtime_counters": runtime_counters_to_dict(context.counters)} if context is not None else {}),
        }

    def _runtime_guardrail_block_result(self, name: str, tool_call_id: str, check: Any) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_call_id=tool_call_id,
            tool_name=name,
            content=f"Runtime guardrail blocked tool call '{name}': {check.reason}",
            is_error=True,
            details={
                "runtime_guardrail_blocked": True,
                "guardrail_check": runtime_guardrail_check_to_dict(check),
                **self._runtime_context_details(),
            },
        )

    @property
    def cancellation_token(self) -> Any:
        return self._cancellation_token

    def cancellation_requested(self) -> bool:
        return bool(self._cancellation_token is not None and self._cancellation_token.cancelled)

    def raise_if_cancelled(self) -> None:
        if self._cancellation_token is not None:
            self._cancellation_token.raise_if_cancelled()

    def clone_selected(
        self,
        names: list[str],
        *,
        current_session_id: Optional[str] = None,
        workspace_override: Path | None = None,
    ) -> "ToolRegistry":
        workspace = (workspace_override or self.workspace).resolve()
        cloned = ToolRegistry(
            workspace,
            policy=self.policy.model_copy(deep=True),
            current_session_id=current_session_id,
            capability_profile=self.capability_profile.model_copy(deep=True) if self.capability_profile is not None else None,
            observability=self.observability,
        )
        cloned._registrations = {
            name: self._registrations[name]
            for name in names
            if name in self._registrations
        }
        cloned._builtin_registration_names = {
            name for name in cloned._registrations if name in self._builtin_registration_names
        }
        cloned._instances = {}
        cloned._runtime_event_emitter = self._runtime_event_emitter
        cloned._runtime_event_lock = self._runtime_event_lock
        cloned._cancellation_token = self._cancellation_token
        cloned._tool_execution_context = self._tool_execution_context
        return cloned

    def evaluate_call(self, name: str, arguments: dict[str, Any]):
        self._ensure_tool_allowed(name)
        spec = self.get_spec(name)
        metadata = self._registrations[name].metadata
        permission_domain = spec.permission_domain
        tool_family = metadata.tool_family or ("mcp" if metadata.category == "mcp" else "extension" if metadata.category == "extension" else None)
        if permission_domain == PermissionDomain.BASH:
            timeout = int(arguments.get("timeout_seconds", self.policy.shell_timeout_seconds))
            shell_effect = build_shell_effect(
                tool_name=name,
                permission_domain=permission_domain,
                command=str(arguments.get("command", "")),
                timeout_seconds=timeout,
                workspace=self.workspace,
            )
            return self.policy_evaluator.evaluate(
                permission_domain=permission_domain,
                tool_name=name,
                tool_family=tool_family,
                command=str(arguments.get("command", "")),
                analysis=shell_effect["analysis"],
            )
        if tool_family in {"extension", "mcp"}:
            decision, _analysis = self._evaluate_dynamic_call(name, arguments)
            return decision
        raw_path = arguments.get("path")
        if raw_path is None:
            return self.policy_evaluator.evaluate(
                permission_domain=permission_domain,
                tool_name=name,
                tool_family=tool_family,
                analysis=self._analysis_for_non_path_builtin(name=name, permission_domain=permission_domain),
            )
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.workspace / path
        analysis = analyze_file_call(workspace=self.workspace, tool_name=name, permission_domain=permission_domain, target_path=path)
        return self.policy_evaluator.evaluate(
            permission_domain=permission_domain,
            tool_name=name,
            tool_family=tool_family,
            target_path=path,
            analysis=analysis,
        )

    def host_execute(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        self.raise_if_cancelled()
        self._ensure_tool_allowed(name)
        result = self._get_tool(name).execute(arguments)
        self.raise_if_cancelled()
        result.tool_name = name
        return result

    def host_execute_dynamic_approved(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        self.raise_if_cancelled()
        self._ensure_tool_allowed(name)
        tool = self._get_tool(name)
        execute_host_approved = getattr(tool, "execute_host_approved", None)
        if execute_host_approved is None:
            raise ValueError(f"Tool '{name}' does not support host-approved dynamic execution")
        result = execute_host_approved(arguments)
        self.raise_if_cancelled()
        result.tool_name = name
        return result

    def execute(self, name: str, arguments: dict[str, Any], *, tool_call_id: str | None = None) -> ToolExecutionResult:
        """
        【核心方法】执行工具
        :param name: 工具名
        :param arguments: 参数字典
        :return: 标准化执行结果
        """
        trace_tool_call_id = str(tool_call_id or arguments.get("tool_call_id") or uuid.uuid4())
        self.raise_if_cancelled()
        self._ensure_tool_allowed(name)
        registration = self._registrations[name]
        if not registration.metadata.model_callable:
            raise PermissionError(f"Tool '{name}' is host-only and not model-callable")
        decision = self.evaluate_call(name, arguments)
        self._record_policy_decision(
            name,
            decision,
            tool_call_id=trace_tool_call_id,
        )
        if decision.action == "deny":
            self.observability.event(
                "tool_policy_denied",
                attributes={"tool_name": name, "tool_call_id": trace_tool_call_id},
                payload={"reason": decision.reason, "permission_domain": decision.permission_domain},
            )
            raise PermissionError(decision.reason)
        guardrail_check = check_runtime_guardrails(self.runtime_execution_context(), "tool_call")
        if guardrail_check.allowed is False:
            return self._runtime_guardrail_block_result(name, trace_tool_call_id, guardrail_check)
        spec = self.get_spec(name)
        attributes = _tool_trace_attributes(name, None, spec, registration.metadata)
        attributes["tool_call_id"] = trace_tool_call_id
        with self.observability.span(
            "tool.call",
            "tool",
            attributes=attributes,
            input={"arguments": sanitize_tool_args(arguments)},
        ) as span:
            try:
                tool = self._get_tool(name)
                if self._worktree_mode() and self._worktree_tool_supported(name):
                    result = self._execute_worktree_tool(name, arguments)
                else:
                    result = tool.execute(arguments)
                self.raise_if_cancelled()
                result.tool_name = name
                if not result.tool_call_id:
                    result.tool_call_id = trace_tool_call_id
                result.details.setdefault("tool_call_id", trace_tool_call_id)
                result.details.setdefault("trace_tool_call_id", trace_tool_call_id)
                result.details.setdefault("policy_decision", decision.action)
                result.details.setdefault("policy_reason", decision.reason)
                result.details.setdefault("permission_domain", decision.permission_domain)
                current_context = self.runtime_execution_context()
                if current_context is not None:
                    updated_context = increment_runtime_counter(current_context, "tool_call")
                    self._set_runtime_execution_context(updated_context)
                    result.details.setdefault("runtime_execution_context_present", True)
                    result.details.setdefault("execution_session_id", updated_context.session_id)
                    result.details.setdefault("tool_call_guardrail_check", runtime_guardrail_check_to_dict(guardrail_check))
                    result.details.setdefault("runtime_counters", runtime_counters_to_dict(updated_context.counters))
                self._backfill_pending_scope(result, session_id=self.current_session_id, tool_call_id=trace_tool_call_id)
                span.set_output(_tool_trace_output(result))
                if result.is_error:
                    span.set_error(result.content or "tool returned is_error=True", kind="ToolExecutionError")
                return result
            except Exception as exc:
                current_context = self.runtime_execution_context()
                if current_context is not None:
                    self._set_runtime_execution_context(increment_runtime_counter(current_context, "tool_call"))
                span.set_error(exc)
                raise

    def error_result(self, call: ToolCall, message: str) -> ToolExecutionResult:
        """
        【公共方法】生成工具执行错误结果（统一错误格式）
        """
        if call.name not in self._registrations:
            return ToolExecutionResult(
                tool_call_id=call.id,
                tool_name=call.name,
                content=message,
                is_error=True,
                details={
                    "error": message,
                    "tool_call_id": call.id,
                    "trace_tool_call_id": call.id,
                    "tool_name": call.name,
                    "tool_unknown": True,
                },
            )
        return self._get_tool(call.name).error_result(call, message)

    def _record_policy_decision(self, name: str, decision, *, tool_call_id: str) -> None:
        details = dict(decision.details or {})
        stable_decision = ToolPolicyDecision.from_policy_decision(
            decision,
            tool_name=name,
            tool_call_id=tool_call_id,
            run_id=getattr(self.observability, "current_run_id", None),
            session_id=self.current_session_id or getattr(self.observability, "current_session_id", None),
            permission_mode=self.policy.permission_mode,
        )
        attributes = {
            **details,
            **stable_decision.to_trace_attributes(),
            "tool_name": name,
            "source_tool_name": name,
            "tool_call_id": tool_call_id,
            "source_tool_call_id": tool_call_id,
            "policy_action": decision.action,
            "policy_reason": decision.reason,
            "permission_domain": decision.permission_domain,
            "target": decision.target,
            "source": "tool_registry_policy",
            "span_kind": "tool_policy_decision",
            "phase": "policy",
            "event_type": "tool_policy_decision",
        }
        self.observability.record_completed_span(
            "policy.decision",
            "policy",
            status="blocked" if decision.action == "deny" else "ok",
            attributes=attributes,
        )
        self.emit_runtime_event(
            "tool_policy_decision",
            tool_name=name,
            details=attributes,
            is_error=decision.action == "deny",
        )

    def _backfill_pending_scope(self, result: ToolExecutionResult, *, session_id: str | None, tool_call_id: str) -> None:
        token = result.details.get("token") if isinstance(result.details, dict) else None
        if not token:
            return
        store = self.pending_store()
        try:
            payload = store.load(str(token))
        except FileNotFoundError:
            return
        payload_session = str(payload.get("session_id") or "")
        if session_id and payload_session and payload_session != session_id:
            cloned = dict(payload)
            cloned["token"] = str(uuid.uuid4())
            cloned["session_id"] = session_id
            cloned["tool_call_id"] = tool_call_id
            cloned["created_at"] = time.time()
            cloned["details"] = dict(cloned.get("details") or {})
            cloned["details"]["session_id"] = session_id
            cloned["details"]["tool_call_id"] = tool_call_id
            store.save(cloned["token"], cloned)
            result.details["token"] = cloned["token"]
            return
        changed = False
        if session_id and not payload.get("session_id"):
            payload["session_id"] = session_id
            changed = True
        if tool_call_id and not payload.get("tool_call_id"):
            payload["tool_call_id"] = tool_call_id
            changed = True
        details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        if session_id and not details.get("session_id"):
            details["session_id"] = session_id
            changed = True
        if tool_call_id and not details.get("tool_call_id"):
            details["tool_call_id"] = tool_call_id
            changed = True
        if changed:
            payload["details"] = details
            store.save(str(token), payload)

    def openapi_specs(self) -> list[dict[str, Any]]:
        """
        【公共方法】生成OpenAI格式的工具规范列表（供LLM调用）
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": self.get_spec(name).name,
                    "description": self.get_spec(name).description,
                    "parameters": self.get_spec(name).parameters,
                },
            }
            for name, registration in self._registrations.items()
            if registration.metadata.model_callable and self._tool_allowed(name, registration.metadata)
        ]

    def _tool_allowed(self, name: str, metadata: ToolMetadata | None = None) -> bool:
        metadata = metadata or self._registrations[name].metadata
        allowed = _allow_tool(
            self.capability_profile,
            name,
            tool_family=metadata.tool_family,
            category=metadata.category,
        )
        if not allowed:
            logger.debug("tool filtered by capability profile", extra={"tool_name": name})
        return allowed

    def _ensure_tool_allowed(self, name: str) -> None:
        if name not in self._registrations:
            raise KeyError(name)
        if not self._tool_allowed(name):
            logger.debug("tool execution denied by capability profile", extra={"tool_name": name})
            raise PermissionError(f"Tool '{name}' is not allowed by the active subagent capability profile.")

    def _worktree_mode(self) -> bool:
        workspace = getattr(self.capability_profile, "workspace", None)
        return str(getattr(workspace, "mode", "")) == "worktree"

    def _worktree_tool_supported(self, name: str) -> bool:
        if name in {"write_file", "edit_file", "run_shell"}:
            return True
        metadata = self._registrations[name].metadata
        return metadata.tool_family in {"extension", "mcp"}

    def _execute_worktree_tool(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        metadata = self._registrations[name].metadata
        if name == "write_file":
            return self._execute_worktree_write(arguments)
        if name == "edit_file":
            return self._execute_worktree_edit(arguments)
        if name == "run_shell":
            return self._execute_worktree_shell(arguments)
        if metadata.tool_family in {"extension", "mcp"}:
            return self._execute_worktree_dynamic(name, arguments)
        raise PermissionError(f"Tool '{name}' is not supported in isolated worktree mode.")

    def _execute_worktree_write(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        reject_symlink_edit_path(self.workspace, str(arguments["path"]))
        path = self._resolve_worktree_path(arguments["path"])
        overwrite = bool(arguments.get("overwrite", False))
        existed = path.exists()
        after = str(arguments["content"])
        before = validate_text_edit_target(path, content=after)
        if existed and not overwrite:
            raise ValueError("File already exists. Re-run with overwrite=true after confirming the diff.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(after, encoding="utf-8")
        effect = build_file_effect(
            workspace=self.workspace,
            tool_name="write_file",
            permission_domain=PermissionDomain.EDIT,
            target_path=path,
            after=after,
            baseline={"kind": "absent"} if not existed else {"kind": "present", "content_digest": content_digest(before)},
            overwrite=overwrite,
        )
        return ToolExecutionResult(
            tool_call_id="",
            tool_name="write_file",
            content=f"Written inside isolated worktree: {path.relative_to(self.workspace)}",
            details={"path": str(path), "worktree": str(self.workspace), "persisted": True, "patch_artifact_pending": True, "effect": effect},
        )

    def _execute_worktree_edit(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        reject_symlink_edit_path(self.workspace, str(arguments["path"]))
        path = self._resolve_worktree_path(arguments["path"])
        original = validate_text_edit_target(path)
        if arguments.get("diff"):
            updated, replacements = EditFileTool._apply_search_replace_diff(original, arguments["diff"])
        else:
            old_text = arguments.get("old_text")
            new_text = arguments.get("new_text")
            if old_text is None or new_text is None:
                raise ValueError("Provide either diff or old_text/new_text.")
            updated = original.replace(str(old_text), str(new_text), 1)
            if updated == original:
                raise ValueError("old_text was not found in file")
            replacements = 1
        path.write_text(updated, encoding="utf-8")
        effect = build_file_effect(
            workspace=self.workspace,
            tool_name="edit_file",
            permission_domain=PermissionDomain.EDIT,
            target_path=path,
            after=updated,
            baseline={"kind": "present", "content_digest": content_digest(original)},
        )
        return ToolExecutionResult(
            tool_call_id="",
            tool_name="edit_file",
            content=f"Edited inside isolated worktree: {path.relative_to(self.workspace)}",
            details={"path": str(path), "worktree": str(self.workspace), "replacements": replacements, "persisted": True, "patch_artifact_pending": True, "effect": effect},
        )

    def _execute_worktree_shell(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        timeout = int(arguments.get("timeout_seconds", self.policy.shell_timeout_seconds))
        command = str(arguments["command"])
        effect = build_shell_effect(
            tool_name="run_shell",
            permission_domain=PermissionDomain.BASH,
            command=command,
            timeout_seconds=timeout,
            workspace=self.workspace,
        )
        self._enforce_worktree_analysis(effect["analysis"])
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            cwd=str(self.workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        output = (completed.stdout or "") + (("\n" + completed.stderr) if completed.stderr else "")
        if completed.returncode != 0:
            raise RuntimeError(f"PowerShell exited with code {completed.returncode}\n{output}".strip())
        return ToolExecutionResult(
            tool_call_id="",
            tool_name="run_shell",
            content=output.strip() or "[no output]",
            details={"command": command, "timeout_seconds": timeout, "returncode": completed.returncode, "worktree": str(self.workspace), "patch_artifact_pending": True, "effect": effect},
        )

    def _execute_worktree_dynamic(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        decision, analysis = self._evaluate_dynamic_call(name, arguments)
        if decision.action == "deny":
            raise PermissionError(decision.reason)
        self._enforce_worktree_analysis(analysis)
        tool = self._get_tool(name)
        execute_host_approved = getattr(tool, "execute_host_approved", None)
        if execute_host_approved is None:
            raise ValueError(f"Tool '{name}' does not support isolated worktree execution")
        result = execute_host_approved(arguments)
        result.tool_name = name
        details = dict(result.details or {})
        details.update({"worktree": str(self.workspace), "patch_artifact_pending": bool(analysis.get("touches_workspace")), "analysis": analysis})
        result.details = details
        return result

    def _enforce_worktree_analysis(self, analysis: dict[str, Any]) -> None:
        if bool(analysis.get("requests_network")):
            raise PermissionError("Isolated worktree sandbox denies network-requesting tool calls.")
        if bool(analysis.get("touches_external")):
            raise PermissionError("Isolated worktree sandbox denies tool calls that touch paths outside the worktree.")
        if bool(analysis.get("destructive_hint")):
            raise PermissionError("Isolated worktree sandbox denies destructive tool calls.")
        if bool(analysis.get("protected_path_hint")):
            raise PermissionError("Isolated worktree sandbox denies protected-path tool calls.")
        declared_required = analysis.get("declared_exact_effect_mode") == "required"
        if analysis.get("confidence_band") in {"unknown", "low"} and not bool(analysis.get("known_safe_inspect")) and not declared_required:
            raise PermissionError("Isolated worktree sandbox denies low-confidence tool calls.")

    def _resolve_worktree_path(self, raw_path: str) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.workspace / path
        resolved = path.resolve()
        if resolved != self.workspace and self.workspace not in resolved.parents:
            raise PermissionError("Path is outside the isolated worktree.")
        if self.policy_evaluator.is_protected(resolved):
            raise PermissionError("Path is protected by workspace policy.")
        return resolved

    def _get_tool(self, name: str) -> BaseTool:
        """
        【私有方法】获取工具单例（延迟初始化 + 缓存）
        """
        tool = self._instances.get(name)
        if tool is not None:
            return tool

        registration = self._registrations[name]
        tool = registration.tool_factory()
        self._instances[name] = tool
        return tool

    def _build_builtin_registrations(self) -> dict[str, ToolRegistration]:
        """
        【私有方法】构建内置工具注册列表
        【工具分类】文件操作 / 仓库操作 / Shell / 审核操作
        """
        registrations = [
            self._registration("read_file", self._spec_read_file, lambda: ReadFileTool(self.workspace, self.policy_evaluator, current_session_id=self.current_session_id)),
            self._registration("write_file", self._spec_write_file, lambda: WriteFileTool(self.workspace, self.policy_evaluator, current_session_id=self.current_session_id)),
            self._registration("edit_file", self._spec_edit_file, lambda: EditFileTool(self.workspace, self.policy_evaluator, current_session_id=self.current_session_id)),
            self._registration("preview_pending_action", self._spec_preview_pending_action, lambda: PreviewPendingActionTool(self.workspace, self.policy_evaluator, tool_registry=self)),
            self._registration("approve_pending_action", self._spec_approve_pending_action, lambda: ApprovePendingActionTool(self.workspace, self.policy_evaluator, tool_registry=self, sandbox_executor=self.sandbox_executor)),
            self._registration("reject_pending_action", self._spec_reject_pending_action, lambda: RejectPendingActionTool(self.workspace, self.policy_evaluator)),
            self._registration("list_pending_actions", self._spec_list_pending_actions, lambda: ListPendingActionsTool(self.workspace, self.policy_evaluator)),
            self._registration("list_files", self._spec_list_files, lambda: ListFilesTool(self.workspace, self.policy_evaluator)),
            self._registration("search_text", self._spec_search_text, lambda: SearchTextTool(self.workspace, self.policy_evaluator)),
            self._registration("grep_code", self._spec_grep_code, lambda: GrepCodeTool(self.workspace, self.policy_evaluator)),
            self._registration("git_status", self._spec_git_status, lambda: GitStatusTool(self.workspace, self.policy_evaluator)),
            self._registration("git_diff_worktree", self._spec_git_diff_worktree, lambda: GitDiffWorktreeTool(self.workspace, self.policy_evaluator)),
            self._registration("list_attachments", self._spec_list_attachments, lambda: ListAttachmentsTool(self.workspace, self.policy_evaluator, current_session_id=self.current_session_id, observability=self.observability)),
            self._registration("inspect_attachment", self._spec_inspect_attachment, lambda: InspectAttachmentTool(self.workspace, self.policy_evaluator, current_session_id=self.current_session_id, observability=self.observability)),
            self._registration("search_attachment", self._spec_search_attachment, lambda: SearchAttachmentTool(self.workspace, self.policy_evaluator, current_session_id=self.current_session_id, observability=self.observability)),
            self._registration("read_attachment_chunk", self._spec_read_attachment_chunk, lambda: ReadAttachmentChunkTool(self.workspace, self.policy_evaluator, current_session_id=self.current_session_id, observability=self.observability)),
            self._registration("read_attachment_text", self._spec_read_attachment_text, lambda: ReadAttachmentTextTool(self.workspace, self.policy_evaluator, current_session_id=self.current_session_id, observability=self.observability)),
            self._registration("read_attachment_range", self._spec_read_attachment_range, lambda: ReadAttachmentRangeTool(self.workspace, self.policy_evaluator, current_session_id=self.current_session_id, observability=self.observability)),
            self._registration("search_attachment_symbols", self._spec_search_attachment_symbols, lambda: SearchAttachmentSymbolsTool(self.workspace, self.policy_evaluator, current_session_id=self.current_session_id, observability=self.observability)),
            self._registration("read_attachment_symbol", self._spec_read_attachment_symbol, lambda: ReadAttachmentSymbolTool(self.workspace, self.policy_evaluator, current_session_id=self.current_session_id, observability=self.observability)),
            self._registration("preview_safe_rewind", self._spec_preview_safe_rewind, lambda: PreviewSafeRewindTool(self.workspace, current_session_id=self.current_session_id)),
            self._registration("execute_safe_rewind", self._spec_execute_safe_rewind, lambda: ExecuteSafeRewindTool(self.workspace, current_session_id=self.current_session_id)),
            self._registration(
                "run_shell",
                self._spec_run_shell,
                lambda: PowerShellTool(
                    self.workspace,
                    self.policy_evaluator,
                    default_timeout_seconds=getattr(self.sandbox_config, "timeout_seconds", None) or self.policy.shell_timeout_seconds,
                    sandbox_executor=self.sandbox_executor,
                ),
            ),
        ]
        return {registration.name: registration for registration in registrations}

    def _registration(self, name: str, spec_factory: SpecFactory, tool_factory: ToolFactory) -> ToolRegistration:
        """
        【私有方法】工具注册项构造工厂
        """
        spec = spec_factory()
        category = self._category_for(name)
        return ToolRegistration(
            name=name,
            category=category,
            spec_factory=spec_factory,
            tool_factory=tool_factory,
            metadata=ToolMetadata(
                name=spec.name,
                category=category,
                requires_confirmation=spec.requires_confirmation,
                permission_domain=spec.permission_domain,
                sensitive=spec.sensitive,
                model_callable=spec.model_callable,
                tool_family=self._tool_family_for(name, category),
                exact_effect_mode="required" if self._tool_family_for(name, category) in {"file", "shell"} else "none",
            ),
        )

    def _evaluate_dynamic_call(self, name: str, arguments: dict[str, Any]):
        spec = self.get_spec(name)
        metadata = self._registrations[name].metadata
        analysis = self._dynamic_analysis(
            name=name,
            permission_domain=spec.permission_domain,
            description=spec.description,
            tool_family=metadata.tool_family or "extension",
            declarations=self._dynamic_declarations(metadata),
            risk_overrides=dict(metadata.risk_overrides),
        )
        analysis["declaration_strength"] = metadata.declaration_strength
        decision = self.policy_evaluator.evaluate(
            permission_domain=spec.permission_domain,
            tool_name=name,
            tool_family=metadata.tool_family,
            analysis=analysis,
        )
        return decision, analysis

    @staticmethod
    def _analysis_for_non_path_builtin(*, name: str, permission_domain: str) -> dict[str, Any] | None:
        if permission_domain == PermissionDomain.REPO:
            return {
                "family": "repo",
                "permission_domain": permission_domain,
                "tool_name": name,
                "risk_class": "inspect",
                "summary": f"Inspect repository with {name}",
                "confidence_band": "high",
                "confidence_score": 0.98,
                "touches_workspace": True,
                "touches_external": False,
                "requests_network": False,
                "destructive_hint": False,
                "protected_path_hint": False,
                "known_safe_inspect": True,
            }
        return None

    def _dynamic_analysis(
        self,
        *,
        name: str,
        permission_domain: str,
        description: str,
        tool_family: str,
        declarations: dict[str, Any],
        risk_overrides: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_family == "mcp":
            return analyze_mcp_call(
                tool_name=name,
                permission_domain=permission_domain,
                description=description,
                declarations=declarations,
                risk_overrides=risk_overrides,
            )
        return analyze_extension_call(
            tool_name=name,
            permission_domain=permission_domain,
            description=description,
            declarations=declarations,
            risk_overrides=risk_overrides,
        )

    def _stage_or_fail_dynamic_call(self, *, name: str, arguments: dict[str, Any], decision, analysis: dict[str, Any]) -> ToolExecutionResult:
        registration = self._registrations[name]
        metadata = registration.metadata
        approvable, reason = self._dynamic_exact_effect_approvable(name=name, arguments=arguments, analysis=analysis)
        if not approvable:
            return ToolExecutionResult(
                tool_call_id="",
                tool_name=name,
                content=reason,
                is_error=True,
                details={
                    "staged": False,
                    "approvable": False,
                    "approval_unavailable": True,
                    "approval_unavailable_reason": reason,
                    "policy_decision": decision.action,
                    "policy_reason": decision.reason,
                    "analysis": analysis,
                },
            )
        effect = self.build_dynamic_effect(name, arguments, analysis=analysis)
        action_type = "run_mcp_tool" if metadata.tool_family == "mcp" else "run_extension_tool"
        payload = self.pending_store().stage(
            action_type=action_type,
            details={
                "tool_name": name,
                "tool_family": metadata.tool_family,
                "arguments": effect["normalized_arguments"]["arguments"],
                "analysis": analysis,
            },
            effect=effect,
            origin={"source": "tool_registry", "tool_name": name, "kind": metadata.tool_family},
        )
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=name,
            content=f"Staged {metadata.tool_family} call {name} for host-side approval with token {payload['token']}",
            details={
                "token": payload["token"],
                "staged": True,
                "approvable": True,
                "approval_unavailable": False,
                "effect": effect,
                "payload_digest": effect["payload_digest"],
                "summary": effect["summary"],
                "analysis": analysis,
            },
        )

    def _dynamic_exact_effect_approvable(self, *, name: str, arguments: dict[str, Any], analysis: dict[str, Any]) -> tuple[bool, str]:
        metadata = self._registrations[name].metadata
        mode = metadata.exact_effect_mode
        if mode == "none":
            return False, "Host review is required, but this dynamic tool does not support exact-effect approval staging."
        if mode == "auto" and not metadata.has_explicit_dynamic_declarations:
            return False, "Host review is required, but this dynamic tool is missing explicit safety declarations for exact-effect approval."
        if analysis.get("confidence_band") in {"unknown", "low"} and mode != "required":
            return False, "Host review is required, but this dynamic tool call is too weakly understood for exact-effect approval."
        try:
            self.build_dynamic_effect(name, arguments, analysis=analysis)
        except (TypeError, ValueError) as exc:
            return False, f"Host review is required, but this dynamic tool call cannot be represented stably for exact-effect approval: {exc}"
        return True, "approvable"

    def _dynamic_direct_allow_eligible(self, name: str, analysis: dict[str, Any]) -> bool:
        metadata = self._registrations[name].metadata
        return (
            metadata.tool_family in {"extension", "mcp"}
            and metadata.exact_effect_mode != "none"
            and analysis.get("confidence_band") == "high"
            and analysis.get("risk_class") == "inspect"
            and bool(analysis.get("known_safe_inspect"))
            and bool(analysis.get("non_side_effectful"))
            and not bool(analysis.get("requests_network"))
            and not bool(analysis.get("touches_external"))
            and not bool(analysis.get("destructive_hint"))
        )

    def build_dynamic_effect(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        analysis: dict[str, Any] | None = None,
        effect_id: str | None = None,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        spec = self.get_spec(name)
        metadata = self._registrations[name].metadata
        dynamic_analysis = analysis or self._dynamic_analysis(
            name=name,
            permission_domain=spec.permission_domain,
            description=spec.description,
            tool_family=metadata.tool_family or "extension",
            declarations=self._dynamic_declarations(metadata),
            risk_overrides=dict(metadata.risk_overrides),
        )
        dynamic_analysis["declaration_strength"] = metadata.declaration_strength
        return build_dynamic_tool_effect(
            tool_name=name,
            permission_domain=spec.permission_domain,
            family=metadata.tool_family or ("mcp" if metadata.category == "mcp" else "extension"),
            arguments=arguments,
            analysis=dynamic_analysis,
            effect_id=effect_id,
            created_at=created_at,
        )

    def pending_store(self):
        from pp_agent.storage.approvals import PendingActionStore

        return PendingActionStore(self.workspace / ".pp-agent" / "pending-edits")

    @staticmethod
    def _dynamic_declarations(metadata: ToolMetadata) -> dict[str, Any]:
        return dynamic_tool_declarations(
            exact_effect_mode=metadata.exact_effect_mode,
            non_side_effectful=metadata.non_side_effectful,
            known_safe_inspect=metadata.known_safe_inspect,
            requests_network_hint=metadata.requests_network_hint,
            touches_external_hint=metadata.touches_external_hint,
        )

    @staticmethod
    def _spec_read_file() -> ToolSpec:
        return ToolSpec(
            name="read_file",
            description="Read the contents of a UTF-8 text file. You must use this tool when the user asks to read, open, show, or inspect a specific local file. Do not answer file contents from memory, prior context, or guesswork when you can read the file directly.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            permission_domain=PermissionDomain.READ,
        )

    @staticmethod
    def _spec_write_file() -> ToolSpec:
        return ToolSpec(
            name="write_file",
            description="Stage a new file write for host-side approval. When the user explicitly asks to create a file, prefer this tool instead of only describing the intended file contents.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["path", "content"],
            },
            requires_confirmation=True,
            permission_domain=PermissionDomain.EDIT,
            sensitive=True,
        )

    @staticmethod
    def _spec_edit_file() -> ToolSpec:
        return ToolSpec(
            name="edit_file",
            description="Stage a safe diff-style edit using SEARCH/REPLACE blocks or a unified diff for host-side approval. When the user explicitly asks to change an existing file, prefer this tool instead of only describing the edit.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "diff": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path"],
            },
            requires_confirmation=True,
            permission_domain=PermissionDomain.EDIT,
            sensitive=True,
        )

    @staticmethod
    def _spec_preview_pending_action() -> ToolSpec:
        return ToolSpec(
            name="preview_pending_action",
            description="Preview a staged action by token, including diff or command details.",
            parameters={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]},
            permission_domain=PermissionDomain.APPROVAL,
            model_callable=False,
        )

    @staticmethod
    def _spec_approve_pending_action() -> ToolSpec:
        return ToolSpec(
            name="approve_pending_action",
            description="Approve and execute a previously staged file edit or shell command by token.",
            parameters={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]},
            requires_confirmation=True,
            permission_domain=PermissionDomain.APPROVAL,
            sensitive=True,
            model_callable=False,
        )

    @staticmethod
    def _spec_reject_pending_action() -> ToolSpec:
        return ToolSpec(
            name="reject_pending_action",
            description="Reject and remove a staged file edit or shell command by token.",
            parameters={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]},
            requires_confirmation=True,
            permission_domain=PermissionDomain.APPROVAL,
            sensitive=True,
            model_callable=False,
        )

    @staticmethod
    def _spec_list_pending_actions() -> ToolSpec:
        return ToolSpec(
            name="list_pending_actions",
            description="List staged actions waiting for approval.",
            parameters={"type": "object", "properties": {}},
            permission_domain=PermissionDomain.APPROVAL,
            model_callable=False,
        )

    @staticmethod
    def _spec_list_files() -> ToolSpec:
        return ToolSpec(
            name="list_files",
            description="List files and directories inside a path. You must use this tool when the user asks what files or folders exist in a local directory or what is inside a path. Do not summarize directory contents from memory or earlier turns when you can inspect the workspace directly.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            permission_domain=PermissionDomain.READ,
        )

    @staticmethod
    def _spec_search_text() -> ToolSpec:
        return ToolSpec(
            name="search_text",
            description="Search for text inside files under the workspace. Use this tool when the user asks to search for plain text, phrases, filenames in content, or broad workspace matches. Prefer a real search over guessing where text might appear.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}, "path": {"type": "string"}},
                "required": ["query"],
            },
            permission_domain=PermissionDomain.READ,
        )

    @staticmethod
    def _spec_grep_code() -> ToolSpec:
        return ToolSpec(
            name="grep_code",
            description="Search code text under the workspace, optimized for coding tasks. Use this tool when the user asks to find code symbols, implementations, call sites, or where a code fragment lives. Prefer this over guessing code locations from memory.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}, "path": {"type": "string"}},
                "required": ["query"],
            },
            permission_domain=PermissionDomain.READ,
        )

    @staticmethod
    def _spec_git_status() -> ToolSpec:
        return ToolSpec(
            name="git_status",
            description="Show git worktree status for the current workspace. You must use this tool when the user asks for current repository state, changed files, staged changes, or whether the worktree is clean.",
            parameters={"type": "object", "properties": {}},
            permission_domain=PermissionDomain.REPO,
        )

    @staticmethod
    def _spec_git_diff_worktree() -> ToolSpec:
        return ToolSpec(
            name="git_diff_worktree",
            description="Show git diff for the current worktree or a single path. You must use this tool when the user asks what changed, asks to inspect a diff, or wants the modifications for a specific file.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            permission_domain=PermissionDomain.REPO,
        )

    @staticmethod
    def _spec_list_attachments() -> ToolSpec:
        return ToolSpec(
            name="list_attachments",
            description="List current-session uploaded attachments. Returns metadata and previews only, never full file contents.",
            parameters={"type": "object", "properties": {"session_id": {"type": "string"}}},
            permission_domain=PermissionDomain.READ,
        )

    @staticmethod
    def _spec_inspect_attachment() -> ToolSpec:
        return ToolSpec(
            name="inspect_attachment",
            description="Inspect one attachment's summary, status, chunk count, code outline, table schema, PDF pages, or JSON structure before reading content.",
            parameters={"type": "object", "properties": {"session_id": {"type": "string"}, "attachment_id": {"type": "string"}}, "required": ["attachment_id"]},
            permission_domain=PermissionDomain.READ,
        )

    @staticmethod
    def _spec_search_attachment() -> ToolSpec:
        return ToolSpec(
            name="search_attachment",
            description="Search one or all current-session attachments with local keyword retrieval and return relevant chunk ids and snippets.",
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "query": {"type": "string"},
                    "attachment_id": {"type": "string"},
                    "top_k": {"type": "integer"},
                    "mode": {"type": "string", "enum": ["auto", "keyword", "hybrid"]},
                },
                "required": ["query"],
            },
            permission_domain=PermissionDomain.READ,
        )

    @staticmethod
    def _spec_read_attachment_chunk() -> ToolSpec:
        return ToolSpec(
            name="read_attachment_chunk",
            description="Read a specific attachment chunk by chunk_id after searching or inspecting an attachment.",
            parameters={"type": "object", "properties": {"session_id": {"type": "string"}, "chunk_id": {"type": "string"}}, "required": ["chunk_id"]},
            permission_domain=PermissionDomain.READ,
        )

    @staticmethod
    def _spec_read_attachment_text() -> ToolSpec:
        return ToolSpec(
            name="read_attachment_text",
            description="Read extracted text from an uploaded attachment by character offset. Use this for broad/full-document PDF, DOCX, Markdown, text, CSV, JSON, or code questions; continue with next_offset until truncated is false.",
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "attachment_id": {"type": "string"},
                    "offset": {"type": "integer"},
                    "max_chars": {"type": "integer"},
                },
                "required": ["attachment_id"],
            },
            permission_domain=PermissionDomain.READ,
        )

    @staticmethod
    def _spec_read_attachment_range() -> ToolSpec:
        return ToolSpec(
            name="read_attachment_range",
            description="Read a specific line range from a text, log, or code attachment. Use this instead of requesting an entire large file.",
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "attachment_id": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                "required": ["attachment_id", "start_line", "end_line"],
            },
            permission_domain=PermissionDomain.READ,
        )

    @staticmethod
    def _spec_search_attachment_symbols() -> ToolSpec:
        return ToolSpec(
            name="search_attachment_symbols",
            description="Search code attachment symbols by name, signature, parent, or docstring preview before reading code.",
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "query": {"type": "string"},
                    "attachment_id": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
                "required": ["query"],
            },
            permission_domain=PermissionDomain.READ,
        )

    @staticmethod
    def _spec_read_attachment_symbol() -> ToolSpec:
        return ToolSpec(
            name="read_attachment_symbol",
            description="Read a local code symbol by symbol_id. Use after inspect_attachment or search_attachment_symbols.",
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "attachment_id": {"type": "string"},
                    "symbol_id": {"type": "string"},
                },
                "required": ["attachment_id", "symbol_id"],
            },
            permission_domain=PermissionDomain.READ,
        )

    @staticmethod
    def _spec_run_shell() -> ToolSpec:
        return ToolSpec(
            name="run_shell",
            description="Stage a PowerShell command for host-side approval. You must use this tool when the user asks to run a local command, verify command output, or check the actual result of a script or interpreter. Do not invent command results.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                },
                "required": ["command"],
            },
            requires_confirmation=True,
            permission_domain=PermissionDomain.BASH,
            sensitive=True,
        )

    @staticmethod
    def _spec_preview_safe_rewind() -> ToolSpec:
        return ToolSpec(
            name="preview_safe_rewind",
            description="Preview a safe rewind for the conversation, workspace, or both without changing state. Use this tool when the user asks to undo recent workspace or session changes safely, and prefer preview before execute when the user wants to see what would be reverted. The session_id should be the real target session id, or 'current' for the active session; workspace_only fits file rollback, conversation_only fits branch rollback, and conversation_and_workspace fits both.",
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "checkpoint_id": {"type": "string"},
                    "turn_count": {"type": "integer"},
                    "message_count": {"type": "integer"},
                    "mode": {
                        "type": "string",
                        "enum": ["conversation_and_workspace", "workspace_only", "conversation_only"],
                    },
                    "allow_stash_snapshot": {"type": "boolean"},
                },
                "required": ["session_id"],
            },
            permission_domain=PermissionDomain.REPO,
        )

    @staticmethod
    def _spec_execute_safe_rewind() -> ToolSpec:
        return ToolSpec(
            name="execute_safe_rewind",
            description="Execute a safe rewind for the conversation, workspace, or both. Use this after preview_safe_rewind when the user confirms they want to revert recent changes safely. The session_id should be the real target session id, or 'current' for the active session; workspace_only fits file rollback, conversation_only fits branch rollback, and conversation_and_workspace fits both.",
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "checkpoint_id": {"type": "string"},
                    "turn_count": {"type": "integer"},
                    "message_count": {"type": "integer"},
                    "mode": {
                        "type": "string",
                        "enum": ["conversation_and_workspace", "workspace_only", "conversation_only"],
                    },
                    "allow_stash_snapshot": {"type": "boolean"},
                },
                "required": ["session_id"],
            },
            requires_confirmation=True,
            permission_domain=PermissionDomain.REPO,
            sensitive=True,
        )

    @staticmethod
    def _category_for(name: str) -> str:
        if name in {"read_file", "write_file", "edit_file", "list_files"}:
            return "files"
        if name in {"git_status", "git_diff_worktree", "grep_code", "search_text", "preview_safe_rewind", "execute_safe_rewind"}:
            return "repo"
        if name in {
            "list_attachments",
            "inspect_attachment",
            "search_attachment",
            "read_attachment_chunk",
            "read_attachment_text",
            "read_attachment_range",
            "search_attachment_symbols",
            "read_attachment_symbol",
        }:
            return "attachments"
        if name == "run_shell":
            return "shell"
        return "approvals"

    @staticmethod
    def _tool_family_for(name: str, category: str) -> str | None:
        if name in {"read_file", "write_file", "edit_file"}:
            return "file"
        if name == "run_shell":
            return "shell"
        if category == "mcp":
            return "mcp"
        if category == "extension":
            return "extension"
        return None
