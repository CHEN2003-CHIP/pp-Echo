from __future__ import annotations

from dataclasses import dataclass
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
from pp_agent.tools.metadata import ToolMetadata
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
    def __init__(self, workspace: Path, policy: Optional[ToolPolicyConfig] = None) -> None:
        """
        初始化工具注册中心
        :param workspace: 工作空间根目录（工具操作的安全边界）
        :param policy: 工具安全策略（确认弹窗、执行超时等）
        """
        self.workspace = workspace.resolve()
        self.policy = policy or ToolPolicyConfig()
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
        replace: bool = False,
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
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=parameters or {"type": "object", "properties": {}},
            requires_confirmation=requires_confirmation,
        )

        class _FunctionTool(BaseTool):
            @property
            def spec(self) -> ToolSpec:
                return spec.model_copy(deep=True)

            def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
                result = executor(self.workspace, arguments)
                if isinstance(result, ToolExecutionResult):
                    return result
                if hasattr(result, "model_dump"):
                    payload = result.model_dump(mode="python")
                    return ToolExecutionResult(**payload)
                return ToolExecutionResult(tool_call_id="", tool_name=name, content=str(result))

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

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        """
        【核心方法】执行工具
        :param name: 工具名
        :param arguments: 参数字典
        :return: 标准化执行结果
        """
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
            for name in self._registrations
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
            self._registration("read_file", self._spec_read_file, lambda: ReadFileTool(self.workspace)),
            self._registration("write_file", self._spec_write_file, lambda: WriteFileTool(self.workspace)),
            self._registration("edit_file", self._spec_edit_file, lambda: EditFileTool(self.workspace)),
            self._registration("preview_pending_action", self._spec_preview_pending_action, lambda: PreviewPendingActionTool(self.workspace)),
            self._registration("approve_pending_action", self._spec_approve_pending_action, lambda: ApprovePendingActionTool(self.workspace)),
            self._registration("reject_pending_action", self._spec_reject_pending_action, lambda: RejectPendingActionTool(self.workspace)),
            self._registration("list_pending_actions", self._spec_list_pending_actions, lambda: ListPendingActionsTool(self.workspace)),
            self._registration("list_files", self._spec_list_files, lambda: ListFilesTool(self.workspace)),
            self._registration("search_text", self._spec_search_text, lambda: SearchTextTool(self.workspace)),
            self._registration("grep_code", self._spec_grep_code, lambda: GrepCodeTool(self.workspace)),
            self._registration("git_status", self._spec_git_status, lambda: GitStatusTool(self.workspace)),
            self._registration("git_diff_worktree", self._spec_git_diff_worktree, lambda: GitDiffWorktreeTool(self.workspace)),
            self._registration("preview_safe_rewind", self._spec_preview_safe_rewind, lambda: PreviewSafeRewindTool(self.workspace)),
            self._registration("execute_safe_rewind", self._spec_execute_safe_rewind, lambda: ExecuteSafeRewindTool(self.workspace)),
            self._registration(
                "run_shell",
                self._spec_run_shell,
                lambda: PowerShellTool(self.workspace, default_timeout_seconds=self.policy.shell_timeout_seconds),
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
            ),
        )

    @staticmethod
    def _spec_read_file() -> ToolSpec:
        return ToolSpec(
            name="read_file",
            description="Read the contents of a UTF-8 text file.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        )

    @staticmethod
    def _spec_write_file() -> ToolSpec:
        return ToolSpec(
            name="write_file",
            description="Stage a new file write by default. Set apply=true to write immediately after confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                    "apply": {"type": "boolean"},
                },
                "required": ["path", "content"],
            },
            requires_confirmation=True,
        )

    @staticmethod
    def _spec_edit_file() -> ToolSpec:
        return ToolSpec(
            name="edit_file",
            description="Stage a safe diff-style edit using SEARCH/REPLACE blocks. Set apply=true to apply immediately.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "diff": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "apply": {"type": "boolean"},
                },
                "required": ["path"],
            },
            requires_confirmation=True,
        )

    @staticmethod
    def _spec_preview_pending_action() -> ToolSpec:
        return ToolSpec(
            name="preview_pending_action",
            description="Preview a staged action by token, including diff or command details.",
            parameters={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]},
        )

    @staticmethod
    def _spec_approve_pending_action() -> ToolSpec:
        return ToolSpec(
            name="approve_pending_action",
            description="Approve and execute a previously staged file edit or shell command by token.",
            parameters={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]},
            requires_confirmation=True,
        )

    @staticmethod
    def _spec_reject_pending_action() -> ToolSpec:
        return ToolSpec(
            name="reject_pending_action",
            description="Reject and remove a staged file edit or shell command by token.",
            parameters={"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]},
            requires_confirmation=True,
        )

    @staticmethod
    def _spec_list_pending_actions() -> ToolSpec:
        return ToolSpec(
            name="list_pending_actions",
            description="List staged actions waiting for approval.",
            parameters={"type": "object", "properties": {}},
        )

    @staticmethod
    def _spec_list_files() -> ToolSpec:
        return ToolSpec(
            name="list_files",
            description="List files and directories inside a path.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        )

    @staticmethod
    def _spec_search_text() -> ToolSpec:
        return ToolSpec(
            name="search_text",
            description="Search for text inside files under the workspace.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}, "path": {"type": "string"}},
                "required": ["query"],
            },
        )

    @staticmethod
    def _spec_grep_code() -> ToolSpec:
        return ToolSpec(
            name="grep_code",
            description="Search code text under the workspace, optimized for coding tasks.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}, "path": {"type": "string"}},
                "required": ["query"],
            },
        )

    @staticmethod
    def _spec_git_status() -> ToolSpec:
        return ToolSpec(
            name="git_status",
            description="Show git worktree status for the current workspace.",
            parameters={"type": "object", "properties": {}},
        )

    @staticmethod
    def _spec_git_diff_worktree() -> ToolSpec:
        return ToolSpec(
            name="git_diff_worktree",
            description="Show git diff for the current worktree or a single path.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        )

    @staticmethod
    def _spec_run_shell() -> ToolSpec:
        return ToolSpec(
            name="run_shell",
            description="Stage a PowerShell command for approval by default. Set apply=true to run immediately after confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                    "apply": {"type": "boolean"},
                },
                "required": ["command"],
            },
            requires_confirmation=True,
        )

    @staticmethod
    def _spec_preview_safe_rewind() -> ToolSpec:
        return ToolSpec(
            name="preview_safe_rewind",
            description="Preview a safe rewind for the conversation, workspace, or both without changing state.",
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
        )

    @staticmethod
    def _spec_execute_safe_rewind() -> ToolSpec:
        return ToolSpec(
            name="execute_safe_rewind",
            description="Execute a safe rewind for the conversation, workspace, or both.",
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
