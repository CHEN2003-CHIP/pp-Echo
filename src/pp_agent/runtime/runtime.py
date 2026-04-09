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
    """
    【核心类】Agent运行时核心类
    功能：负责Agent的对话管理、工具调用、生命周期控制、会话持久化、事件广播
    核心职责：
        1. 管理单轮/多轮对话流程
        2. 执行LLM交互、工具调用、计划审批
        3. 会话状态持久化与恢复
        4. 运行时事件广播与钩子处理
    依赖：LLM客户端、工具注册器、会话存储、生命周期发射器
    """
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

        """
        这一段是在做 session 恢复场景：
        上次压缩过的 summary 恢复回来
        上次 pending 的 tool calls 恢复回来
        上 次 planner token 恢复回来
        上次队列消息恢复回来
        也就是说，这个 runtime 可以从“半路停住的状态”继续，而不是只能从空白对话开始。
        """
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
        self._runtime_hooks = self._compose_runtime_hooks(runtime_hooks)
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
        self._runtime_hooks = self._compose_runtime_hooks(value)
        self._wire_lifecycle()

    def _compose_runtime_hooks(self, hooks: Optional[RuntimeHooks]) -> RuntimeHooks:
        hooks = hooks or RuntimeHooks()
        return RuntimeHooks(
            transform_context=[self._default_transform_context, *hooks.transform_context_hooks],
            before_tool_call=[self._default_before_tool_call, *hooks.before_tool_call_hooks],
            after_tool_call=[self._default_after_tool_call, *hooks.after_tool_call_hooks],
            on_tool_error=[self._default_tool_error_hook, *hooks.on_tool_error_hooks],
            lifecycle_event=list(hooks.lifecycle_event_hooks),
        )

    def restore_session_record(self, record: SessionRecord, *, emit_event: bool = True) -> None:
        """SessionRecord 里保存的是整棵会话树
            active_head_id 表示“现在停在树上的哪个节点”
            branch_messages(record, 某个head) 会把从根走到这个 head 的整条分支消息取出来
            restore_session_record() 做的就是把这条“当前分支”重新装回 runtime.state.messages 里，让 runtime 继续从这里接着跑。
        """
        normalized = self.session_store.load(record.id) if self._session_exists() else self.session_store._normalized_record(record)
        self._session_record = normalized.model_copy(deep=True)
        active_head = self.session_store.turn_node(normalized, normalized.active_head_id)
        self._base_head_id = active_head.parent_id if active_head is not None and active_head.status == "draft" else normalized.active_head_id
        self._base_branch_messages = self.session_store.branch_messages(normalized, self._base_head_id)
        self.state.messages = self.session_store.branch_messages(normalized, normalized.active_head_id)
        self.state.turn.turn_id = sum(1 for message in self.state.messages if message.role == "user")
        if emit_event:
            """先把这个恢复事件放到 _pending_lifecycle_events 队列里，等下一次 _run_loop() 一开始时统一 flush 出去。"""
            self._queue_lifecycle_event(self._event(SESSION_RESTORE, details={"active_head_id": normalized.active_head_id}))

    def prompt(self, text: str) -> list[AgentEvent]:
        """
        把你的输入包装成一条 user 消息
        追加到当前会话状态 self.state.messages
        启动整个 runtime 主循环 _run_loop()
        把这轮运行过程中产生的所有 AgentEvent 收集起来返回。
        """
        user_message = ChatMessage(role="user", content=[TextPart(text=text)], timestamp=time.time())
        self.state.messages.append(user_message)
        return self._collect_runtime_events(self._run_loop())

    def continue_(self) -> list[AgentEvent]:
        """如果当前没有挂起的 tool calls,并且没有挂起的 planner approval token,那才允许从 queued_messages 里取下一条消息出来；"""
        next_message = self._dequeue_next_message() if not self.state.pending_tool_calls and not self.state.pending_plan_token else None
        """
        有挂起流程 → 继续当前流程
        没挂起流程但队列里有消息 → 先把消息注入
        什么都没有 → 正常继续跑一轮
        """
        decision = self.turn_controller.on_continue_request(self.state, next_message)
        """把之前排队的后续消息正式送进会话，然后从这条新消息开始再跑一轮。"""
        if decision.action == "inject_message" and decision.queued_message is not None:
            return self._collect_runtime_events(self._inject_controller_message(decision, phase="continue"))
        return self._collect_runtime_events(self._run_loop())

    def enqueue_message(self, text: str, delivery: str = "follow_up") -> QueuedMessage:
        """把一条消息先存进 runtime 的排队区，保存状态，并通知外界‘队列有新消息了"""
        #先构造一个排队消息对象
        item = QueuedMessage(id=str(uuid.uuid4()), delivery=delivery, text=text, created_at=time.time())
        #加锁，把它放进队列
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
        """核对审批 token → 删除待审批记录 → 打开“已批准”开关 → 记录审批通过事件 → 恢复执行之前挂起的工具计划。"""
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
        """手动触发一次上下文压缩，并把压缩产生的事件收集回来；如果真的压缩了，就保存状态"""
        events = self._collect_runtime_events(self._emit_compaction_if_needed())
        if events:
            self._persist()
        return events

    def _run_loop(self) -> Iterator[AgentEvent]:
        """开始一轮 → 看有没有待审批计划 → 没有就先问模型 → 有工具就执行工具 → 处理成功/失败 → 必要时压缩上下文 → 结束这一轮"""
        self.state.is_streaming = True
        self.state.error_message = None
        #把积压通知发完，再广播‘这轮开始了
        while self._pending_lifecycle_events:
            pending = self._pending_lifecycle_events.pop(0)
            yield from self._emit(pending)
        yield from self._emit(self._event(AGENT_START, details={}))

        keep_running = True
        while keep_running:
            #开始新 turn，标记当前阶段
            self.state.turn.turn_id += 1
            start_decision = self.turn_controller.on_turn_start(self.state)
            yield from self._set_turn_phase(start_decision.phase, start_decision.reason)
            yield from self._emit(self._event(TURN_START, details={"turn_id": self.state.turn.turn_id}))

            executing_pending_plan = bool(self.state.pending_tool_calls)
            #如果有待执行计划，但 _approved_pending_plan 还是 False就报错并停下
            if executing_pending_plan and not self._approved_pending_plan:
                message = "A planner approval is still pending. Use /approve <token> before continuing."
                self.state.error_message = message
                yield from self._emit(self._event(ERROR, message=message, is_error=True))
                break
            #如果已经批准了，就把 pending_tool_calls 拿出来赋给 tool_calls，然后清空 pending 状态
            if executing_pending_plan:
                tool_calls = [call.model_copy(deep=True) for call in self.state.pending_tool_calls]
                self.state.pending_tool_calls = []
                self.state.pending_plan_token = None
            else:
                #如果不是恢复旧计划，就去问模型
                try:
                    assistant_text, tool_calls = self._collect_assistant_message()
                except (LLMClientError, ValueError) as exc:
                    self.state.error_message = str(exc)
                    yield from self._emit(
                        self._event(ERROR, message=str(exc), is_error=True)
                    )

                    yield from self._emit(
                        self._event(
                            TURN_END,
                            details={
                                "turn_id": self.state.turn.turn_id,
                                "failed": True,
                                "failure_kind": "provider_empty_or_invalid_response",
                            },
                        )
                    )

                    yield from self._set_turn_phase("idle", "provider_error")
                    keep_running = False
                    break
                #模型这次输出的东西，无论是文字还是 tool call，都会被记进会话历史
                assistant_parts = [TextPart(text=assistant_text)] if assistant_text else []
                assistant_parts.extend(ToolCallPart(id=call.id, name=call.name, arguments=call.arguments) for call in tool_calls)
                self.state.messages.append(ChatMessage(role="assistant", content=assistant_parts, timestamp=time.time()))
                #如果模型给了工具，而且这些工具需要审批，就先暂停
                if tool_calls and self._should_pause_for_plan(tool_calls):
                    #把工具调用转成“计划步骤”
                    plan_steps = self._build_plan_steps(tool_calls)
                    #生成审批 token，并把待审批内容存起来
                    payload = self._stage_plan_approval(tool_calls, plan_steps)
                    self.state.pending_tool_calls = [call.model_copy(deep=True) for call in tool_calls]
                    self.state.pending_plan_token = payload["token"]
                    #controller决策
                    pause_decision = self.turn_controller.before_plan_approval()
                    yield from self._set_turn_phase(pause_decision.phase, pause_decision.reason)
                    planner_preview = self._planner_preview_details(tool_calls, plan_steps, token=payload["token"])
                    yield from self._emit(
                        self._event(
                            PLANNER_START,
                            details={**planner_preview, "requires_approval": True, "turn_id": self.state.turn.turn_id},
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
                    yield from self._emit(self._event(PLANNER_GATE_PENDING, message=f"Planner paused for approval token {payload['token']}", details={**planner_preview, "turn_id": self.state.turn.turn_id, "requires_approval": True}))
                    yield from self._emit(
                        self._event(
                            PLANNER_END,
                            message=f"Planner paused for approval token {payload['token']}",
                            details={**planner_preview, "requires_approval": True},
                        )
                    )
                    end_decision = self.turn_controller.on_turn_end()
                    yield from self._emit(self._event(TURN_END, details={"turn_id": self.state.turn.turn_id}))
                    yield from self._set_turn_phase(end_decision.phase, end_decision.reason)
                    keep_running = False
                    break
            #如果模型这次没有工具调用
            if not tool_calls:
                #尝试做上下文压缩
                yield from self._emit_compaction_if_needed()
                yield from self._emit(self._event(TURN_END, details={"turn_id": self.state.turn.turn_id}))
                #controller决策
                decision = self.turn_controller.after_assistant_turn(self._dequeue_next_message())
                yield from self._set_turn_phase(decision.phase, decision.reason)
                #如果有排队消息要注入，就注入
                if decision.action == "inject_message" and decision.queued_message is not None:
                    yield from self._inject_controller_message(decision, phase="post_assistant")
                    keep_running = False
                    break
                keep_running = False
                break
            #如果有工具调用，就进入工具执行阶段
            plan_steps = self._build_plan_steps(tool_calls)
            exec_decision = self.turn_controller.before_tool_execution()
            yield from self._set_turn_phase(exec_decision.phase, exec_decision.reason)
            planner_preview = self._planner_preview_details(tool_calls, plan_steps)
            yield from self._emit(self._event(PLANNER_START, details={**planner_preview, "requires_approval": False, "turn_id": self.state.turn.turn_id}))
            for step in plan_steps:
                yield from self._emit(self._event(PLANNER_STEP, plan_step=step.model_copy(deep=True), details={"status": step.status}))
            yield from self._emit(self._event(PLANNER_END, details={**planner_preview, "requires_approval": False}))

            tool_failed = False
            continue_after_error = False
            skip_confirmation = executing_pending_plan and self._approved_pending_plan
            #逐个执行工具
            for index, call in enumerate(tool_calls):
                #标记当前步骤进行中
                plan_steps[index].status = "in_progress"
                yield from self._emit(self._event(PLANNER_STEP, plan_step=plan_steps[index].model_copy(deep=True), details={"status": "in_progress"}))
                #构造一个 TOOL_CALL 事件
                tool_spec = self.tool_registry.get_spec(call.name)
                tool_details = {
                    "tool_name": call.name,
                    "tool_call_id": call.id,
                    "args_preview": self._args_preview(call.arguments),
                    "requires_confirmation": tool_spec.requires_confirmation,
                }
                tool_call_event = self._event(TOOL_CALL, tool_name=call.name, tool_args=call.arguments, details=tool_details)
                #决策是否允许运行
                decision = self.lifecycle.emit_tool_call(tool_call_event, self.state, call, self.tool_registry)
                tool_call_event.details.update(decision.details)
                tool_details.update(decision.details)
                yield from self._emit(tool_call_event)
                yield from self._emit(self._event(TOOL_START, tool_name=call.name, tool_args=call.arguments, details=tool_details))
                try:
                    if decision.action != "allow":
                        raise PermissionError(decision.message or f"Tool '{call.name}' was rejected by runtime policy")
                    if skip_confirmation and self.tool_registry.get_spec(call.name).requires_confirmation:
                        
                        result = self.tool_registry.execute(call.name, call.arguments)
                    else:

                        result = self.tool_registry.execute(call.name, call.arguments)
                    """把工具结果转成 chat message，追加到 state.messages
                        把 plan step 标成 completed
                        发 TOOL_RESULT
                        发更新后的 PLANNER_STEP
                        发 TOOL_END
                    """
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
                    """
                    用 tool_registry.error_result(...) 生成一个错误结果消息
                    也追加到 state.messages
                    把 step 标成 failed
                    发 TOOL_ERROR
                    发失败状态的 PLANNER_STEP
                    发 TOOL_END(is_error=True)
                    """
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
            #把“已批准”开关关掉，避免影响下一轮
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
        #这一整轮正式结束，保存状态，然后广播结束事件
        yield from self._emit(self._event(AGENT_END, details={}))

    def _collect_assistant_message(self) -> tuple[str, list[ToolCall]]:
        """Agent → LLM 的请求发送 + 响应解析全流程封装"""
        messages = self._messages_for_model()
        tools = self.tool_registry.openapi_specs()
        #构建模型请求事件
        request_event = self._event(
            BEFORE_PROVIDER_REQUEST,
            details={
                "provider": self._provider_name(),
                "model": self.llm_client.model.model,
                "message_count": len(messages),
                "tool_count": len(tools),
            },
        )
        #发射事件、获取生命周期决策
        request_decision = self.lifecycle.emit_before_provider_request(request_event, self.state, messages, tools)
        #更新事件细节、发射事件用于监测
        request_event.details.update(request_decision.details)
        list(self._emit(request_event))

        #收集文本
        text_chunks: list[str] = []
        #收集工具调用
        partial_calls: dict[int, dict[str, str]] = {}
        finish_reasons: list[str] = []
        streamed_event_count = 0
        try:
            ## 核心：流式调用大模型（逐块返回响应，非一次性返回）
            for event in self.llm_client.stream_chat(request_decision.messages or messages, tools=request_decision.tools if request_decision.tools is not None else tools):
                streamed_event_count += 1
                finish_reason = str(event.get("finish_reason") or "").strip()
                if finish_reason:
                    finish_reasons.append(finish_reason)
                #收集返回文本、发送 MESSAGE_DELTA 事件
                if event["text"]:
                    text_chunks.append(event["text"])
                    list(self._emit(self._event(MESSAGE_DELTA, delta=event["text"])))
                #收集工具调用信息，注意模型可能分多块返回同一个工具调用的信息，所以要按 index 聚合
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

        #解析工具调用参数，构建 ToolCall 对象列表；如果解析失败（比如 JSON 格式错误），就发 ProviderError 事件并报错
        tool_calls = []
        for partial in partial_calls.values():
            try:
                arguments = json.loads(partial["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                provider_error_event = self._event(PROVIDER_ERROR, message=str(exc), is_error=True, details={"provider": self._provider_name(), "model": self.llm_client.model.model, "raw_arguments": partial["arguments"], "tool_name": partial["name"]})
                list(self._emit(provider_error_event))
                raise ValueError(f"Invalid tool arguments for {partial['name']}: {partial['arguments']}") from exc
            tool_calls.append(ToolCall(id=partial["id"] or str(uuid.uuid4()), name=partial["name"], arguments=arguments))
        #构建模型响应事件，发出供监测使用，并让生命周期有机会修改最终的 assistant_text 和 tool_calls
        response_event = self._event(
            PROVIDER_RESPONSE,
            details={
                "provider": self._provider_name(),
                "model": self.llm_client.model.model,
                "message_count": len(messages),
                "tool_count": len(tool_calls),
                "text_length": len("".join(text_chunks)),
                "streamed_event_count": streamed_event_count,
                "finish_reasons": finish_reasons,
            },
        )
        # 发射事件，获取生命周期决策
        response_decision = self.lifecycle.emit_provider_response(response_event, "".join(text_chunks), tool_calls)
        response_event.details.update(response_decision.details)
        list(self._emit(response_event))
        #使用决策信息
        assistant_text = response_decision.assistant_text or "".join(text_chunks)
        resolved_tool_calls = response_decision.tool_calls or tool_calls
        #没有回复文本与工具调用结果时，尝试用工具结果内容做回退；如果还是没有，就发 ProviderError 事件并报错
        if not assistant_text.strip() and not resolved_tool_calls:
            fallback_text = self._tool_result_fallback(messages)
            if fallback_text:
                response_event.details["fallback"] = "tool_results"
                return fallback_text, []
            message = "Provider returned an empty response with no tool calls."
            provider_error_event = self._event(
                PROVIDER_ERROR,
                message=message,
                is_error=True,
                details={
                    "provider": self._provider_name(),
                    "model": self.llm_client.model.model,
                    "message_count": len(messages),
                    "streamed_event_count": streamed_event_count,
                    "finish_reasons": finish_reasons,
                },
            )
            list(self._emit(provider_error_event))
            raise ValueError(message)
        return assistant_text, resolved_tool_calls

    @staticmethod
    def _tool_result_fallback(messages: list[ChatMessage]) -> str:
        """仅从当前响应周期末尾连续的工具结果中提取回退文本。"""
        trailing_tool_messages: list[ChatMessage] = []
        for message in reversed(messages):
            if message.role != "tool":
                break
            trailing_tool_messages.append(message)

        if not trailing_tool_messages:
            return ""

        tool_texts: list[str] = []
        for message in reversed(trailing_tool_messages):
            parts = [part.text.strip() for part in message.content if getattr(part, "text", "").strip()]
            text = "\n".join(parts).strip()
            if text:
                tool_texts.append(text)
        if not tool_texts:
            return ""
        return "\n\n".join(tool_texts)

    def _build_plan_steps(self, tool_calls: list[ToolCall]) -> list[PlanStep]:
        """??????????????ToolCall?? ? ??? Agent ??????????????PlanStep??"""
        steps: list[PlanStep] = []
        for call in tool_calls:
            title = self._plan_step_title(call)
            steps.append(PlanStep(title=title, tool_name=call.name, tool_args=call.arguments, status="pending"))
        return steps

    def _plan_step_title(self, call: ToolCall) -> str:
        path = str(call.arguments.get("path", "")).strip()
        command = str(call.arguments.get("command", "")).strip()
        query = str(call.arguments.get("query", "")).strip()
        if call.name == "read_file" and path:
            return f"Read {path}"
        if call.name == "write_file" and path:
            return f"Write {path}"
        if call.name == "edit_file" and path:
            return f"Edit {path}"
        if call.name == "run_shell":
            return f"Run shell command: {self._compact_plan_value(command, 80)}" if command else "Run shell command"
        if call.name == "search_text":
            return f"Search text: {self._compact_plan_value(query, 60)}" if query else "Search text"
        if call.name.startswith("approve_"):
            return f"Apply approved action via {call.name}"
        return f"Use {call.name}"

    @staticmethod
    def _compact_plan_value(value: str, limit: int = 80) -> str:
        text = value.replace("\r", " ").replace("\n", " ").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _planner_preview_details(self, tool_calls: list[ToolCall], plan_steps: list[PlanStep], token: str | None = None) -> dict[str, object]:
        summary = [f"{step.title} [{step.tool_name}]" for step in plan_steps]
        files_touched: list[str] = []
        shell_commands: list[str] = []
        high_risk_tools: list[str] = []
        for call in tool_calls:
            path = str(call.arguments.get("path", "")).strip()
            command = str(call.arguments.get("command", "")).strip()
            if path:
                files_touched.append(path)
            if command:
                shell_commands.append(self._compact_plan_value(command, 120))
            spec = self.tool_registry.get_spec(call.name)
            if spec.requires_confirmation and call.name not in high_risk_tools:
                high_risk_tools.append(call.name)
        preview = {
            "count": len(plan_steps),
            "summary": summary,
            "plan_steps": [step.model_dump(mode="json") for step in plan_steps],
            "step_count": len(plan_steps),
            "tools": [call.name for call in tool_calls],
            "files_touched_guess": files_touched,
            "shell_commands_guess": shell_commands,
            "high_risk_tools": high_risk_tools,
        }
        if token is not None:
            preview["token"] = token
        return preview

    def _should_pause_for_plan(self, tool_calls: list[ToolCall]) -> bool:
       
        if not self.require_plan_approval or self.state.pending_tool_calls:
           
            return False
        return any(self.tool_registry.get_spec(call.name).requires_confirmation for call in tool_calls)

    def _stage_plan_approval(self, tool_calls: list[ToolCall], plan_steps: list[PlanStep]) -> dict[str, object]:
        
        preview = self._planner_preview_details(tool_calls, plan_steps)
        return self._pending_action_store().stage(
            action_type="planner_approval",
            details={
                "session_id": self.session_id,
                "tool_calls": [call.model_dump(mode="json") for call in tool_calls],
                **preview,
            },
        )

    def _messages_for_model(self) -> list[ChatMessage]:
        """为大模型（LLM）组装最终的对话上下文消息列表"""
        # 1. 跳过已被压缩总结的消息，只取【未压缩的最新消息】
        recent = self.state.messages[self.state.compaction.summarized_message_count :]
        # 2. 限制最大消息数量，防止超出模型上下文窗口（只保留最近N条）
        recent = recent[-self.max_context_messages :]
        # 3. 创建【系统消息】
        messages = [ChatMessage(role="system", content=[TextPart(text=self.state.system_prompt)], timestamp=time.time())]
        # 4. 获取上下文压缩器生成的【历史对话摘要】
        summary_message = self.compactor.summary_message(self.state.compaction)
        # 5. 如果有摘要（长对话场景），就把摘要加入消息列表
        if summary_message is not None:
            messages.append(summary_message)
        # 6. 把【最近未压缩消息】追加到列表末尾
        messages.extend(recent)
        # 7. 创建 CONTEXT_BUILT 事件（上下文构建完成）
        context_event = self._event(CONTEXT_BUILT, details={"message_count": len(messages), "queue_count": len(self.state.queued_messages)})
        # 8. 发射事件，获取外部决策（允许拦截/修改消息）
        context_decision = self.lifecycle.emit_context_built(context_event, self.state, messages)
        # 9. 更新事件细节、发射事件用于监测
        context_event.details.update(context_decision.details)
        list(self._emit(context_event))
        return context_decision.messages or messages

    def _emit_compaction_if_needed(self) -> Iterator[AgentEvent]:
        """自动触发对话历史压缩，解决大模型上下文窗口超限"""

        # 1. 调用压缩器，尝试压缩消息历史，返回【更新后的压缩状态】
        updated = self.compactor.compact(self.state.messages, self.state.compaction)
        # 2. 如果压缩状态【没有任何变化】= 无需压缩，直接终止函数
        if updated == self.state.compaction:
            return
        # 3. 创建【会话压缩前】事件（SESSION_BEFORE_COMPACT）
        before_event = self._event(
            SESSION_BEFORE_COMPACT,
            details={
                "message_count": len(self.state.messages),
                "reason": "automatic" if self.state.is_streaming else "manual",
                "summarized_message_count": self.state.compaction.summarized_message_count,
            },
        )
        # 4. 发射事件，获取外部决策（是否允许压缩）
        compact_decision = self.lifecycle.emit_session_before_compact(before_event)
        # 5. 更新事件详情，并抛出事件
        before_event.details.update(compact_decision.details)
        yield from self._emit(before_event)
        # 6. 如果决策【不允许压缩】，直接终止流程
        if not compact_decision.allow:
            return
        # 7. 【更新状态】：将Agent的压缩状态替换为新的压缩结果
        self.state.compaction = updated
        # 8. 抛出【会话已压缩】事件（SESSION_COMPACTED）
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
        # 9. 抛出【上下文压缩中】事件（COMPACTION）
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
        """标准化补全事件信息 → 持久化存储 → 分发通知 → 内部捕获"""
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
        """安全、规范地修改回合的执行阶段 + 自动触发阶段变更事件"""
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
        """控制器说要注入消息 → 这个函数负责真的把消息加进去，让 Agent 能处理它"""
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
        """将内存中的所有实时状态永久保存到存储层"""
        ## 1. 如果本地没有缓存会话记录 → 加载或新建
        if self._session_record is None:
            self._session_record = self.session_store.load(self.session_id) if self._session_exists() else self.session_store.create(self.state.system_prompt, self.state.model)
            self._base_head_id = self._session_record.active_head_id
            self._base_branch_messages = self.session_store.branch_messages(self._session_record, self._base_head_id)
        # 2. 深拷贝会话记录（避免修改原始对象）
        record = self._session_record.model_copy(deep=True)
        # 3. 填充【内存中最新的状态】到存储记录
        record.metadata.id = self.session_id
        record.metadata.model = self.state.model.model_copy(deep=True)
        record.metadata.system_prompt = self.state.system_prompt
        record.metadata.compaction = self.state.compaction.model_copy(deep=True)
        record.metadata.pending_tool_calls = [call.model_copy(deep=True) for call in self.state.pending_tool_calls]
        record.metadata.pending_plan_token = self.state.pending_plan_token
        record.metadata.queued_messages = [item.model_copy(deep=True) for item in self.state.queued_messages]
        try:
            # 4. 核心：同步内存消息到存储的会话分支
            record = self.session_store.sync_branch_state(
                record,
                base_head_id=self._base_head_id,
                branch_messages=self.state.messages,
                pending_plan_token=self.state.pending_plan_token,
                pending_tool_calls=self.state.pending_tool_calls,
            )
        except ValueError:
            # 5. 同步失败（会话冲突/数据损坏）→ 执行恢复逻辑
            # 重新加载最新的会话记录
            latest = self.session_store.load(self.session_id) if self._session_exists() else record.model_copy(deep=True)
            # 自动寻找最佳的基础分支头（修复版本冲突）
            recovered_base_head_id = self.session_store.best_base_head_id(latest, self.state.messages)
            # 重建恢复用的会话记录
            recovery_record = latest.model_copy(deep=True)
            recovery_record.metadata.id = self.session_id
            recovery_record.metadata.model = self.state.model.model_copy(deep=True)
            recovery_record.metadata.system_prompt = self.state.system_prompt
            recovery_record.metadata.compaction = self.state.compaction.model_copy(deep=True)
            recovery_record.metadata.pending_tool_calls = [call.model_copy(deep=True) for call in self.state.pending_tool_calls]
            recovery_record.metadata.pending_plan_token = self.state.pending_plan_token
            recovery_record.metadata.queued_messages = [item.model_copy(deep=True) for item in self.state.queued_messages]
            if recovered_base_head_id is None:
                recovery_record.messages = []
                recovery_record.metadata.turn_nodes = []
                recovery_record.metadata.active_head_id = None
            # 用恢复后的记录重新同步
            record = self.session_store.sync_branch_state(
                recovery_record,
                base_head_id=recovered_base_head_id,
                branch_messages=self.state.messages,
                pending_plan_token=self.state.pending_plan_token,
                pending_tool_calls=self.state.pending_tool_calls,
            )
        # 6. 将最终记录保存到存储
        self.session_store.save(record)
        # 7. 更新本地缓存的会话记录
        self._session_record = record.model_copy(deep=True)
        # 8. 获取当前活跃的会话节点
        active_head = self.session_store.turn_node(record, record.active_head_id)
        # 9. 如果是草稿节点，用父节点作为基础头；否则用当前头
        self._base_head_id = active_head.parent_id if active_head is not None and active_head.status == "draft" else record.active_head_id
        # 10. 更新基础分支消息
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
        """带线程锁、支持优先级调度的消息队列出队方法，优先取出引导消息，保证 Agent 按正确顺序处理排队消息"""
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
        # 1. 有待审批计划 → 提醒AI：别默认队列引导已生效
        if state.pending_plan_token:
            notes.append("A planner approval is pending. Do not assume queued guidance has already been applied.")
        # 2. 有引导消息 → 提醒AI：先完成当前回合，后面有高优先级指令
        if steering_count:
            notes.append(f"Queued steering count: {steering_count}. Finish the current turn cleanly and expect higher-priority guidance next.")
        # 3. 有跟进消息 → 提醒AI：这是后续请求，先做完当前工作
        if follow_up_count:
            notes.append(f"Queued follow-up count: {follow_up_count}. Treat them as later requests after the current work is complete.")
        notes.append(f"Active session id: {self.session_id}. Use this exact id for session-scoped tools; safe rewind also accepts 'current'.")
        if not notes:
            return messages
        directive = ChatMessage(
            role="system",
            content=[TextPart(text="Runtime notes:\n" + "\n".join(f"- {note}" for note in notes))],
            timestamp=time.time(),
        )
        return [messages[0], directive, *messages[1:]] if messages else [directive]

    def _default_before_tool_call(self, _state: AgentState, call: ToolCall, registry: ToolRegistry) -> BeforeToolCallDecision:
        """Agent 工具执行前的「最终安全校验钩子」"""
        spec = registry.get_spec(call.name)
        decision = registry.evaluate_call(call.name, call.arguments)
        if decision.action == "deny":
            return BeforeToolCallDecision(
                action="reject",
                message=decision.reason,
                details={"policy_action": decision.action, "permission_domain": decision.permission_domain, "policy_reason": decision.reason, **(decision.details or {})},
            )
        if decision.action == "ask" and not self._approved_pending_plan:
            return BeforeToolCallDecision(
                action="reject",
                message=decision.reason,
                details={"policy_action": decision.action, "permission_domain": decision.permission_domain, "policy_reason": decision.reason, **(decision.details or {})},
            )
        if spec.requires_confirmation and not self._approved_pending_plan and not self.confirm_callback(call.name, call.arguments):
            return BeforeToolCallDecision(action="reject", message=f"Tool '{call.name}' was rejected by user confirmation")
        return BeforeToolCallDecision(
            action="allow",
            details={"policy_action": decision.action, "permission_domain": decision.permission_domain, "policy_reason": decision.reason, **(decision.details or {})},
        )

    def _default_after_tool_call(self, _state: AgentState, _call: ToolCall, _result) -> AfterToolCallDecision:
        """Agent 工具执行后的「默认后续决策钩子」，默认继续执行后续工具调用（如果有）"""
        return AfterToolCallDecision(continue_loop=True)

    def _default_tool_error_hook(self, _state: AgentState, _call: ToolCall, _error: Exception) -> ToolErrorDecision:
        """Agent 工具执行出错时的「默认错误处理钩子」，默认不继续执行后续工具调用（如果有），直接进入回合结束流程"""
        return ToolErrorDecision(continue_loop=False)

    def _event(self, event_type: str, **kwargs) -> AgentEvent:
        """构造一个 AgentEvent 对象，自动补全常规字段"""
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
        """在生命周期事件处理中，如果需要发出新的事件但又不想立刻发出，
        可以调用这个方法把事件放到待发列表里，等当前事件处理完后再统一发出"""
        self._pending_lifecycle_events.append(event)

    def _collect_runtime_events(self, iterator: Iterator[AgentEvent]) -> list[AgentEvent]:
        """「备份 - 恢复」机制的安全事件捕获器"""
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
