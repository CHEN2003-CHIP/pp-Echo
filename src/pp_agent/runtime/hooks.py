from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from typing import TYPE_CHECKING
from typing import Literal
from typing import Optional

from pydantic import BaseModel, Field

from pp_agent.domain import ChatMessage, ToolCall
from pp_agent.runtime.emitter import LifecycleSubscriber
from pp_agent.runtime.emitter import LifecycleEmitter
from pp_agent.runtime.lifecycle import (
    ContextBuildDecision,
    ToolCallDecision as LifecycleToolCallDecision,
    ToolErrorDecision as LifecycleToolErrorDecision,
    ToolResultDecision as LifecycleToolResultDecision,
)
from pp_agent.runtime.state import AgentState
from pp_agent.tools.base import ToolExecutionResult

if TYPE_CHECKING:
    from pp_agent.tools.registry import ToolRegistry
else:
    ToolRegistry = Any


class BeforeToolCallDecision(BaseModel):
    action: str = "allow"
    message: Optional[str] = None
    details: dict[str, object] = Field(default_factory=dict)


class AfterToolCallDecision(BaseModel):
    continue_loop: bool = True
    details: dict[str, object] = Field(default_factory=dict)


class ToolErrorDecision(BaseModel):
    continue_loop: bool = False
    details: dict[str, object] = Field(default_factory=dict)

# 定义各种钩子类型
TransformContextHook = Callable[[AgentState, list[ChatMessage]], list[ChatMessage]]
BeforeToolCallHook = Callable[[AgentState, ToolCall, ToolRegistry], BeforeToolCallDecision]
AfterToolCallHook = Callable[[AgentState, ToolCall, ToolExecutionResult], AfterToolCallDecision]
ToolErrorHook = Callable[[AgentState, ToolCall, Exception], ToolErrorDecision]
ContextHookKind = Literal["mcp", "skill", "memory", "project_memory", "extension", "runtime"]


@dataclass(frozen=True)
class ContextHookEntry:
    name: str
    kind: ContextHookKind
    fn: TransformContextHook
    enabled_for_subagent: bool = False

    def __call__(self, state: AgentState, messages: list[ChatMessage]) -> list[ChatMessage]:
        return self.fn(state, messages)


