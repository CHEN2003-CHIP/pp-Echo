from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Optional, Union

from pp_agent.domain import ToolCall, ToolSpec
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
)
from pp_agent.tools.effects import (
    analyze_extension_call,
    analyze_file_call,
    analyze_mcp_call,
    build_dynamic_tool_effect,
    build_shell_effect,
    dynamic_tool_declarations,
)
from pp_agent.tools.metadata import ToolMetadata
from pp_agent.tools.policy import ALLOW, ASK, PermissionDomain, ToolPolicyEvaluator
from pp_agent.tools.repo_tools import GitDiffWorktreeTool, GitStatusTool, GrepCodeTool
from pp_agent.tools.search_tool import SearchTextTool
from pp_agent.tools.session_tools import ExecuteSafeRewindTool, PreviewSafeRewindTool
from pp_agent.tools.shell_tool import PowerShellTool


SpecFactory = Callable[[], ToolSpec]
ToolFactory = Callable[[], BaseTool]
ToolExecutor = Callable[[Path, dict[str, Any]], Union[ToolExecutionResult, str]]


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
    【核心服务】工具注册中心
    【业务功能】统一管理所有AI工具：注册、查询、执行、权限控制、动态扩展
    【架构角色】工具层入口，隔离工具实现与调用方
    【安全策略】支持执行前确认、超时控制、动态开关
    """
    def __init__(self, workspace: Path, policy: Optional[ToolPolicyConfig] = None, current_session_id: Optional[str] = None) -> None:
        """
        初始化工具注册中心
        :param workspace: 工作空间根目录（工具操作的安全边界）
        :param policy: 工具安全策略（确认弹窗、执行超时等）
        """
        self.workspace = workspace.resolve()
        self.policy = policy or ToolPolicyConfig()
        self.policy_evaluator = ToolPolicyEvaluator(
            self.workspace,
            permission_mode=self.policy.permission_mode,
            allowed_tools=self.policy.allowed_tools,
            denied_tools=self.policy.denied_tools,
            ask_tools=self.policy.ask_tools,
        )
        self.current_session_id = current_session_id
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
        :param name: 工具名
        :param description: 工具描述（给AI看）
        :param parameters: 入参定义
        :param executor: 执行函数
        :param category: 分类
        :param requires_confirmation: 是否需要确认
        :param replace: 是否覆盖
        """
        if deprecated_kwargs:
            legacy_fields = [field for field in ("analysis_hints", "legacy_hint_origin") if field in deprecated_kwargs]
            if legacy_fields:
                joined = ", ".join(legacy_fields)
                raise TypeError(
                    f"register_function_tool() no longer accepts author-facing legacy fields: {joined}. "
                    "Use formal declarations only: exact_effect_mode, non_side_effectful, known_safe_inspect, "
                    "requests_network_hint, and touches_external_hint. Runtime-only risk overrides must use the private internal registration helper."
                )
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
            runtime_risk_overrides=None,
            legacy_hint_origin="author",
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
        runtime_risk_overrides: Optional[dict[str, Any]] = None,
        legacy_hint_origin: str = "runtime_internal",
        exact_effect_mode: str = "auto",
        non_side_effectful: bool = False,
        known_safe_inspect: bool = False,
        requests_network_hint: bool = False,
        touches_external_hint: bool = False,
        replace: bool = False,
    ) -> None:
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
                    analysis_hints=dict(runtime_risk_overrides or {}),
                    legacy_hint_origin=legacy_hint_origin,
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

    def metadata(self) -> dict[str, ToolMetadata]:
        """
        【公共方法】获取所有工具元数据（供前端展示/权限面板）
        """
        return {
            name: registration.metadata.model_copy(deep=True)
            for name, registration in self._registrations.items()
        }

    def clone_selected(self, names: list[str], *, current_session_id: Optional[str] = None) -> "ToolRegistry":
        cloned = ToolRegistry(
            self.workspace,
            policy=self.policy.model_copy(deep=True),
            current_session_id=current_session_id,
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
        return cloned

    def evaluate_call(self, name: str, arguments: dict[str, Any]):
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
        result = self._get_tool(name).execute(arguments)
        result.tool_name = name
        return result

    def host_execute_dynamic_approved(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        tool = self._get_tool(name)
        execute_host_approved = getattr(tool, "execute_host_approved", None)
        if execute_host_approved is None:
            raise ValueError(f"Tool '{name}' does not support host-approved dynamic execution")
        result = execute_host_approved(arguments)
        result.tool_name = name
        return result

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        """
        【核心方法】执行工具
        :param name: 工具名
        :param arguments: 参数字典
        :return: 标准化执行结果
        """
        registration = self._registrations[name]
        if not registration.metadata.model_callable:
            raise PermissionError(f"Tool '{name}' is host-only and not model-callable")
        decision = self.evaluate_call(name, arguments)
        if decision.action == "deny":
            raise PermissionError(decision.reason)
        result = self._get_tool(name).execute(arguments)
        result.tool_name = name
        return result

    def error_result(self, call: ToolCall, message: str) -> ToolExecutionResult:
        """
        【公共方法】生成工具执行错误结果（统一错误格式）
        """
        return self._get_tool(call.name).error_result(call, message)

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
            if registration.metadata.model_callable
        ]

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
            self._registration("read_file", self._spec_read_file, lambda: ReadFileTool(self.workspace, self.policy_evaluator)),
            self._registration("write_file", self._spec_write_file, lambda: WriteFileTool(self.workspace, self.policy_evaluator)),
            self._registration("edit_file", self._spec_edit_file, lambda: EditFileTool(self.workspace, self.policy_evaluator)),
            self._registration("preview_pending_action", self._spec_preview_pending_action, lambda: PreviewPendingActionTool(self.workspace, self.policy_evaluator, tool_registry=self)),
            self._registration("approve_pending_action", self._spec_approve_pending_action, lambda: ApprovePendingActionTool(self.workspace, self.policy_evaluator, tool_registry=self)),
            self._registration("reject_pending_action", self._spec_reject_pending_action, lambda: RejectPendingActionTool(self.workspace, self.policy_evaluator)),
            self._registration("list_pending_actions", self._spec_list_pending_actions, lambda: ListPendingActionsTool(self.workspace, self.policy_evaluator)),
            self._registration("list_files", self._spec_list_files, lambda: ListFilesTool(self.workspace, self.policy_evaluator)),
            self._registration("search_text", self._spec_search_text, lambda: SearchTextTool(self.workspace, self.policy_evaluator)),
            self._registration("grep_code", self._spec_grep_code, lambda: GrepCodeTool(self.workspace, self.policy_evaluator)),
            self._registration("git_status", self._spec_git_status, lambda: GitStatusTool(self.workspace, self.policy_evaluator)),
            self._registration("git_diff_worktree", self._spec_git_diff_worktree, lambda: GitDiffWorktreeTool(self.workspace, self.policy_evaluator)),
            self._registration("preview_safe_rewind", self._spec_preview_safe_rewind, lambda: PreviewSafeRewindTool(self.workspace, current_session_id=self.current_session_id)),
            self._registration("execute_safe_rewind", self._spec_execute_safe_rewind, lambda: ExecuteSafeRewindTool(self.workspace, current_session_id=self.current_session_id)),
            self._registration(
                "run_shell",
                self._spec_run_shell,
                lambda: PowerShellTool(self.workspace, self.policy_evaluator, default_timeout_seconds=self.policy.shell_timeout_seconds),
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
            analysis_hints=dict(metadata.analysis_hints),
        )
        analysis["declaration_strength"] = metadata.declaration_strength
        analysis["uses_legacy_analysis_hints"] = metadata.uses_legacy_analysis_hints
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
        analysis_hints: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_family == "mcp":
            return analyze_mcp_call(
                tool_name=name,
                permission_domain=permission_domain,
                description=description,
                declarations=declarations,
                hints=analysis_hints,
            )
        return analyze_extension_call(
            tool_name=name,
            permission_domain=permission_domain,
            description=description,
            declarations=declarations,
            hints=analysis_hints,
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
            analysis_hints=dict(metadata.analysis_hints),
        )
        dynamic_analysis["declaration_strength"] = metadata.declaration_strength
        dynamic_analysis["uses_legacy_analysis_hints"] = metadata.uses_legacy_analysis_hints
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
