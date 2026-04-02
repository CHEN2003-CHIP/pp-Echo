from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Optional

from pp_agent.llm.provider.openai_compatible import LLMClient, LLMClientError
from pp_agent.runtime.compaction import ConversationCompactor
from pp_agent.runtime.emitter import LifecycleEmitter
from pp_agent.runtime.turn_loop import TurnController, TurnDecision
from pp_agent.runtime.hooks import (
    AfterToolCallDecision,
    BeforeToolCallDecision,
    RuntimeHooks,
    ToolErrorDecision,
)
from pp_agent.runtime.events import RuntimeMonitor
from pp_agent.runtime.lifecycle import (
    AGENT_END,
    AGENT_START,
    BEFORE_PROVIDER_REQUEST,
    COMPACTION,
    CONTEXT_BUILT,
    ERROR,
    MESSAGE_DELTA,
    PLANNER_END,
    PLANNER_GATE_APPROVED,
    PLANNER_GATE_PENDING,
    PLANNER_GATE_REJECTED,
    PLANNER_START,
    PLANNER_STEP,
    PROVIDER_ERROR,
    PROVIDER_RESPONSE,
    QUEUE_DEQUEUED,
    QUEUE_ENQUEUED,
    QUEUE_UPDATE,
    SESSION_BEFORE_COMPACT,
    SESSION_COMPACTED,
    SESSION_RESTORE,
    TOOL_CALL,
    TOOL_END,
    TOOL_ERROR,
    TOOL_RESULT,
    TOOL_START,
    TURN_END,
    TURN_PHASE_CHANGED,
    TURN_START,
    TURN_STATE,
)
from pp_agent.domain import PlanStep, QueuedMessage
from pp_agent.runtime.state import AgentEvent, AgentState
from pp_agent.domain import ChatMessage, TextPart, ToolCall, ToolCallPart
from pp_agent.storage.sessions import SessionRecord, SessionStore
from pp_agent.storage.timeline import TimelineStore
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.tools.registry import ToolRegistry


Subscriber = Callable[[AgentEvent], None]
ConfirmCallback = Callable[[str, dict], bool]