class RuntimeHooks:
    def __init__(
        self,
        transform_context: Optional[list[TransformContextHook | ContextHookEntry]] = None,
        before_tool_call: Optional[list[BeforeToolCallHook]] = None,
        after_tool_call: Optional[list[AfterToolCallHook]] = None,
        on_tool_error: Optional[list[ToolErrorHook]] = None,
        lifecycle_event: Optional[list[LifecycleSubscriber]] = None,
    ) -> None:
        self.transform_context_hooks = transform_context or []
        self.before_tool_call_hooks = before_tool_call or []
        self.after_tool_call_hooks = after_tool_call or []
        self.on_tool_error_hooks = on_tool_error or []
        self.lifecycle_event_hooks = lifecycle_event or []

    def snapshot(self) -> dict[str, list[Callable]]:
        # 创建当前钩子配置的快照，便于后续恢复
        return {
            "transform_context": list(self.transform_context_hooks),
            "before_tool_call": list(self.before_tool_call_hooks),
            "after_tool_call": list(self.after_tool_call_hooks),
            "on_tool_error": list(self.on_tool_error_hooks),
            "lifecycle_event": list(self.lifecycle_event_hooks),
        }

    def restore(self, snapshot: dict[str, list[Callable]]) -> None:
        # 恢复之前的钩子配置
        self.transform_context_hooks = list(snapshot.get("transform_context", []))
        self.before_tool_call_hooks = list(snapshot.get("before_tool_call", []))
        self.after_tool_call_hooks = list(snapshot.get("after_tool_call", []))
        self.on_tool_error_hooks = list(snapshot.get("on_tool_error", []))
        self.lifecycle_event_hooks = list(snapshot.get("lifecycle_event", []))

    def add_transform_context_hook(
        self,
        name: str,
        kind: ContextHookKind,
        fn: TransformContextHook,
        *,
        enabled_for_subagent: bool = False,
    ) -> None:
        self.transform_context_hooks.append(
            ContextHookEntry(
                name=name,
                kind=kind,
                fn=fn,
                enabled_for_subagent=enabled_for_subagent,
            )
        )

    def transform_context(self, state: AgentState, messages: list[ChatMessage]) -> list[ChatMessage]:
        # 调用所有 transform_context 钩子，对传入的消息列表进行转换
        current = messages
        for hook in self.transform_context_hooks:
            if isinstance(hook, ContextHookEntry):
                current = hook.fn(state, current)
            else:
                current = hook(state, current)
        return current

    def before_tool_call(self, state: AgentState, call: ToolCall, registry: ToolRegistry) -> BeforeToolCallDecision:
        # 调用所有 before_tool_call 钩子，获取最终的工具调用决策（如是否允许调用/修改调用参数等）
        final = BeforeToolCallDecision()
        for hook in self.before_tool_call_hooks:
            decision = hook(state, call, registry)
            if decision.details:
                final.details.update(decision.details)
            if decision.action != "allow":
                final.action = decision.action
                final.message = decision.message
                return final
            if decision.message:
                final.message = decision.message
        return final

    def after_tool_call(self, state: AgentState, call: ToolCall, result: ToolExecutionResult) -> AfterToolCallDecision:
        # 调用所有 after_tool_call 钩子，获取工具执行后的决策（如是否继续执行后续计划/修改结果内容等）
        final = AfterToolCallDecision()
        for hook in self.after_tool_call_hooks:
            decision = hook(state, call, result)
            final.continue_loop = final.continue_loop and decision.continue_loop
            if decision.details:
                final.details.update(decision.details)
        return final

    def on_tool_error(self, state: AgentState, call: ToolCall, error: Exception) -> ToolErrorDecision:
        # 调用所有 on_tool_error 钩子，获取工具执行出错时的决策（如是否忽略错误/继续执行后续计划等）
        final = ToolErrorDecision()
        for hook in self.on_tool_error_hooks:
            decision = hook(state, call, error)
            final.continue_loop = final.continue_loop or decision.continue_loop
            if decision.details:
                final.details.update(decision.details)
        return final

    def register_with_lifecycle(self, emitter: LifecycleEmitter) -> None:
        # 将当前钩子注册到生命周期事件发射器中，以便在相应事件发生时触发钩子逻辑
        emitter.subscribe(self._handle_lifecycle_event)
        emitter.on_context_built(self._handle_context_built)
        emitter.on_tool_call(self._handle_tool_call)
        emitter.on_tool_result(self._handle_tool_result)
        emitter.on_tool_error(self._handle_tool_error)

    def _handle_lifecycle_event(self, event) -> None:
        for hook in self.lifecycle_event_hooks:
            hook(event)

    def _handle_context_built(self, event, state: AgentState, messages: list[ChatMessage]) -> ContextBuildDecision:
        return ContextBuildDecision(messages=self.transform_context(state, messages))

    def _handle_tool_call(self, event, state: AgentState, call: ToolCall, registry: ToolRegistry) -> LifecycleToolCallDecision:
        decision = self.before_tool_call(state, call, registry)
        return LifecycleToolCallDecision(action=decision.action, message=decision.message, details=decision.details)

    def _handle_tool_result(self, event, state: AgentState, call: ToolCall, result: ToolExecutionResult) -> LifecycleToolResultDecision:
        decision = self.after_tool_call(state, call, result)
        return LifecycleToolResultDecision(continue_loop=decision.continue_loop, details=decision.details, result=result)

    def _handle_tool_error(self, event, state: AgentState, call: ToolCall, error: Exception) -> LifecycleToolErrorDecision:
        decision = self.on_tool_error(state, call, error)
        return LifecycleToolErrorDecision(continue_loop=decision.continue_loop, details=decision.details)
