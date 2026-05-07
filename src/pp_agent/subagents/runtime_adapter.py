from __future__ import annotations

from typing import Any, Optional


class SubAgentTurnLimitReached(RuntimeError):
    pass


class _LimitedLLMClient:
    """Child-only LLM wrapper that enforces a prompt-call budget without mutating the shared client."""

    def __init__(self, base_client: Any, *, max_turns: int) -> None:
        self._base_client = base_client
        self._max_turns = max_turns
        self._call_count = 0
        self.model = getattr(base_client, "model", None)
        self.provider = getattr(base_client, "provider", None)

    def stream_chat(self, messages, tools=None):
        self._call_count += 1
        if self._call_count > self._max_turns:
            raise SubAgentTurnLimitReached(f"Subagent exceeded max_turns={self._max_turns}.")
        yield from self._base_client.stream_chat(messages, tools=tools)


class SubAgentRuntimeAdapter:
    """Small compatibility layer between SubAgentManager and AgentRuntime-like objects."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    @property
    def session_id(self) -> str:
        return getattr(self._runtime, "session_id", "")

    @property
    def turn_id(self) -> int:
        state = getattr(self._runtime, "state", None)
        turn = getattr(state, "turn", None)
        return int(getattr(turn, "turn_id", 0) or 0)

    def restore_session_record(self, record: Any, *, emit_event: bool = False) -> None:
        self._runtime.restore_session_record(record, emit_event=emit_event)

    def set_system_prompt(self, value: str) -> None:
        self._runtime.state.system_prompt = value

    def set_require_plan_approval(self, value: bool) -> None:
        self._runtime.require_plan_approval = value

    def set_tool_registry(self, registry: Any) -> None:
        self._runtime.tool_registry = registry

    def set_model_override(self, model_name: Optional[str]) -> None:
        if not model_name:
            return
        llm_client = getattr(self._runtime, "llm_client", None)
        if llm_client is not None and hasattr(llm_client, "model"):
            llm_client.model = llm_client.model.model_copy(update={"model": model_name})
        state = getattr(self._runtime, "state", None)
        if state is not None and hasattr(state, "model"):
            state.model = state.model.model_copy(update={"model": model_name})

    def queue_lifecycle_event(
        self,
        event_type: str,
        *,
        message: Optional[str] = None,
        details: Optional[dict[str, object]] = None,
        is_error: bool = False,
    ) -> None:
        if not hasattr(self._runtime, "_event"):
            return
        event = self._runtime._event(  # type: ignore[attr-defined]
            event_type,
            message=message,
            details=details or {},
            is_error=is_error,
        )
        if hasattr(self._runtime, "_queue_lifecycle_event"):
            self._runtime._queue_lifecycle_event(event)  # type: ignore[attr-defined]
            return
        if hasattr(self._runtime, "_emit"):
            list(self._runtime._emit(event))  # type: ignore[attr-defined]

    def emit_lifecycle_event(
        self,
        event_type: str,
        *,
        message: Optional[str] = None,
        details: Optional[dict[str, object]] = None,
        is_error: bool = False,
    ) -> None:
        if not hasattr(self._runtime, "_event") or not hasattr(self._runtime, "_emit"):
            return
        event = self._runtime._event(  # type: ignore[attr-defined]
            event_type,
            message=message,
            details=details or {},
            is_error=is_error,
        )
        list(self._runtime._emit(event))  # type: ignore[attr-defined]

    def prompt(self, prompt_text: str, *, max_turns: int = 1):
        llm_client = getattr(self._runtime, "llm_client", None)
        stream_chat = getattr(llm_client, "stream_chat", None)
        if llm_client is None or not callable(stream_chat) or max_turns <= 0:
            return self._runtime.prompt(prompt_text)
        original_client = llm_client
        self._runtime.llm_client = _LimitedLLMClient(original_client, max_turns=max_turns)
        try:
            return self._runtime.prompt(prompt_text)
        finally:
            self._runtime.llm_client = original_client

    def extract_final_text(self) -> str:
        messages = getattr(self._runtime.state, "messages", [])
        for message in reversed(messages):
            if getattr(message, "role", None) != "assistant":
                continue
            parts = [part.text.strip() for part in getattr(message, "content", []) if getattr(part, "text", "").strip()]
            text = "\n".join(parts).strip()
            if text:
                return text
        return ""
