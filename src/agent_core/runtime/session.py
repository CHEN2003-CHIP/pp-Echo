from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from collections.abc import Callable, Iterator
from typing import Optional

from agent_core.llm.client import LLMClient, LLMClientError
from agent_core.runtime.compaction import ConversationCompactor
from agent_core.runtime.types import AgentEvent, AgentState, PlanStep
from agent_core.types import ChatMessage, TextPart, ToolCall, ToolCallPart
from storage.sessions import SessionRecord, SessionStore
from tools.pending_actions import PendingActionStore
from tools.registry import ToolRegistry


Subscriber = Callable[[AgentEvent], None]
ConfirmCallback = Callable[[str, dict], bool]


class AgentSession:
    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        session_store: SessionStore,
        session_id: str,
        system_prompt: str,
        confirm_callback: Optional[ConfirmCallback] = None,
        max_context_messages: int = 12,
        compact_after_messages: int = 8,
        initial_compaction=None,
        initial_pending_tool_calls: Optional[list[ToolCall]] = None,
        initial_pending_plan_token: Optional[str] = None,
        require_plan_approval: bool = True,
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.session_store = session_store
        self.session_id = session_id
        self.confirm_callback = confirm_callback or (lambda _name, _args: True)
        self.max_context_messages = max_context_messages
        self.require_plan_approval = require_plan_approval
        self.compactor = ConversationCompactor(keep_recent_messages=compact_after_messages)
        self.state = AgentState(system_prompt=system_prompt, model=llm_client.model.model_copy(deep=True))
        if initial_compaction is not None:
            self.state.compaction = initial_compaction.model_copy(deep=True)
        if initial_pending_tool_calls:
            self.state.pending_tool_calls = [call.model_copy(deep=True) for call in initial_pending_tool_calls]
        self.state.pending_plan_token = initial_pending_plan_token
        self._subscribers: list[Subscriber] = []
        self._approved_pending_plan = False

    def subscribe(self, callback: Subscriber) -> None:
        self._subscribers.append(callback)

    def prompt(self, text: str) -> list[AgentEvent]:
        user_message = ChatMessage(role="user", content=[TextPart(text=text)], timestamp=time.time())
        self.state.messages.append(user_message)
        return list(self._run_loop())

    def continue_(self) -> list[AgentEvent]:
        return list(self._run_loop())

    def approve_pending_plan(self, token: str) -> list[AgentEvent]:
        if token != self.state.pending_plan_token:
            raise ValueError(f"Token {token} does not match the pending planner gate for this session")
        self._pending_action_store().remove(token)
        self._approved_pending_plan = True
        return list(self._run_loop())

    def reject_pending_plan(self, token: str) -> None:
        if token != self.state.pending_plan_token:
            raise ValueError(f"Token {token} does not match the pending planner gate for this session")
        self._pending_action_store().remove(token)
        self.state.pending_plan_token = None
        self.state.pending_tool_calls = []
        self._persist()

    def _run_loop(self) -> Iterator[AgentEvent]:
        self.state.is_streaming = True
        self.state.error_message = None
        yield from self._emit(AgentEvent(type="agent_start", details={"session_id": self.session_id}))
        keep_running = True
        while keep_running:
            yield from self._emit(AgentEvent(type="turn_start"))
            executing_pending_plan = bool(self.state.pending_tool_calls)
            if executing_pending_plan:
                assistant_text = ""
                tool_calls = [call.model_copy(deep=True) for call in self.state.pending_tool_calls]
                self.state.pending_tool_calls = []
                self.state.pending_plan_token = None
            else:
                try:
                    assistant_text, tool_calls = self._collect_assistant_message()
                except (LLMClientError, ValueError) as exc:
                    self.state.error_message = str(exc)
                    yield from self._emit(AgentEvent(type="error", message=str(exc), is_error=True))
                    break

                assistant_parts = [TextPart(text=assistant_text)] if assistant_text else []
                assistant_parts.extend(ToolCallPart(id=call.id, name=call.name, arguments=call.arguments) for call in tool_calls)
                self.state.messages.append(ChatMessage(role="assistant", content=assistant_parts, timestamp=time.time()))

                if tool_calls and self._should_pause_for_plan(tool_calls):
                    plan_steps = self._build_plan_steps(tool_calls)
                    payload = self._stage_plan_approval(tool_calls, plan_steps)
                    self.state.pending_tool_calls = [call.model_copy(deep=True) for call in tool_calls]
                    self.state.pending_plan_token = payload["token"]
                    yield from self._emit(AgentEvent(type="planner_start", details={"count": len(plan_steps), "requires_approval": True, "token": payload["token"]}))
                    for step in plan_steps:
                        step.status = "awaiting_approval"
                        yield from self._emit(AgentEvent(type="planner_step", plan_step=step.model_copy(deep=True), details={"status": step.status, "token": payload["token"]}))
                    yield from self._emit(AgentEvent(type="planner_end", message=f"Planner paused for approval token {payload['token']}", details={"count": len(plan_steps), "requires_approval": True, "token": payload["token"]}))
                    yield from self._emit(AgentEvent(type="turn_end"))
                    keep_running = False
                    break

            if not tool_calls:
                keep_running = False
                yield from self._emit_compaction_if_needed()
                yield from self._emit(AgentEvent(type="turn_end"))
                break

            plan_steps = self._build_plan_steps(tool_calls)
            yield from self._emit(AgentEvent(type="planner_start", details={"count": len(plan_steps), "requires_approval": False}))
            for step in plan_steps:
                yield from self._emit(AgentEvent(type="planner_step", plan_step=step.model_copy(deep=True), details={"status": step.status}))
            yield from self._emit(AgentEvent(type="planner_end", details={"count": len(plan_steps), "requires_approval": False}))

            tool_failed = False
            skip_confirmation = executing_pending_plan and self._approved_pending_plan
            for index, call in enumerate(tool_calls):
                plan_steps[index].status = "in_progress"
                yield from self._emit(AgentEvent(type="planner_step", plan_step=plan_steps[index].model_copy(deep=True), details={"status": "in_progress"}))
                yield from self._emit(AgentEvent(type="tool_start", tool_name=call.name, tool_args=call.arguments))
                try:
                    spec = self.tool_registry.get_spec(call.name)
                    if spec.requires_confirmation and not skip_confirmation and not self.confirm_callback(call.name, call.arguments):
                        raise PermissionError(f"Tool '{call.name}' was rejected by user confirmation")
                    result = self.tool_registry.execute(call.name, call.arguments)
                    result.tool_call_id = call.id
                    self.state.messages.append(result.as_chat_message())
                    plan_steps[index].status = "completed"
                    yield from self._emit(AgentEvent(type="planner_step", plan_step=plan_steps[index].model_copy(deep=True), details={"status": "completed"}))
                    yield from self._emit(AgentEvent(type="tool_end", tool_name=call.name, message=result.content, details=result.details, is_error=False))
                except Exception as exc:  # noqa: BLE001
                    error_result = self.tool_registry.error_result(call, str(exc))
                    self.state.messages.append(error_result.as_chat_message())
                    plan_steps[index].status = "failed"
                    tool_failed = True
                    yield from self._emit(AgentEvent(type="planner_step", plan_step=plan_steps[index].model_copy(deep=True), details={"status": "failed"}))
                    yield from self._emit(AgentEvent(type="tool_end", tool_name=call.name, message=str(exc), details=error_result.details, is_error=True))
            self._approved_pending_plan = False
            yield from self._emit_compaction_if_needed()
            yield from self._emit(AgentEvent(type="turn_end"))
            if tool_failed:
                keep_running = False

        self.state.is_streaming = False
        self._persist()
        yield from self._emit(AgentEvent(type="agent_end", details={"session_id": self.session_id}))

    def _collect_assistant_message(self) -> tuple[str, list[ToolCall]]:
        text_chunks: list[str] = []
        partial_calls: dict[int, dict[str, str]] = {}
        for event in self.llm_client.stream_chat(self._messages_for_model(), tools=self.tool_registry.openapi_specs()):
            if event["text"]:
                text_chunks.append(event["text"])
                list(self._emit(AgentEvent(type="message_delta", delta=event["text"])))
            for index, tool in enumerate(event["tool_calls"]):
                slot = partial_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if tool.get("id"):
                    slot["id"] = tool["id"]
                if tool.get("name"):
                    slot["name"] = tool["name"]
                slot["arguments"] += tool.get("arguments_chunk", "")

        tool_calls = []
        for partial in partial_calls.values():
            try:
                arguments = json.loads(partial["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid tool arguments for {partial['name']}: {partial['arguments']}") from exc
            tool_calls.append(ToolCall(id=partial["id"] or str(uuid.uuid4()), name=partial["name"], arguments=arguments))
        return "".join(text_chunks), tool_calls

    def _build_plan_steps(self, tool_calls: list[ToolCall]) -> list[PlanStep]:
        steps: list[PlanStep] = []
        for call in tool_calls:
            title = f"Use {call.name}"
            if call.name in {"write_file", "edit_file", "run_shell"}:
                title = f"Stage or execute {call.name}"
            elif call.name.startswith("approve_"):
                title = f"Apply approved action via {call.name}"
            steps.append(PlanStep(title=title, tool_name=call.name, tool_args=call.arguments, status="pending"))
        return steps

    def _should_pause_for_plan(self, tool_calls: list[ToolCall]) -> bool:
        if not self.require_plan_approval or self.state.pending_tool_calls:
            return False
        return any(self.tool_registry.get_spec(call.name).requires_confirmation for call in tool_calls)

    def _stage_plan_approval(self, tool_calls: list[ToolCall], plan_steps: list[PlanStep]) -> dict[str, object]:
        summary = [f"{step.title} [{step.tool_name}]" for step in plan_steps]
        return self._pending_action_store().stage(
            action_type="planner_approval",
            details={
                "session_id": self.session_id,
                "tool_calls": [call.model_dump(mode="json") for call in tool_calls],
                "plan_steps": [step.model_dump(mode="json") for step in plan_steps],
                "summary": summary,
            },
        )

    def _messages_for_model(self) -> list[ChatMessage]:
        recent = self.state.messages[self.state.compaction.summarized_message_count :]
        recent = recent[-self.max_context_messages :]
        messages = [ChatMessage(role="system", content=[TextPart(text=self.state.system_prompt)], timestamp=time.time())]
        summary_message = self.compactor.summary_message(self.state.compaction)
        if summary_message is not None:
            messages.append(summary_message)
        messages.extend(recent)
        return messages

    def _emit_compaction_if_needed(self) -> Iterator[AgentEvent]:
        updated = self.compactor.compact(self.state.messages, self.state.compaction)
        if updated != self.state.compaction:
            self.state.compaction = updated
            yield from self._emit(AgentEvent(type="compaction", message="Context compacted", details={"summary_length": len(updated.summary), "summarized_message_count": updated.summarized_message_count}))

    def _emit(self, event: AgentEvent) -> Iterator[AgentEvent]:
        for callback in self._subscribers:
            callback(event)
        yield event

    def _persist(self) -> None:
        record = SessionRecord(metadata=self.session_store.load(self.session_id).metadata if self._session_exists() else self.session_store.create(self.state.system_prompt, self.state.model).metadata, messages=self.state.messages)
        record.metadata.id = self.session_id
        record.metadata.model = self.state.model.model_copy(deep=True)
        record.metadata.system_prompt = self.state.system_prompt
        record.metadata.compaction = self.state.compaction.model_copy(deep=True)
        record.metadata.pending_tool_calls = [call.model_copy(deep=True) for call in self.state.pending_tool_calls]
        record.metadata.pending_plan_token = self.state.pending_plan_token
        self.session_store.save(record)

    def _session_exists(self) -> bool:
        try:
            self.session_store.load(self.session_id)
            return True
        except FileNotFoundError:
            return False

    def _pending_action_store(self) -> PendingActionStore:
        root = self.tool_registry.workspace / ".pp-agent" / "pending-edits"
        return PendingActionStore(root)