class AgentRuntime:
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
        initial_queued_messages: Optional[list[QueuedMessage]] = None,
        require_plan_approval: bool = True,
        runtime_hooks: Optional[RuntimeHooks] = None,
        timeline_store: Optional[TimelineStore] = None,
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.session_store = session_store
        self.session_id = session_id
        self.confirm_callback = confirm_callback or (lambda _name, _args: True)
        self.max_context_messages = max_context_messages
        self.require_plan_approval = require_plan_approval
        self.compactor = ConversationCompactor(keep_recent_messages=compact_after_messages)
        self.turn_controller = TurnController()
        self.state = AgentState(system_prompt=system_prompt, model=llm_client.model.model_copy(deep=True))
        if initial_compaction is not None:
            self.state.compaction = initial_compaction.model_copy(deep=True)
        if initial_pending_tool_calls:
            self.state.pending_tool_calls = [call.model_copy(deep=True) for call in initial_pending_tool_calls]
        self.state.pending_plan_token = initial_pending_plan_token
        if initial_queued_messages:
            self.state.queued_messages = [item.model_copy(deep=True) for item in initial_queued_messages]
        self._subscribers: list[Subscriber] = []
        self._approved_pending_plan = False
        self._queue_lock = threading.RLock()
        self.runtime_monitor = RuntimeMonitor()
        self.timeline_store = timeline_store
        self._session_record: Optional[SessionRecord] = None
        self._base_head_id: Optional[str] = None
        self._base_branch_messages: list[ChatMessage] = []
        self._pending_lifecycle_events: list[AgentEvent] = []
        self._captured_events: Optional[list[AgentEvent]] = None
        self._runtime_hooks = runtime_hooks or RuntimeHooks(
            transform_context=[self._default_transform_context],
            before_tool_call=[self._default_before_tool_call],
            after_tool_call=[self._default_after_tool_call],
            on_tool_error=[self._default_tool_error_hook],
        )
        self.lifecycle = LifecycleEmitter()
        self._wire_lifecycle()

    def subscribe(self, callback: Subscriber) -> None:
        self._subscribers.append(callback)
        self.lifecycle.subscribe(callback)

    @property
    def runtime_hooks(self) -> RuntimeHooks:
        return self._runtime_hooks

    @runtime_hooks.setter
    def runtime_hooks(self, value: RuntimeHooks) -> None:
        self._runtime_hooks = value
        self._wire_lifecycle()

    def restore_session_record(self, record: SessionRecord) -> None:
        normalized = self.session_store.load(record.id) if self._session_exists() else self.session_store._normalized_record(record)
        self._session_record = normalized.model_copy(deep=True)
        active_head = self.session_store.turn_node(normalized, normalized.active_head_id)
        self._base_head_id = active_head.parent_id if active_head is not None and active_head.status == "draft" else normalized.active_head_id
        self._base_branch_messages = self.session_store.branch_messages(normalized, self._base_head_id)
        self.state.messages = self.session_store.branch_messages(normalized, normalized.active_head_id)
        self.state.turn.turn_id = sum(1 for message in self.state.messages if message.role == "user")
        self._queue_lifecycle_event(self._event(SESSION_RESTORE, details={"active_head_id": normalized.active_head_id}))

    def prompt(self, text: str) -> list[AgentEvent]:
        user_message = ChatMessage(role="user", content=[TextPart(text=text)], timestamp=time.time())
        self.state.messages.append(user_message)
        return self._collect_runtime_events(self._run_loop())

    def continue_(self) -> list[AgentEvent]:
        next_message = self._dequeue_next_message() if not self.state.pending_tool_calls and not self.state.pending_plan_token else None
        decision = self.turn_controller.on_continue_request(self.state, next_message)
        if decision.action == "inject_message" and decision.queued_message is not None:
            return self._collect_runtime_events(self._inject_controller_message(decision, phase="continue"))
        return self._collect_runtime_events(self._run_loop())

    def enqueue_message(self, text: str, delivery: str = "follow_up") -> QueuedMessage:
        item = QueuedMessage(id=str(uuid.uuid4()), delivery=delivery, text=text, created_at=time.time())
        with self._queue_lock:
            self.state.queued_messages.append(item)
        self._persist()
        payload = {"action": "enqueued", "delivery": delivery, "queued_id": item.id, "text": text, "queue_action": "enqueued", "queue_delivery": delivery}
        list(self._emit(self._event(QUEUE_ENQUEUED, message=f"Queued {delivery} message", details=payload)))
        list(self._emit(self._event(QUEUE_UPDATE, message=f"Queued {delivery} message", details=payload)))
        return item

    def list_queued_messages(self) -> list[QueuedMessage]:
        with self._queue_lock:
            return [item.model_copy(deep=True) for item in self.state.queued_messages]

    def approve_pending_plan(self, token: str) -> list[AgentEvent]:
        if token != self.state.pending_plan_token:
            raise ValueError(f"Token {token} does not match the pending planner gate for this session")
        self._pending_action_store().remove(token)
        self._approved_pending_plan = True
        self._queue_lifecycle_event(self._event(PLANNER_GATE_APPROVED, message=f"Approved planner gate {token}", details={"token": token}))
        return self._collect_runtime_events(self._run_loop())

    def reject_pending_plan(self, token: str) -> None:
        if token != self.state.pending_plan_token:
            raise ValueError(f"Token {token} does not match the pending planner gate for this session")
        self._pending_action_store().remove(token)
        self.state.pending_plan_token = None
        self.state.pending_tool_calls = []
        list(self._emit(self._event(PLANNER_GATE_REJECTED, message=f"Rejected planner gate {token}", details={"token": token})))
        self._persist()

    def compact_now(self) -> list[AgentEvent]:
        events = self._collect_runtime_events(self._emit_compaction_if_needed())
        if events:
            self._persist()
        return events

    def _run_loop(self) -> Iterator[AgentEvent]:
        self.state.is_streaming = True
        self.state.error_message = None
        while self._pending_lifecycle_events:
            pending = self._pending_lifecycle_events.pop(0)
            yield from self._emit(pending)
        yield from self._emit(self._event(AGENT_START, details={}))
        keep_running = True
        while keep_running:
            self.state.turn.turn_id += 1
            start_decision = self.turn_controller.on_turn_start(self.state)
            yield from self._set_turn_phase(start_decision.phase, start_decision.reason)
            yield from self._emit(self._event(TURN_START, details={"turn_id": self.state.turn.turn_id}))
            executing_pending_plan = bool(self.state.pending_tool_calls)
            if executing_pending_plan and not self._approved_pending_plan:
                message = "A planner approval is still pending. Use /approve <token> before continuing."
                self.state.error_message = message
                yield from self._emit(self._event(ERROR, message=message, is_error=True))
                break
            if executing_pending_plan:
                tool_calls = [call.model_copy(deep=True) for call in self.state.pending_tool_calls]
                self.state.pending_tool_calls = []
                self.state.pending_plan_token = None
            else:
                try:
                    assistant_text, tool_calls = self._collect_assistant_message()
                except (LLMClientError, ValueError) as exc:
                    self.state.error_message = str(exc)
                    yield from self._emit(self._event(ERROR, message=str(exc), is_error=True))
                    break

                assistant_parts = [TextPart(text=assistant_text)] if assistant_text else []
                assistant_parts.extend(ToolCallPart(id=call.id, name=call.name, arguments=call.arguments) for call in tool_calls)
                self.state.messages.append(ChatMessage(role="assistant", content=assistant_parts, timestamp=time.time()))

                if tool_calls and self._should_pause_for_plan(tool_calls):
                    plan_steps = self._build_plan_steps(tool_calls)
                    payload = self._stage_plan_approval(tool_calls, plan_steps)
                    self.state.pending_tool_calls = [call.model_copy(deep=True) for call in tool_calls]
                    self.state.pending_plan_token = payload["token"]
                    pause_decision = self.turn_controller.before_plan_approval()
                    yield from self._set_turn_phase(pause_decision.phase, pause_decision.reason)
                    yield from self._emit(
                        self._event(
                            PLANNER_START,
                            details={"count": len(plan_steps), "requires_approval": True, "token": payload["token"], "turn_id": self.state.turn.turn_id},
                        )
                    )
                    for step in plan_steps:
                        step.status = "awaiting_approval"
                        yield from self._emit(
                            self._event(
                                PLANNER_STEP,
                                plan_step=step.model_copy(deep=True),
                                details={"status": step.status, "token": payload["token"]},
                            )
                        )
                    yield from self._emit(self._event(PLANNER_GATE_PENDING, message=f"Planner paused for approval token {payload['token']}", details={"token": payload["token"], "turn_id": self.state.turn.turn_id}))
                    yield from self._emit(
                        self._event(
                            PLANNER_END,
                            message=f"Planner paused for approval token {payload['token']}",
                            details={"count": len(plan_steps), "requires_approval": True, "token": payload["token"]},
                        )
                    )
                    end_decision = self.turn_controller.on_turn_end()
                    yield from self._emit(self._event(TURN_END, details={"turn_id": self.state.turn.turn_id}))
                    yield from self._set_turn_phase(end_decision.phase, end_decision.reason)
                    keep_running = False
                    break

            if not tool_calls:
                yield from self._emit_compaction_if_needed()
                yield from self._emit(self._event(TURN_END, details={"turn_id": self.state.turn.turn_id}))
                decision = self.turn_controller.after_assistant_turn(self._dequeue_next_message())
                yield from self._set_turn_phase(decision.phase, decision.reason)
                if decision.action == "inject_message" and decision.queued_message is not None:
                    yield from self._inject_controller_message(decision, phase="post_assistant")
                    keep_running = False
                    break
                keep_running = False
                break

            plan_steps = self._build_plan_steps(tool_calls)
            exec_decision = self.turn_controller.before_tool_execution()
            yield from self._set_turn_phase(exec_decision.phase, exec_decision.reason)
            yield from self._emit(self._event(PLANNER_START, details={"count": len(plan_steps), "requires_approval": False, "turn_id": self.state.turn.turn_id}))
            for step in plan_steps:
                yield from self._emit(self._event(PLANNER_STEP, plan_step=step.model_copy(deep=True), details={"status": step.status}))
            yield from self._emit(self._event(PLANNER_END, details={"count": len(plan_steps), "requires_approval": False}))

            tool_failed = False
            continue_after_error = False
            skip_confirmation = executing_pending_plan and self._approved_pending_plan
            for index, call in enumerate(tool_calls):
                plan_steps[index].status = "in_progress"
                yield from self._emit(self._event(PLANNER_STEP, plan_step=plan_steps[index].model_copy(deep=True), details={"status": "in_progress"}))
                tool_spec = self.tool_registry.get_spec(call.name)
                tool_details = {
                    "tool_name": call.name,
                    "tool_call_id": call.id,
                    "args_preview": self._args_preview(call.arguments),
                    "requires_confirmation": tool_spec.requires_confirmation,
                }
                tool_call_event = self._event(TOOL_CALL, tool_name=call.name, tool_args=call.arguments, details=tool_details)
                decision = self.lifecycle.emit_tool_call(tool_call_event, self.state, call, self.tool_registry)
                tool_call_event.details.update(decision.details)
                yield from self._emit(tool_call_event)
                yield from self._emit(self._event(TOOL_START, tool_name=call.name, tool_args=call.arguments, details=tool_details))
                try:
                    if decision.action != "allow":
                        raise PermissionError(decision.message or f"Tool '{call.name}' was rejected by runtime policy")
                    if skip_confirmation and self.tool_registry.get_spec(call.name).requires_confirmation:
                        result = self.tool_registry.execute(call.name, call.arguments)
                    else:
                        result = self.tool_registry.execute(call.name, call.arguments)
                    result.tool_call_id = call.id
                    self.state.messages.append(result.as_chat_message())
                    plan_steps[index].status = "completed"
                    result_event = self._event(TOOL_RESULT, tool_name=call.name, message=result.content, details={**tool_details, "success": True, "preview": result.content[:120]})
                    after_decision = self.lifecycle.emit_tool_result(result_event, self.state, call, result)
                    result_event.details.update(result.details)
                    result_event.details.update(after_decision.details)
                    yield from self._emit(result_event)
                    yield from self._emit(self._event(PLANNER_STEP, plan_step=plan_steps[index].model_copy(deep=True), details={"status": "completed", **after_decision.details}))
                    yield from self._emit(self._event(TOOL_END, tool_name=call.name, message=result.content, details={**result.details, **after_decision.details, **tool_details}, is_error=False))
                    keep_running = keep_running and after_decision.continue_loop
                except Exception as exc:  # noqa: BLE001
                    error_result = self.tool_registry.error_result(call, str(exc))
                    self.state.messages.append(error_result.as_chat_message())
                    plan_steps[index].status = "failed"
                    tool_failed = True
                    error_event = self._event(TOOL_ERROR, tool_name=call.name, message=str(exc), details={**tool_details, "success": False, "preview": str(exc)})
                    error_decision = self.lifecycle.emit_tool_error(error_event, self.state, call, exc)
                    error_event.details.update(error_result.details)
                    error_event.details.update(error_decision.details)
                    continue_after_error = continue_after_error or error_decision.continue_loop
                    yield from self._emit(error_event)
                    yield from self._emit(self._event(PLANNER_STEP, plan_step=plan_steps[index].model_copy(deep=True), details={"status": "failed", **error_decision.details}))
                    yield from self._emit(self._event(TOOL_END, tool_name=call.name, message=str(exc), details={**error_result.details, **error_decision.details, **tool_details}, is_error=True))
            self._approved_pending_plan = False
            yield from self._emit_compaction_if_needed()
            yield from self._emit(self._event(TURN_END, details={"turn_id": self.state.turn.turn_id}))
            decision = self.turn_controller.after_tool_round(
                tool_failed=tool_failed,
                continue_after_error=continue_after_error,
                steering_message=self._dequeue_next_message(delivery="steering") if not tool_failed else None,
            )
            yield from self._set_turn_phase(decision.phase, decision.reason)
            if decision.action == "inject_message" and decision.queued_message is not None:
                yield from self._inject_controller_message(decision, phase="post_turn")
                keep_running = False
                break
            if decision.action == "stop":
                keep_running = False

        self.state.is_streaming = False
        self._persist()
        yield from self._emit(self._event(AGENT_END, details={}))

    def _collect_assistant_message(self) -> tuple[str, list[ToolCall]]:
        messages = self._messages_for_model()
        tools = self.tool_registry.openapi_specs()
        request_event = self._event(
            BEFORE_PROVIDER_REQUEST,
            details={
                "provider": self._provider_name(),
                "model": self.llm_client.model.model,
                "message_count": len(messages),
                "tool_count": len(tools),
            },
        )
        request_decision = self.lifecycle.emit_before_provider_request(request_event, self.state, messages, tools)
        request_event.details.update(request_decision.details)
        list(self._emit(request_event))
        text_chunks: list[str] = []
        partial_calls: dict[int, dict[str, str]] = {}
        try:
            for event in self.llm_client.stream_chat(request_decision.messages or messages, tools=request_decision.tools if request_decision.tools is not None else tools):
                if event["text"]:
                    text_chunks.append(event["text"])
                    list(self._emit(self._event(MESSAGE_DELTA, delta=event["text"])))
                for index, tool in enumerate(event["tool_calls"]):
                    slot = partial_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if tool.get("id"):
                        slot["id"] = tool["id"]
                    if tool.get("name"):
                        slot["name"] = tool["name"]
                    slot["arguments"] += tool.get("arguments_chunk", "")
        except LLMClientError as exc:
            list(
                self._emit(
                    self._event(
                        PROVIDER_ERROR,
                        message=str(exc),
                        is_error=True,
                        details={"provider": self._provider_name(), "model": self.llm_client.model.model},
                    )
                )
            )
            raise

        tool_calls = []
        for partial in partial_calls.values():
            try:
                arguments = json.loads(partial["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                provider_error_event = self._event(PROVIDER_ERROR, message=str(exc), is_error=True, details={"provider": self._provider_name(), "model": self.llm_client.model.model, "raw_arguments": partial["arguments"], "tool_name": partial["name"]})
                list(self._emit(provider_error_event))
                raise ValueError(f"Invalid tool arguments for {partial['name']}: {partial['arguments']}") from exc
            tool_calls.append(ToolCall(id=partial["id"] or str(uuid.uuid4()), name=partial["name"], arguments=arguments))
        response_event = self._event(PROVIDER_RESPONSE, details={"provider": self._provider_name(), "model": self.llm_client.model.model, "message_count": len(messages), "tool_count": len(tool_calls)})
        response_decision = self.lifecycle.emit_provider_response(response_event, "".join(text_chunks), tool_calls)
        response_event.details.update(response_decision.details)
        list(self._emit(response_event))
        return response_decision.assistant_text or "".join(text_chunks), response_decision.tool_calls or tool_calls

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
        context_event = self._event(CONTEXT_BUILT, details={"message_count": len(messages), "queue_count": len(self.state.queued_messages)})
        context_decision = self.lifecycle.emit_context_built(context_event, self.state, messages)
        context_event.details.update(context_decision.details)
        list(self._emit(context_event))
        return context_decision.messages or messages

    def _emit_compaction_if_needed(self) -> Iterator[AgentEvent]:
        updated = self.compactor.compact(self.state.messages, self.state.compaction)
        if updated == self.state.compaction:
            return
        before_event = self._event(
            SESSION_BEFORE_COMPACT,
            details={
                "message_count": len(self.state.messages),
                "reason": "automatic" if self.state.is_streaming else "manual",
                "summarized_message_count": self.state.compaction.summarized_message_count,
            },
        )
        compact_decision = self.lifecycle.emit_session_before_compact(before_event)
        before_event.details.update(compact_decision.details)
        yield from self._emit(before_event)
        if not compact_decision.allow:
            return
        self.state.compaction = updated
        yield from self._emit(
            self._event(
                SESSION_COMPACTED,
                message="Context compacted",
                details={
                    "summary_length": len(updated.summary),
                    "summarized_message_count": updated.summarized_message_count,
                },
            )
        )
        yield from self._emit(
            self._event(
                COMPACTION,
                message="Context compacted",
                details={
                    "summary_length": len(updated.summary),
                    "summarized_message_count": updated.summarized_message_count,
                },
            )
        )

    def _emit(self, event: AgentEvent) -> Iterator[AgentEvent]:
        if not event.timestamp:
            event.timestamp = time.time()
        if not event.session_id:
            event.session_id = self.session_id
        if event.turn_id is None:
            event.turn_id = self.state.turn.turn_id
        if event.phase is None:
            event.phase = self.state.turn.phase
        event = self.runtime_monitor.attach_event(event, self.state)
        if self.timeline_store is not None and event.type != "message_delta":
            self.timeline_store.append(self.session_id, event)
        self.lifecycle.emit(event)
        if self._captured_events is not None:
            self._captured_events.append(event)
        yield event

    def _set_turn_phase(self, phase: str, reason: str) -> Iterator[AgentEvent]:
        self.state.turn.phase = phase
        self.state.turn.reason = reason
        yield from self._emit(
            self._event(
                TURN_PHASE_CHANGED,
                details={"reason": reason},
            )
        )
        yield from self._emit(
            self._event(
                TURN_STATE,
                details={"reason": reason},
            )
        )


    def _inject_controller_message(self, decision: TurnDecision, phase: str) -> Iterator[AgentEvent]:
        queued = decision.queued_message
        if queued is None:
            return
        self.state.messages.append(ChatMessage(role="user", content=[TextPart(text=queued.text)], timestamp=time.time()))
        yield from self._emit(
            self._event(
                QUEUE_DEQUEUED,
                message=f"Dequeued {queued.delivery} message",
                details={"action": "dequeued", "delivery": queued.delivery, "queued_id": queued.id, "text": queued.text, "controller_phase": phase, "reason": decision.reason, "queue_action": "dequeued", "queue_delivery": queued.delivery},
            )
        )
        yield from self._emit(
            self._event(
                QUEUE_UPDATE,
                message=f"Dequeued {queued.delivery} message",
                details={"action": "dequeued", "delivery": queued.delivery, "queued_id": queued.id, "text": queued.text, "controller_phase": phase, "reason": decision.reason, "queue_action": "dequeued", "queue_delivery": queued.delivery},
            )
        )
        yield from self._run_loop()

    def _persist(self) -> None:
        if self._session_record is None:
            self._session_record = self.session_store.load(self.session_id) if self._session_exists() else self.session_store.create(self.state.system_prompt, self.state.model)
            self._base_head_id = self._session_record.active_head_id
            self._base_branch_messages = self.session_store.branch_messages(self._session_record, self._base_head_id)
        record = self._session_record.model_copy(deep=True)
        record.metadata.id = self.session_id
        record.metadata.model = self.state.model.model_copy(deep=True)
        record.metadata.system_prompt = self.state.system_prompt
        record.metadata.compaction = self.state.compaction.model_copy(deep=True)
        record.metadata.pending_tool_calls = [call.model_copy(deep=True) for call in self.state.pending_tool_calls]
        record.metadata.pending_plan_token = self.state.pending_plan_token
        record.metadata.queued_messages = [item.model_copy(deep=True) for item in self.state.queued_messages]
        record = self.session_store.sync_branch_state(
            record,
            base_head_id=self._base_head_id,
            branch_messages=self.state.messages,
            pending_plan_token=self.state.pending_plan_token,
            pending_tool_calls=self.state.pending_tool_calls,
        )
        self.session_store.save(record)
        self._session_record = record.model_copy(deep=True)
        active_head = self.session_store.turn_node(record, record.active_head_id)
        self._base_head_id = active_head.parent_id if active_head is not None and active_head.status == "draft" else record.active_head_id
        self._base_branch_messages = self.session_store.branch_messages(record, self._base_head_id)

    def _session_exists(self) -> bool:
        try:
            self.session_store.load(self.session_id)
            return True
        except FileNotFoundError:
            return False

    def _pending_action_store(self) -> PendingActionStore:
        root = self.tool_registry.workspace / ".pp-agent" / "pending-edits"
        return PendingActionStore(root)

    def _dequeue_next_message(self, delivery: Optional[str] = None) -> Optional[QueuedMessage]:
        with self._queue_lock:
            if not self.state.queued_messages:
                return None
            if delivery is not None:
                index = next((idx for idx, item in enumerate(self.state.queued_messages) if item.delivery == delivery), None)
                if index is None:
                    return None
                return self.state.queued_messages.pop(index)
            steering_index = next((index for index, item in enumerate(self.state.queued_messages) if item.delivery == "steering"), None)
            index = steering_index if steering_index is not None else 0
            return self.state.queued_messages.pop(index)

    def _default_transform_context(self, state: AgentState, messages: list[ChatMessage]) -> list[ChatMessage]:
        steering_count = sum(1 for item in state.queued_messages if item.delivery == "steering")
        follow_up_count = sum(1 for item in state.queued_messages if item.delivery == "follow_up")
        notes: list[str] = []
        if state.pending_plan_token:
            notes.append("A planner approval is pending. Do not assume queued guidance has already been applied.")
        if steering_count:
            notes.append(f"Queued steering count: {steering_count}. Finish the current turn cleanly and expect higher-priority guidance next.")
        if follow_up_count:
            notes.append(f"Queued follow-up count: {follow_up_count}. Treat them as later requests after the current work is complete.")
        if not notes:
            return messages
        directive = ChatMessage(
            role="system",
            content=[TextPart(text="Runtime notes:\n" + "\n".join(f"- {note}" for note in notes))],
            timestamp=time.time(),
        )
        return [messages[0], directive, *messages[1:]] if messages else [directive]

    def _default_before_tool_call(self, _state: AgentState, call: ToolCall, registry: ToolRegistry) -> BeforeToolCallDecision:
        spec = registry.get_spec(call.name)
        if spec.requires_confirmation and not self._approved_pending_plan and not self.confirm_callback(call.name, call.arguments):
            return BeforeToolCallDecision(action="reject", message=f"Tool '{call.name}' was rejected by user confirmation")
        return BeforeToolCallDecision(action="allow")

    def _default_after_tool_call(self, _state: AgentState, _call: ToolCall, _result) -> AfterToolCallDecision:
        return AfterToolCallDecision(continue_loop=True)

    def _default_tool_error_hook(self, _state: AgentState, _call: ToolCall, _error: Exception) -> ToolErrorDecision:
        return ToolErrorDecision(continue_loop=False)

    def _event(self, event_type: str, **kwargs) -> AgentEvent:
        if "timestamp" not in kwargs:
            kwargs["timestamp"] = time.time()
        if "session_id" not in kwargs:
            kwargs["session_id"] = self.session_id
        if "turn_id" not in kwargs:
            kwargs["turn_id"] = self.state.turn.turn_id
        if "phase" not in kwargs:
            kwargs["phase"] = self.state.turn.phase
        return AgentEvent(type=event_type, **kwargs)

    def _queue_lifecycle_event(self, event: AgentEvent) -> None:
        self._pending_lifecycle_events.append(event)

    def _collect_runtime_events(self, iterator: Iterator[AgentEvent]) -> list[AgentEvent]:
        previous = self._captured_events
        self._captured_events = []
        try:
            for _ in iterator:
                pass
            return list(self._captured_events)
        finally:
            self._captured_events = previous

    @staticmethod
    def _args_preview(arguments: dict) -> dict[str, object]:
        preview: dict[str, object] = {}
        for key, value in arguments.items():
            if isinstance(value, str) and len(value) > 120:
                preview[key] = value[:117] + "..."
            else:
                preview[key] = value
        return preview

    def _wire_lifecycle(self) -> None:
        self.lifecycle = LifecycleEmitter()
        for callback in self._subscribers:
            self.lifecycle.subscribe(callback)
        self._runtime_hooks.register_with_lifecycle(self.lifecycle)

    def _provider_name(self) -> str:
        provider = getattr(self.llm_client, "provider", None)
        if provider is None:
            return "unknown"
        return getattr(provider, "name", "unknown")


AgentSession = AgentRuntime


