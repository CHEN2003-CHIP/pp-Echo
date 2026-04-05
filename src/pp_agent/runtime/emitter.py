from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional, Union

from pp_agent.domain import ChatMessage, ToolCall
from pp_agent.runtime.state import AgentState
from pp_agent.runtime.lifecycle import (
    ContextBuildDecision,
    ProviderRequestDecision,
    ProviderResponseDecision,
    SessionCompactDecision,
    ToolCallDecision,
    ToolErrorDecision,
    ToolResultDecision,
)
from pp_agent.runtime.state import AgentEvent
from pp_agent.tools.base import ToolExecutionResult

#基础通用型
LifecycleSubscriber = Callable[[AgentEvent], None]
#上下文构建处理器
ContextBuildHandler = Callable[[AgentEvent, AgentState, list[ChatMessage]], Optional[Union[ContextBuildDecision, list[ChatMessage]]]]
#模型请求处理器
ProviderRequestHandler = Callable[[AgentEvent, AgentState, list[ChatMessage], Optional[list[dict[str, Any]]]], Optional[ProviderRequestDecision]]
#模型响应处理器
ProviderResponseHandler = Callable[[AgentEvent, str, list[ToolCall]], Optional[ProviderResponseDecision]]
#工具调用处理器
ToolCallHandler = Callable[[AgentEvent, AgentState, ToolCall, Any], Optional[ToolCallDecision]]
#工具结果处理器
ToolResultHandler = Callable[[AgentEvent, AgentState, ToolCall, ToolExecutionResult], Optional[ToolResultDecision]]
#工具错误处理器
ToolErrorHandler = Callable[[AgentEvent, AgentState, ToolCall, Exception], Optional[ToolErrorDecision]]
#会话压缩处理器
SessionCompactHandler = Callable[[AgentEvent], Optional[SessionCompactDecision]]


