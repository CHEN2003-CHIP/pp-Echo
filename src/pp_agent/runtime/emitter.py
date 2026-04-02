from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from pp_agent.domain import ChatMessage, ToolCall
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


LifecycleSubscriber = Callable[[AgentEvent], None]
ContextBuildHandler = Callable[[AgentEvent, list[ChatMessage]], ContextBuildDecision | list[ChatMessage] | None]
ProviderRequestHandler = Callable[[AgentEvent, list[ChatMessage], Optional[list[dict[str, Any]]]], ProviderRequestDecision | None]
ProviderResponseHandler = Callable[[AgentEvent, str, list[ToolCall]], ProviderResponseDecision | None]
ToolCallHandler = Callable[[AgentEvent], ToolCallDecision | None]
ToolResultHandler = Callable[[AgentEvent, ToolExecutionResult], ToolResultDecision | None]
ToolErrorHandler = Callable[[AgentEvent, Exception], ToolErrorDecision | None]
SessionCompactHandler = Callable[[AgentEvent], SessionCompactDecision | None]


class LifecycleEmitter:
    def __init__(self) -> None:
        self._subscribers: list[LifecycleSubscriber] = []
        self._context_built_handlers: list[ContextBuildHandler] = []
        self._provider_request_handlers: list[ProviderRequestHandler] = []
        self._provider_response_handlers: list[ProviderResponseHandler] = []
        self._tool_call_handlers: list[ToolCallHandler] = []
        self._tool_result_handlers: list[ToolResultHandler] = []
        self._tool_error_handlers: list[ToolErrorHandler] = []
        self._session_compact_handlers: list[SessionCompactHandler] = []

    def subscribe(self, callback: LifecycleSubscriber) -> None:
        self._subscribers.append(callback)

    def on_context_built(self, callback: ContextBuildHandler) -> None:
        self._context_built_handlers.append(callback)

    def on_before_provider_request(self, callback: ProviderRequestHandler) -> None:
        self._provider_request_handlers.append(callback)

    def on_provider_response(self, callback: ProviderResponseHandler) -> None:
        self._provider_response_handlers.append(callback)

    def on_tool_call(self, callback: ToolCallHandler) -> None:
        self._tool_call_handlers.append(callback)

    def on_tool_result(self, callback: ToolResultHandler) -> None:
        self._tool_result_handlers.append(callback)

    def on_tool_error(self, callback: ToolErrorHandler) -> None:
        self._tool_error_handlers.append(callback)

    def on_session_before_compact(self, callback: SessionCompactHandler) -> None:
        self._session_compact_handlers.append(callback)

    def emit(self, event: AgentEvent) -> AgentEvent:
        for callback in self._subscribers:
            callback(event)
        return event

    def emit_context_built(self, event: AgentEvent, messages: list[ChatMessage]) -> ContextBuildDecision:
        final = ContextBuildDecision(messages=messages)
        for callback in self._context_built_handlers:
            decision = callback(event, final.messages or messages)
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
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]],
    ) -> ProviderRequestDecision:
        final = ProviderRequestDecision(messages=messages, tools=tools)
        for callback in self._provider_request_handlers:
            decision = callback(event, final.messages or messages, final.tools if final.tools is not None else tools)
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

    def emit_tool_call(self, event: AgentEvent) -> ToolCallDecision:
        final = ToolCallDecision()
        for callback in self._tool_call_handlers:
            decision = callback(event)
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

    def emit_tool_result(self, event: AgentEvent, result: ToolExecutionResult) -> ToolResultDecision:
        final = ToolResultDecision(result=result)
        for callback in self._tool_result_handlers:
            decision = callback(event, final.result or result)
            if decision is None:
                continue
            final.continue_loop = final.continue_loop and decision.continue_loop
            if decision.result is not None:
                final.result = decision.result
            if decision.details:
                final.details.update(decision.details)
        return final

    def emit_tool_error(self, event: AgentEvent, error: Exception) -> ToolErrorDecision:
        final = ToolErrorDecision()
        for callback in self._tool_error_handlers:
            decision = callback(event, error)
            if decision is None:
                continue
            final.continue_loop = final.continue_loop or decision.continue_loop
            if decision.details:
                final.details.update(decision.details)
        return final

    def emit_session_before_compact(self, event: AgentEvent) -> SessionCompactDecision:
        final = SessionCompactDecision()
        for callback in self._session_compact_handlers:
            decision = callback(event)
            if decision is None:
                continue
            final.allow = final.allow and decision.allow
            if decision.details:
                final.details.update(decision.details)
        return final
