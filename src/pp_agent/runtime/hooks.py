from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from pydantic import BaseModel, Field

from pp_agent.domain import ChatMessage, ToolCall
from pp_agent.runtime.emitter import LifecycleEmitter
from pp_agent.runtime.lifecycle import (
    ContextBuildDecision,
    ToolCallDecision as LifecycleToolCallDecision,
    ToolErrorDecision as LifecycleToolErrorDecision,
    ToolResultDecision as LifecycleToolResultDecision,
)
from pp_agent.runtime.state import AgentState
from pp_agent.tools.base import ToolExecutionResult
from pp_agent.tools.registry import ToolRegistry


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


TransformContextHook = Callable[[AgentState, list[ChatMessage]], list[ChatMessage]]
BeforeToolCallHook = Callable[[AgentState, ToolCall, ToolRegistry], BeforeToolCallDecision]
AfterToolCallHook = Callable[[AgentState, ToolCall, ToolExecutionResult], AfterToolCallDecision]
ToolErrorHook = Callable[[AgentState, ToolCall, Exception], ToolErrorDecision]


class RuntimeHooks:
    def __init__(
        self,
        transform_context: Optional[list[TransformContextHook]] = None,
        before_tool_call: Optional[list[BeforeToolCallHook]] = None,
        after_tool_call: Optional[list[AfterToolCallHook]] = None,
        on_tool_error: Optional[list[ToolErrorHook]] = None,
    ) -> None:
        self.transform_context_hooks = transform_context or []
        self.before_tool_call_hooks = before_tool_call or []
        self.after_tool_call_hooks = after_tool_call or []
        self.on_tool_error_hooks = on_tool_error or []

    def transform_context(self, state: AgentState, messages: list[ChatMessage]) -> list[ChatMessage]:
        current = messages
        for hook in self.transform_context_hooks:
            current = hook(state, current)
        return current

    def before_tool_call(self, state: AgentState, call: ToolCall, registry: ToolRegistry) -> BeforeToolCallDecision:
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
        final = AfterToolCallDecision()
        for hook in self.after_tool_call_hooks:
            decision = hook(state, call, result)
            final.continue_loop = final.continue_loop and decision.continue_loop
            if decision.details:
                final.details.update(decision.details)
        return final

    def on_tool_error(self, state: AgentState, call: ToolCall, error: Exception) -> ToolErrorDecision:
        final = ToolErrorDecision()
        for hook in self.on_tool_error_hooks:
            decision = hook(state, call, error)
            final.continue_loop = final.continue_loop or decision.continue_loop
            if decision.details:
                final.details.update(decision.details)
        return final

    def register_with_lifecycle(self, emitter: LifecycleEmitter) -> None:
        emitter.on_context_built(self._handle_context_built)
        emitter.on_tool_call(self._handle_tool_call)
        emitter.on_tool_result(self._handle_tool_result)
        emitter.on_tool_error(self._handle_tool_error)

    def _handle_context_built(self, event, messages: list[ChatMessage]) -> ContextBuildDecision:
        state = event.details.get("state")
        if not isinstance(state, AgentState):
            return ContextBuildDecision(messages=messages)
        return ContextBuildDecision(messages=self.transform_context(state, messages))

    def _handle_tool_call(self, event) -> LifecycleToolCallDecision:
        state = event.details.get("state")
        call = event.details.get("tool_call")
        registry = event.details.get("tool_registry")
        if not isinstance(state, AgentState) or not isinstance(call, ToolCall) or not isinstance(registry, ToolRegistry):
            return LifecycleToolCallDecision()
        decision = self.before_tool_call(state, call, registry)
        return LifecycleToolCallDecision(action=decision.action, message=decision.message, details=decision.details)

    def _handle_tool_result(self, event, result: ToolExecutionResult) -> LifecycleToolResultDecision:
        state = event.details.get("state")
        call = event.details.get("tool_call")
        if not isinstance(state, AgentState) or not isinstance(call, ToolCall):
            return LifecycleToolResultDecision(result=result)
        decision = self.after_tool_call(state, call, result)
        return LifecycleToolResultDecision(continue_loop=decision.continue_loop, details=decision.details, result=result)

    def _handle_tool_error(self, event, error: Exception) -> LifecycleToolErrorDecision:
        state = event.details.get("state")
        call = event.details.get("tool_call")
        if not isinstance(state, AgentState) or not isinstance(call, ToolCall):
            return LifecycleToolErrorDecision()
        decision = self.on_tool_error(state, call, error)
        return LifecycleToolErrorDecision(continue_loop=decision.continue_loop, details=decision.details)