class LifecycleEmitter:
    def __init__(self) -> None:
        # 通用事件订阅者（监听所有事件）
        self._subscribers: list[LifecycleSubscriber] = []
        # 上下文构建完成钩子
        self._context_built_handlers: list[ContextBuildHandler] = []
        # 模型请求前钩子
        self._provider_request_handlers: list[ProviderRequestHandler] = []
        # 模型响应后钩子
        self._provider_response_handlers: list[ProviderResponseHandler] = []
        # 工具执行前钩子
        self._tool_call_handlers: list[ToolCallHandler] = []
        # 工具执行后钩子
        self._tool_result_handlers: list[ToolResultHandler] = []
        # 工具执行出错钩子
        self._tool_error_handlers: list[ToolErrorHandler] = []
        # 会话压缩前钩子
        self._session_compact_handlers: list[SessionCompactHandler] = []


    def subscribe(self, callback: LifecycleSubscriber) -> None:
        # 订阅所有事件（通用日志/监控）
        self._subscribers.append(callback)

    def on_context_built(self, callback: ContextBuildHandler) -> None:
        # 上下文构建完成钩子
        self._context_built_handlers.append(callback)

    def on_before_provider_request(self, callback: ProviderRequestHandler) -> None:
        # 模型请求前钩子
        self._provider_request_handlers.append(callback)

    def on_provider_response(self, callback: ProviderResponseHandler) -> None:
        # 模型响应后钩子
        self._provider_response_handlers.append(callback)

    def on_tool_call(self, callback: ToolCallHandler) -> None:
        # 工具执行前钩子
        self._tool_call_handlers.append(callback)

    def on_tool_result(self, callback: ToolResultHandler) -> None:
        # 工具执行后钩子
        self._tool_result_handlers.append(callback)

    def on_tool_error(self, callback: ToolErrorHandler) -> None:
        # 工具执行出错钩子
        self._tool_error_handlers.append(callback)

    def on_session_before_compact(self, callback: SessionCompactHandler) -> None:
        # 会话压缩前钩子
        self._session_compact_handlers.append(callback)

    def emit(self, event: AgentEvent) -> AgentEvent:
        # 触发事件,通知所有订阅者
        for callback in self._subscribers:
            callback(event)
        return event

    def emit_context_built(self, event: AgentEvent, state: AgentState, messages: list[ChatMessage]) -> ContextBuildDecision:
        # 上下文构建完成事件，允许订阅者修改最终输入模型的消息列表（如添加隐式消息/修改消息内容等）
        final = ContextBuildDecision(messages=messages)
        for callback in self._context_built_handlers:
            decision = callback(event, state, final.messages or messages)
            if decision is None:
                continue
            if isinstance(decision, list):
                final.messages = decision
                continue
            if decision.messages is not None:
                final.messages = decision.messages
            if decision.details:
                final.details.update(decision.details)
        return final

    def emit_before_provider_request(
        self,
        event: AgentEvent,
        state: AgentState,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]],
    ) -> ProviderRequestDecision:
        # 模型请求前事件，允许订阅者修改最终输入模型的消息列表和工具列表（如添加隐式消息/修改消息内容/动态增加工具等）
        final = ProviderRequestDecision(messages=messages, tools=tools)
        for callback in self._provider_request_handlers:
            decision = callback(event, state, final.messages or messages, final.tools if final.tools is not None else tools)
            if decision is None:
                continue
            if decision.messages is not None:
                final.messages = decision.messages
            if decision.tools is not None:
                final.tools = decision.tools
            if decision.details:
                final.details.update(decision.details)
        return final

    def emit_provider_response(self, event: AgentEvent, assistant_text: str, tool_calls: list[ToolCall]) -> ProviderResponseDecision:
        # 模型响应后事件，允许订阅者修改最终的助手文本和工具调用列表（如修改助手文本内容/动态增加工具调用等）
        final = ProviderResponseDecision(assistant_text=assistant_text, tool_calls=tool_calls)
        for callback in self._provider_response_handlers:
            decision = callback(event, final.assistant_text or "", final.tool_calls or [])
            if decision is None:
                continue
            if decision.assistant_text is not None:
                final.assistant_text = decision.assistant_text
            if decision.tool_calls is not None:
                final.tool_calls = decision.tool_calls
            if decision.details:
                final.details.update(decision.details)
        return final

    def emit_tool_call(self, event: AgentEvent, state: AgentState, call: ToolCall, registry: Any) -> ToolCallDecision:
        # 工具调用事件，允许订阅者修改工具调用的决策（如阻止调用/修改调用参数等）
        final = ToolCallDecision()
        for callback in self._tool_call_handlers:
            decision = callback(event, state, call, registry)
            if decision is None:
                continue
            if decision.details:
                final.details.update(decision.details)
            if decision.action != "allow":
                final.action = decision.action
                final.message = decision.message
                return final
            if decision.message:
                final.message = decision.message
        return final

    def emit_tool_result(self, event: AgentEvent, state: AgentState, call: ToolCall, result: ToolExecutionResult) -> ToolResultDecision:
        # 工具执行后事件，允许订阅者修改工具执行结果（如修改结果内容/影响后续流程等）
        final = ToolResultDecision(result=result)
        for callback in self._tool_result_handlers:
            decision = callback(event, state, call, final.result or result)
            if decision is None:
                continue
            final.continue_loop = final.continue_loop and decision.continue_loop
            if decision.result is not None:
                final.result = decision.result
            if decision.details:
                final.details.update(decision.details)
        return final

    def emit_tool_error(self, event: AgentEvent, state: AgentState, call: ToolCall, error: Exception) -> ToolErrorDecision:
        # 工具执行出错事件，允许订阅者修改错误处理决策（如忽略错误/重新尝试等）
        final = ToolErrorDecision()
        for callback in self._tool_error_handlers:
            decision = callback(event, state, call, error)
            if decision is None:
                continue
            final.continue_loop = final.continue_loop or decision.continue_loop
            if decision.details:
                final.details.update(decision.details)
        return final

    def emit_session_before_compact(self, event: AgentEvent) -> SessionCompactDecision:
        # 会话压缩前事件，允许订阅者修改压缩决策（如阻止压缩/添加额外消息等）
        final = SessionCompactDecision()
        for callback in self._session_compact_handlers:
            decision = callback(event)
            if decision is None:
                continue
            final.allow = final.allow and decision.allow
            if decision.details:
                final.details.update(decision.details)
        return final
