from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pp_agent.llm.provider.openai_compatible import LLMClient, LLMClientError
from pp_agent.llm.usage import LLMUsageStats, estimate_cost_usd, normalize_usage
from pp_agent.memory.auto_index import AutoIndexScheduler, NoopAutoIndexScheduler
from pp_agent.memory.provider import MemoryProvider, NoopMemoryProvider
from pp_agent.observability.hooks import ObservabilityHooks
from pp_agent.observability.noop import NoopObservabilityHooks
from pp_agent.observability.redaction import safe_preview, sanitize_tool_args
from pp_agent.runtime.cancellation import CancellationToken, OperationCancelled
from pp_agent.runtime.compaction import ConversationCompactor
from pp_agent.runtime.emitter import LifecycleEmitter
from pp_agent.runtime.turn_loop import TurnController, TurnDecision
from pp_agent.runtime.hooks import (
    AfterToolCallDecision,
    BeforeToolCallDecision,
    ContextHookEntry,
    RuntimeHooks,
    ToolErrorDecision,
)
from pp_agent.runtime.events import RuntimeMonitor
from pp_agent.runtime.lifecycle import (
    AGENT_END,
    AGENT_START,
    BEFORE_PROVIDER_REQUEST,
    CHECKPOINT_BEFORE_CREATE,
    CHECKPOINT_BEFORE_RESTORE,
    CHECKPOINT_CREATED,
    CHECKPOINT_RESTORE_FAILED,
    CHECKPOINT_RESTORE_PREVIEW,
    CHECKPOINT_RESTORED,
    COMPACTION,
    CONTEXT_BUILT,
    ERROR,
    LEARNING_CANDIDATES_CREATED,
    LEARNING_EXTRACTION_FAILED,
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
    REASONING_DELTA,
    REASONING_END,
    REASONING_START,
    REASONING_SUMMARY,
    SESSION_BEFORE_COMPACT,
    SESSION_COMPACTED,
    SESSION_RESTORE,
    SESSION_SAFE_REWIND_COMPLETED,
    SESSION_SAFE_REWIND_STARTED,
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
from pp_agent.subagents.contract import explicit_orchestrated_edit_request
from pp_agent.storage.timeline import TimelineStore
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.tools.effects import is_protected_path
from pp_agent.tools.base import ToolExecutionResult
from pp_agent.tools.registry import ToolRegistry


Subscriber = Callable[[AgentEvent], None]
ConfirmCallback = Callable[[str, dict], bool]
ConfigRefreshCallback = Callable[["AgentRuntime", object], None]
logger = logging.getLogger(__name__)
TEXT_TOOL_NAME_RE = re.compile(r"([A-Za-z0-9_.-]+)\s*$")
TEXT_TOOL_CALL_FALLBACK_ALLOWLIST = {"list_files", "search_text", "grep_code", "git_status"}
TEXT_TOOL_CALL_FALLBACK_DENYLIST = {"spawn_subagent", "read_file", "write_file", "edit_file", "run_shell"}
WEB_TOOL_NAMES = {"web.search", "web.news", "web.github_trending", "web.fetch"}
WEB_LOOKUP_ATTEMPT_LIMIT = 2


@dataclass(frozen=True)
class _TurnPersistContext:
    new_message_start_index: int
    turn_id: str
    turn_started_at: float


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
        memory_provider: Optional[MemoryProvider] = None,
        auto_index_scheduler: Optional[AutoIndexScheduler] = None,
        learning_runtime: Optional[object] = None,
        enforce_orchestrated_edit_contract: bool = True,
        require_patch_artifact_for_code_change: bool = True,
        config_manager: Optional[object] = None,
        config_snapshot: Optional[object] = None,
        config_refresh_callback: Optional[ConfigRefreshCallback] = None,
        observability: Optional[ObservabilityHooks] = None,
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
        self._cancellation_token = CancellationToken()
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
        self.memory_provider = memory_provider or NoopMemoryProvider()
        self.auto_index_scheduler = auto_index_scheduler or NoopAutoIndexScheduler()
        self.learning_runtime = learning_runtime
        self.enforce_orchestrated_edit_contract = bool(enforce_orchestrated_edit_contract)
        self.require_patch_artifact_for_code_change = bool(require_patch_artifact_for_code_change)
        self.config_manager = config_manager
        self.config_snapshot = config_snapshot
        self.config_version = getattr(config_snapshot, "config_version", None)
        self.pending_config_effects: list[str] = []
        self._config_refresh_callback = config_refresh_callback
        self.observability = observability or NoopObservabilityHooks()
        self._trace_event_starts: dict[str, AgentEvent] = {}
        self._event_sequence = 0
        self._run_sequence = 0
        self._current_run_id: str | None = None
        self._activity_starts: dict[str, float] = {}
        self.lifecycle.subscribe(self._observe_runtime_event)
        self._attach_runtime_context_to_tool_registry()

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
            transform_context=[
                ContextHookEntry(
                    name="agent_runtime_default",
                    kind="runtime",
                    fn=self._default_transform_context,
                    enabled_for_subagent=True,
                ),
                *hooks.transform_context_hooks,
            ],
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
        self._cancellation_token.clear()
        self._begin_run("prompt")
        user_message = ChatMessage(role="user", content=[TextPart(text=text)], timestamp=time.time())
        self.state.messages.append(user_message)
        context = _TurnPersistContext(
            new_message_start_index=len(self.state.messages) - 1,
            turn_id=f"turn-{self.state.turn.turn_id + 1}",
            turn_started_at=user_message.timestamp,
        )
        self.observability.start_run(
            session_id=self.session_id,
            turn_id=context.turn_id,
            user_goal_preview=safe_preview(text, 1000),
            provider=self._provider_name(),
            model=self.llm_client.model.model,
            attributes={"entrypoint": "prompt"},
        )
        try:
            events = self._collect_runtime_events(self._run_loop(turn_persist_context=context))
        except Exception as exc:
            self.observability.end_run(status="error", error=exc)
            raise
        self.observability.end_run(status=self._trace_status_from_events(events))
        return events

    def continue_(self) -> list[AgentEvent]:
        """如果当前没有挂起的 tool calls,并且没有挂起的 planner approval token,那才允许从 queued_messages 里取下一条消息出来；"""
        self._cancellation_token.clear()
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
        self._begin_run("continue")
        context = _TurnPersistContext(
            new_message_start_index=len(self.state.messages),
            turn_id=f"turn-{self.state.turn.turn_id + 1}",
            turn_started_at=time.time(),
        )
        self.observability.start_run(
            session_id=self.session_id,
            turn_id=context.turn_id,
            user_goal_preview=safe_preview(next_message.text if next_message is not None else "continue", 1000),
            provider=self._provider_name(),
            model=self.llm_client.model.model,
            attributes={"entrypoint": "continue", "decision": decision.action},
        )
        try:
            events = self._collect_runtime_events(self._run_loop(turn_persist_context=context))
        except Exception as exc:
            self.observability.end_run(status="error", error=exc)
            raise
        self.observability.end_run(status=self._trace_status_from_events(events))
        return events

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
        self._cancellation_token.clear()
        self._begin_run("approval")
        if token != self.state.pending_plan_token:
            raise ValueError(f"Token {token} does not match the pending planner gate for this session")
        self._pending_action_store().remove(token)
        self._approved_pending_plan = True
        self._queue_lifecycle_event(self._event(PLANNER_GATE_APPROVED, message=f"Approved planner gate {token}", details={"token": token}))
        context = _TurnPersistContext(
            new_message_start_index=len(self.state.messages),
            turn_id=f"turn-{self.state.turn.turn_id + 1}",
            turn_started_at=time.time(),
        )
        return self._collect_runtime_events(self._run_loop(turn_persist_context=context))

    def reject_pending_plan(self, token: str) -> None:
        if token != self.state.pending_plan_token:
            raise ValueError(f"Token {token} does not match the pending planner gate for this session")
        self._pending_action_store().remove(token)
        self.state.pending_plan_token = None
        self.state.pending_tool_calls = []
        list(self._emit(self._event(PLANNER_GATE_REJECTED, message=f"Rejected planner gate {token}", details={"token": token})))
        self._persist()

    def record_external_approval_result(self, result: dict[str, object]) -> ChatMessage:
        session_id = str(result.get("session_id") or "").strip()
        if session_id and session_id != self.session_id:
            raise ValueError(f"External approval result belongs to session {session_id}, not {self.session_id}")
        token = str(result.get("token") or "").strip()
        action_type = str(result.get("action_type") or "").strip()
        source_tool_name = str(result.get("source_tool_name") or action_type or "approve_pending_action").strip()
        tool_call_id = str(result.get("tool_call_id") or token or "").strip()
        details = dict(result.get("details") or {})
        lifecycle = dict(result.get("lifecycle") or details.get("lifecycle") or {})
        success = bool(result.get("success", True))
        approval_action = str(result.get("approval_action") or "").strip()
        approved = bool(result.get("approved", approval_action == "approve" and success))
        rejected = bool(result.get("rejected", approval_action == "reject" or action_type == "reject_pending_action"))
        payload = {
            **details,
            "token": token,
            "action_type": action_type,
            "source_tool_name": source_tool_name,
            "tool_call_id": tool_call_id,
            "success": success,
            "result": result.get("result"),
            "result_details": details,
            "lifecycle": lifecycle,
            "external_approval_result": True,
            "approval_action": approval_action or None,
            "approval_status": "rejected" if rejected else ("approved" if approved else "failed"),
            "approved": approved,
            "rejected": rejected,
            "timestamp": result.get("timestamp") or time.time(),
        }
        message = ChatMessage(
            role="tool",
            tool_call_id=tool_call_id or None,
            tool_name=source_tool_name,
            content=[TextPart(text=str(result.get("result") or ""))],
            metadata={"tool_details": payload, "is_error": not success},
            timestamp=float(payload["timestamp"]),
        )
        self.state.messages.append(message)
        self._persist()
        return message

    def request_cancel(self, reason: str = "cancel_requested") -> None:
        self._cancellation_token.cancel(reason)

    def cancellation_requested(self) -> bool:
        return self._cancellation_token.cancelled

    def set_cancellation_token(self, token: CancellationToken) -> None:
        self._cancellation_token = token
        self._attach_runtime_context_to_tool_registry()

    def compact_now(self) -> list[AgentEvent]:
        """手动触发一次上下文压缩，并把压缩产生的事件收集回来；如果真的压缩了，就保存状态"""
        events = self._collect_runtime_events(self._emit_compaction_if_needed())
        if events:
            self._persist()
        return events

    def _run_loop(self, *, turn_persist_context: _TurnPersistContext) -> Iterator[AgentEvent]:
        """开始一轮 → 看有没有待审批计划 → 没有就先问模型 → 有工具就执行工具 → 处理成功/失败 → 必要时压缩上下文 → 结束这一轮"""
        yield from self._refresh_config_for_turn()
        self.state.is_streaming = True
        self.state.error_message = None
        #把积压通知发完，再广播‘这轮开始了
        while self._pending_lifecycle_events:
            pending = self._pending_lifecycle_events.pop(0)
            yield from self._emit(pending)
        yield from self._emit(self._event(AGENT_START, details={}))

        keep_running = True
        verification_gate_nudged = False
        persist_end_index = turn_persist_context.new_message_start_index
        while keep_running:
            if self._cancellation_token.cancelled:
                yield from self._emit_cancelled_turn(self._cancellation_token.reason)
                keep_running = False
                break
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
                except OperationCancelled as exc:
                    yield from self._emit_cancelled_turn(str(exc))
                    keep_running = False
                    break
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
                    persist_end_index = len(self.state.messages)
                    keep_running = False
                    break
            #如果模型这次没有工具调用
            if not tool_calls:
                #尝试做上下文压缩
                yield from self._emit_compaction_if_needed()
                yield from self._emit(self._event(TURN_END, details={"turn_id": self.state.turn.turn_id}))
                verification_note = self._verification_gate_required_note(self.state)
                if verification_note and not verification_gate_nudged and not self._assistant_declares_verification_blocker(assistant_text):
                    self._append_runtime_system_note(
                        verification_note,
                        kind="verification_required",
                        details={"verification_gate": self._verification_gate_state(self.state)},
                    )
                    verification_gate_nudged = True
                    persist_end_index = len(self.state.messages)
                    keep_running = True
                    continue
                #controller决策
                decision = self.turn_controller.after_assistant_turn(self._dequeue_next_message())
                yield from self._set_turn_phase(decision.phase, decision.reason)
                #如果有排队消息要注入，就注入
                if decision.action == "inject_message" and decision.queued_message is not None:
                    persist_end_index = len(self.state.messages)
                    yield from self._inject_controller_message(decision, phase="post_assistant")
                    keep_running = False
                    break
                persist_end_index = len(self.state.messages)
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
            turn_failure_kind: str | None = None
            continue_after_error = False
            skip_confirmation = executing_pending_plan and self._approved_pending_plan
            #逐个执行工具
            for index, call in enumerate(tool_calls):
                if self._cancellation_token.cancelled:
                    tool_failed = True
                    turn_failure_kind = "canceled"
                    keep_running = False
                    break
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
                    self._cancellation_token.raise_if_cancelled()
                    if decision.action != "allow":
                        raise PermissionError(decision.message or f"Tool '{call.name}' was rejected by runtime policy")
                    if skip_confirmation and self.tool_registry.get_spec(call.name).requires_confirmation:
                        
                        result = self.tool_registry.execute(call.name, call.arguments, tool_call_id=call.id)
                    else:

                        result = self.tool_registry.execute(call.name, call.arguments, tool_call_id=call.id)
                    self._cancellation_token.raise_if_cancelled()
                    """把工具结果转成 chat message，追加到 state.messages
                        把 plan step 标成 completed
                        发 TOOL_RESULT
                        发更新后的 PLANNER_STEP
                        发 TOOL_END
                    """
                    result.tool_call_id = call.id
                    self._attach_session_to_pending_action(result)
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
                except OperationCancelled as exc:
                    friendly_message = str(exc) or "cancel_requested"
                    error_result = self.tool_registry.error_result(call, friendly_message)
                    self.state.messages.append(error_result.as_chat_message())
                    plan_steps[index].status = "failed"
                    tool_failed = True
                    turn_failure_kind = "canceled"
                    error_event = self._event(TOOL_ERROR, tool_name=call.name, message=friendly_message, details={**tool_details, "success": False, "preview": friendly_message, "failure_kind": "canceled"})
                    error_event.details.update(error_result.details)
                    yield from self._emit(error_event)
                    yield from self._emit(self._event(PLANNER_STEP, plan_step=plan_steps[index].model_copy(deep=True), details={"status": "failed", "failure_kind": "canceled"}))
                    yield from self._emit(self._event(TOOL_END, tool_name=call.name, message=friendly_message, details={**error_result.details, **tool_details, "failure_kind": "canceled"}, is_error=True))
                    keep_running = False
                    break
                except Exception as exc:  # noqa: BLE001
                    """
                    用 tool_registry.error_result(...) 生成一个错误结果消息
                    也追加到 state.messages
                    把 step 标成 failed
                    发 TOOL_ERROR
                    发失败状态的 PLANNER_STEP
                    发 TOOL_END(is_error=True)
                    """
                    friendly_message = self._friendly_tool_exception_message(call, exc)
                    error_result = self.tool_registry.error_result(call, friendly_message)
                    self.state.messages.append(error_result.as_chat_message())
                    plan_steps[index].status = "failed"
                    tool_failed = True
                    error_event = self._event(TOOL_ERROR, tool_name=call.name, message=friendly_message, details={**tool_details, "success": False, "preview": friendly_message})
                    error_decision = self.lifecycle.emit_tool_error(error_event, self.state, call, exc)
                    error_event.details.update(error_result.details)
                    error_event.details.update(error_decision.details)
                    continue_after_error = continue_after_error or error_decision.continue_loop
                    yield from self._emit(error_event)
                    yield from self._emit(self._event(PLANNER_STEP, plan_step=plan_steps[index].model_copy(deep=True), details={"status": "failed", **error_decision.details}))
                    yield from self._emit(self._event(TOOL_END, tool_name=call.name, message=friendly_message, details={**error_result.details, **error_decision.details, **tool_details}, is_error=True))
            #把“已批准”开关关掉，避免影响下一轮
            self._approved_pending_plan = False
            yield from self._emit_compaction_if_needed()
            turn_end_details = {"turn_id": self.state.turn.turn_id}
            if turn_failure_kind:
                turn_end_details.update({"failed": True, "failure_kind": turn_failure_kind})
            yield from self._emit(self._event(TURN_END, details=turn_end_details))
            decision = self.turn_controller.after_tool_round(
                tool_failed=tool_failed,
                continue_after_error=continue_after_error,
                steering_message=self._dequeue_next_message(delivery="steering") if not tool_failed else None,
            )
            yield from self._set_turn_phase(decision.phase, decision.reason)
            if decision.action == "inject_message" and decision.queued_message is not None:
                persist_end_index = len(self.state.messages)
                yield from self._inject_controller_message(decision, phase="post_turn")
                keep_running = False
                break
            if decision.action == "stop":
                persist_end_index = len(self.state.messages)
                keep_running = False

        self.state.is_streaming = False
        cancel_was_requested = self._cancellation_token.cancelled
        turn_finished_at = time.time()
        new_messages = [
            message.model_copy(deep=True)
            for message in self.state.messages[turn_persist_context.new_message_start_index:persist_end_index]
        ]
        self._persist(
            dual_write_turn_id=turn_persist_context.turn_id,
            new_messages=new_messages,
            memory_metadata={
                "source": "runtime_dual_write",
                "workspace": str(self.tool_registry.workspace),
                "session_head_id": self._session_record.active_head_id if self._session_record is not None else None,
                "turn_started_at": turn_persist_context.turn_started_at,
                "turn_finished_at": turn_finished_at,
            },
        )
        #这一整轮正式结束，保存状态，然后广播结束事件
        yield from self._emit(self._event(AGENT_END, details={}))
        if cancel_was_requested:
            self._cancellation_token.clear()

    def _collect_assistant_message(self) -> tuple[str, list[ToolCall]]:
        """Agent → LLM 的请求发送 + 响应解析全流程封装"""
        self._ensure_provider_context_budget()
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
        list(
            self._emit(
                self._event(
                    REASONING_START,
                    message="Preparing model context and public progress.",
                    details={
                        "summary": "Preparing context and tool declarations.",
                        "message_count": len(request_decision.messages or messages),
                        "tool_count": len(request_decision.tools if request_decision.tools is not None else tools),
                    },
                )
            )
        )
        list(self._emit(request_event))

        #收集文本
        text_chunks: list[str] = []
        #收集工具调用
        partial_calls: dict[int, dict[str, str]] = {}
        finish_reasons: list[str] = []
        streamed_event_count = 0
        raw_usage: object | None = None
        request_id: str | None = None
        emitted_reasoning_delta = False
        started = time.perf_counter()
        try:
            ## 核心：流式调用大模型（逐块返回响应，非一次性返回）
            for event in self.llm_client.stream_chat(request_decision.messages or messages, tools=request_decision.tools if request_decision.tools is not None else tools):
                self._cancellation_token.raise_if_cancelled()
                streamed_event_count += 1
                if event.get("usage") is not None:
                    raw_usage = event.get("usage")
                if event.get("request_id"):
                    request_id = str(event.get("request_id"))
                finish_reason = str(event.get("finish_reason") or "").strip()
                if finish_reason:
                    finish_reasons.append(finish_reason)
                #收集返回文本、发送 MESSAGE_DELTA 事件
                if event["text"]:
                    text_chunks.append(event["text"])
                    if not emitted_reasoning_delta:
                        emitted_reasoning_delta = True
                        list(
                            self._emit(
                                self._event(
                                    REASONING_DELTA,
                                    message="Receiving public assistant output.",
                                    delta="Receiving public assistant output.",
                                    details={"summary": "The model has started returning visible output."},
                                )
                            )
                        )
                    list(self._emit(self._event(MESSAGE_DELTA, delta=event["text"])))
                #收集工具调用信息，注意模型可能分多块返回同一个工具调用的信息，所以要按 index 聚合
                for index, tool in enumerate(event["tool_calls"]):
                    stable_index = tool.get("index")
                    key = stable_index if stable_index is not None else tool.get("id") or index
                    slot = partial_calls.setdefault(key, {"id": "", "name": "", "arguments": ""})
                    if tool.get("id"):
                        slot["id"] = tool["id"]
                    if tool.get("name"):
                        slot["name"] = tool["name"]
                    slot["arguments"] += tool.get("arguments_chunk", "")
        except LLMClientError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            list(
                self._emit(
                    self._event(
                        PROVIDER_ERROR,
                        message=str(exc),
                        is_error=True,
                        details={
                            "provider": self._provider_name(),
                            "model": self.llm_client.model.model,
                            "latency_ms": latency_ms,
                            "retry_count": 0,
                            "attempt_index": 1,
                        },
                    )
                )
            )
            raise
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = normalize_usage(raw_usage)
        usage = LLMUsageStats(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            cost_usd=estimate_cost_usd(self.llm_client.model.model, usage),
            latency_ms=latency_ms,
            provider_latency_ms=usage.provider_latency_ms,
            retry_count=usage.retry_count,
            attempt_index=usage.attempt_index,
            request_id=request_id or usage.request_id,
        )

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
                **usage.as_trace_attributes(),
            },
        )
        # 发射事件，获取生命周期决策
        response_decision = self.lifecycle.emit_provider_response(response_event, "".join(text_chunks), tool_calls)
        response_event.details.update(response_decision.details)
        list(self._emit(response_event))
        visible_text = "".join(text_chunks).strip()
        reasoning_summary = (
            f"Prepared {len(tool_calls)} tool call(s)."
            if tool_calls
            else (safe_preview(visible_text, 220) if visible_text else "No visible text returned.")
        )
        list(
            self._emit(
                self._event(
                    REASONING_SUMMARY,
                    message=reasoning_summary,
                    details={
                        "summary": reasoning_summary,
                        "tool_count": len(tool_calls),
                        "text_length": len(visible_text),
                    },
                )
            )
        )
        list(
            self._emit(
                self._event(
                    REASONING_END,
                    message="Public reasoning progress completed.",
                    details={"summary": "Model response received and parsed."},
                )
            )
        )
        #使用决策信息
        assistant_text = response_decision.assistant_text or "".join(text_chunks)
        resolved_tool_calls = response_decision.tool_calls or tool_calls
        if not resolved_tool_calls and assistant_text.strip():
            fallback_tool_calls = self._tool_calls_from_text_fallback(assistant_text)
            if fallback_tool_calls:
                response_event.details["tool_call_text_fallback"] = True
                response_event.details["tool_call_text_fallback_mode"] = "trailing_single_call"
                resolved_tool_calls = fallback_tool_calls
                assistant_text = ""
        child_runtime = self._is_subagent_runtime()
        explicit_subagent = None if child_runtime else self._explicit_subagent_request(self.state)
        orchestrated_edit = None if child_runtime else self._explicit_orchestrated_edit_request(self.state)
        denied_text_tool = self._denied_text_tool_call_name(assistant_text) if assistant_text.strip() and not resolved_tool_calls else None
        if denied_text_tool is not None and orchestrated_edit is None:
            response_event.details["tool_call_text_fallback_denied"] = True
            response_event.details["tool_call_text_fallback_denied_tool"] = denied_text_tool
            assistant_text = ""
        if (
            explicit_subagent is not None
            and denied_text_tool is None
            and not self._has_subagent_result_since_latest_user(self.state)
            and not any(call.name == "spawn_subagent" for call in resolved_tool_calls)
        ):
            response_event.details["subagent_forced"] = True
            resolved_tool_calls = [
                ToolCall(
                    id=str(uuid.uuid4()),
                    name="spawn_subagent",
                    arguments={
                        "subagent_type": explicit_subagent["spec_name"],
                        "task": explicit_subagent["task"],
                    },
                )
            ]
            assistant_text = ""
        if (
            orchestrated_edit is not None
            and self.enforce_orchestrated_edit_contract
            and not self._has_orchestration_result_since_latest_user(self.state)
            and not any(call.name == "orchestrate_agents" for call in resolved_tool_calls)
        ):
            response_event.details["orchestrated_edit_forced"] = True
            resolved_tool_calls = [
                ToolCall(
                    id=str(uuid.uuid4()),
                    name="orchestrate_agents",
                    arguments={
                        "goal": orchestrated_edit["goal"],
                        "workflow": "code_change",
                        "allow_edits": True,
                        "max_agents": 6,
                    },
                )
            ]
            assistant_text = ""
        resolved_tool_calls = self._normalize_orchestrate_tool_calls(resolved_tool_calls, orchestrated_edit)
        resolved_tool_calls = self._normalize_subagent_tool_calls(resolved_tool_calls, explicit_subagent)
        patch_wait_message = self._pending_patch_artifact_wait_message(self.state, resolved_tool_calls)
        if patch_wait_message:
            response_event.details["patch_artifact_wait_guard"] = True
            assistant_text = patch_wait_message
            resolved_tool_calls = []
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

    def _ensure_provider_context_budget(self) -> None:
        estimated_chars = self._estimate_uncompacted_context_chars()
        threshold = max(8000, self.max_context_messages * 2000)
        if estimated_chars <= threshold:
            return
        list(self._emit_compaction_if_needed())

    def _estimate_uncompacted_context_chars(self) -> int:
        messages = self.state.messages[self.state.compaction.summarized_message_count :]
        total = 0
        for message in messages:
            for part in message.content:
                text = getattr(part, "text", None)
                if isinstance(text, str):
                    total += len(text)
                else:
                    total += len(str(getattr(part, "arguments", "")))
        return total

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

    def _friendly_tool_exception_message(self, call: ToolCall, exc: Exception) -> str:
        message = str(exc)
        if not isinstance(exc, PermissionError) or call.name != "read_file":
            return message

        raw_path = str(call.arguments.get("path", "")).strip()
        if not raw_path:
            return message

        try:
            resolved = Path(raw_path)
            if not resolved.is_absolute():
                resolved = self.tool_registry.workspace / resolved
            resolved = resolved.resolve()
        except OSError:
            return message

        if not is_protected_path(self.tool_registry.workspace, resolved):
            return message

        name = resolved.name.lower()
        if name == ".env" or name.startswith(".env."):
            return (
                f"Cannot read protected file {raw_path} directly. Secrets in .env are blocked by policy. "
                "To check the active model, use /settings or `pp-agent config show` instead."
            )
        return f"Cannot read protected file {raw_path} directly. Protected paths and secret-like files are blocked by policy."

    def _tool_calls_from_text_fallback(self, assistant_text: str) -> list[ToolCall]:
        last_brace = assistant_text.rfind("{")
        if last_brace < 0:
            return []
        prefix = assistant_text[:last_brace].rstrip()
        name_match = TEXT_TOOL_NAME_RE.search(prefix)
        if not name_match:
            return []
        name = name_match.group(1).strip()
        raw_arguments = assistant_text[last_brace:].strip()
        if name in TEXT_TOOL_CALL_FALLBACK_DENYLIST:
            return []
        if name not in TEXT_TOOL_CALL_FALLBACK_ALLOWLIST:
            return []
        try:
            spec = self.tool_registry.get_spec(name)
        except KeyError:
            return []
        metadata = self.tool_registry.metadata().get(name)
        if spec.permission_domain != "read":
            return []
        if metadata is not None and metadata.tool_family not in {None, "file", "repo"}:
            return []

        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return []
        if not isinstance(arguments, dict):
            return []
        return [ToolCall(id=str(uuid.uuid4()), name=name, arguments=arguments)]

    def _denied_text_tool_call_name(self, assistant_text: str) -> str | None:
        last_brace = assistant_text.rfind("{")
        if last_brace < 0:
            return None
        prefix = assistant_text[:last_brace].rstrip()
        name_match = TEXT_TOOL_NAME_RE.search(prefix)
        if not name_match:
            return None
        name = name_match.group(1).strip()
        return name if name in TEXT_TOOL_CALL_FALLBACK_DENYLIST else None

    @staticmethod
    def _available_subagent_specs() -> set[str]:
        from pp_agent.subagents.specs import default_subagent_specs

        return set(default_subagent_specs())

    def _explicit_subagent_request(self, state: AgentState) -> dict[str, str] | None:
        latest_user_text = self._latest_user_text(state)
        if "@subagent" not in latest_user_text:
            return None
        _, _, remainder = latest_user_text.partition("@subagent")
        task = remainder.strip(" \t\r\n:：,-")
        if not task:
            task = "Handle the user's explicit subagent request."
        lowered = task.lower()
        spec_name = "change-reviewer" if any(token in lowered for token in ("review", "diff", "change", "审查", "评审", "改动")) else "repo-researcher"
        return {"spec_name": spec_name, "task": task}

    def _normalize_subagent_tool_calls(
        self,
        tool_calls: list[ToolCall],
        explicit_subagent: dict[str, str] | None,
    ) -> list[ToolCall]:
        if not tool_calls:
            return tool_calls

        available_specs = self._available_subagent_specs()
        normalized: list[ToolCall] = []
        for call in tool_calls:
            if call.name != "spawn_subagent":
                normalized.append(call)
                continue

            arguments = dict(call.arguments)
            if explicit_subagent is not None:
                requested_type = str(arguments.get("subagent_type", "")).strip()
                if requested_type not in available_specs:
                    arguments["subagent_type"] = explicit_subagent["spec_name"]
                if not str(arguments.get("task", "")).strip():
                    arguments["task"] = explicit_subagent["task"]
            normalized.append(call.model_copy(update={"arguments": arguments}))
        return normalized

    def _normalize_orchestrate_tool_calls(
        self,
        tool_calls: list[ToolCall],
        orchestrated_edit: dict[str, str] | None,
    ) -> list[ToolCall]:
        if not tool_calls or orchestrated_edit is None or not self.enforce_orchestrated_edit_contract or self._is_subagent_runtime():
            return tool_calls
        normalized: list[ToolCall] = []
        for call in tool_calls:
            if call.name != "orchestrate_agents":
                normalized.append(call)
                continue
            arguments = dict(call.arguments)
            original_goal = str(arguments.get("goal") or "").strip()
            arguments["goal"] = orchestrated_edit["goal"]
            arguments["workflow"] = "code_change"
            arguments["allow_edits"] = True
            try:
                arguments["max_agents"] = max(int(arguments.get("max_agents") or 0), 6)
            except (TypeError, ValueError):
                arguments["max_agents"] = 6
            arguments["_orchestrated_edit_contract"] = {
                "goal_source": "latest_user_message",
                "original_tool_goal": original_goal,
            }
            normalized.append(call.model_copy(update={"arguments": arguments}))
        return normalized

    def _explicit_orchestrated_edit_request(self, state: AgentState) -> dict[str, str] | None:
        if self._is_subagent_runtime():
            return None
        latest_user_text = self._latest_user_text(state).strip()
        if explicit_orchestrated_edit_request(latest_user_text):
            return {"goal": latest_user_text}
        return None

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
                "turn_id": self.state.turn.turn_id,
                "tool_calls": [call.model_dump(mode="json") for call in tool_calls],
                **preview,
            },
            session_id=self.session_id,
            turn_id=self.state.turn.turn_id,
            origin={"source": "runtime", "kind": "planner_approval", "session_id": self.session_id},
            expires_at=time.time() + 24 * 60 * 60,
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
        recall_metadata = self.state.memory_context.get("memory_recall")
        if isinstance(recall_metadata, dict):
            context_event.details["memory_recall"] = recall_metadata
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
        event = self._enrich_activity_event(event)
        event = self.runtime_monitor.attach_event(event, self.state)
        if self.timeline_store is not None and event.type != "message_delta":
            self.timeline_store.append(self.session_id, event)
        self.lifecycle.emit(event)
        if self._captured_events is not None:
            self._captured_events.append(event)
        yield event

    def _emit_cancelled_turn(self, reason: str) -> Iterator[AgentEvent]:
        message = reason or "cancel_requested"
        self.state.error_message = message
        yield from self._emit(
            self._event(
                ERROR,
                message=message,
                is_error=True,
                details={"failure_kind": "canceled", "cancelled": True},
            )
        )
        yield from self._emit(
            self._event(
                TURN_END,
                details={"turn_id": self.state.turn.turn_id, "failed": True, "failure_kind": "canceled"},
            )
        )
        yield from self._set_turn_phase("idle", "canceled")

    def _observe_runtime_event(self, event: AgentEvent) -> None:
        """把既有 Runtime lifecycle event 转换为结构化 Trace 事件和 span。"""
        try:
            self._observe_runtime_event_impl(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("trace observer ignored lifecycle event failure: %s", exc)

    def _observe_runtime_event_impl(self, event: AgentEvent) -> None:
        """执行 Runtime event 到 Trace 的实际转换；调用方负责异常隔离。"""
        if event.type == MESSAGE_DELTA:
            return
        details = dict(event.details or {})
        payload = {
            "message": event.message,
            "tool_name": event.tool_name,
            "is_error": event.is_error,
            "details": details,
        }
        self.observability.event(event.type, attributes=self._trace_event_attributes(event), payload=payload)
        record_span = getattr(self.observability, "record_completed_span", None)
        if not callable(record_span):
            return
        key = self._trace_span_key(event)
        if event.type in {TURN_START, BEFORE_PROVIDER_REQUEST, TOOL_START}:
            if key:
                self._trace_event_starts[key] = event
            return
        if event.type == CONTEXT_BUILT:
            record_span(
                "context.build",
                "context",
                started_at=event.timestamp,
                ended_at=event.timestamp,
                attributes={
                    "message_count": details.get("message_count"),
                    "queue_count": details.get("queue_count"),
                    "memory_count": self._trace_memory_count(details),
                    "estimated_tokens": details.get("estimated_tokens"),
                },
                output={"memory_recall": details.get("memory_recall")} if isinstance(details.get("memory_recall"), dict) else {},
            )
            self._record_memory_span_from_context(event, record_span)
            return
        if event.type == PROVIDER_RESPONSE:
            start = self._trace_event_starts.pop("llm", None)
            record_span(
                "llm.call",
                "llm",
                started_at=start.timestamp if start is not None else event.timestamp,
                ended_at=event.timestamp,
                attributes={
                    "provider": details.get("provider"),
                    "model": details.get("model"),
                    "message_count": details.get("message_count"),
                    "tool_count": details.get("tool_count"),
                    "finish_reason": ",".join(details.get("finish_reasons") or []),
                    "tool_call_count": details.get("tool_count"),
                    "input_tokens": details.get("input_tokens"),
                    "output_tokens": details.get("output_tokens"),
                    "total_tokens": details.get("total_tokens"),
                    "cached_input_tokens": details.get("cached_input_tokens"),
                    "reasoning_tokens": details.get("reasoning_tokens"),
                    "cost_usd": details.get("cost_usd"),
                    "latency_ms": details.get("latency_ms"),
                    "provider_latency_ms": details.get("provider_latency_ms"),
                    "retry_count": details.get("retry_count", 0),
                    "attempt_index": details.get("attempt_index", 1),
                    "request_id": details.get("request_id"),
                },
                output={
                    "text_length": details.get("text_length"),
                    "streamed_event_count": details.get("streamed_event_count"),
                },
            )
            if int(details.get("tool_count") or 0) == 0 and not event.is_error:
                record_span("final.answer", "system", started_at=event.timestamp, ended_at=event.timestamp, attributes={"source": "provider_response"})
            return
        if event.type == PROVIDER_ERROR:
            start = self._trace_event_starts.pop("llm", None)
            record_span(
                "llm.call",
                "llm",
                status="error",
                started_at=start.timestamp if start is not None else event.timestamp,
                ended_at=event.timestamp,
                attributes={
                    "provider": details.get("provider"),
                    "model": details.get("model"),
                    "latency_ms": details.get("latency_ms"),
                    "retry_count": details.get("retry_count", 0),
                    "attempt_index": details.get("attempt_index", 1),
                },
                error=event.message or "provider_error",
            )
            return
        if event.type == TOOL_END:
            start = self._trace_event_starts.pop(key or "", None)
            output = dict(details)
            if event.tool_name in {"list_attachments", "inspect_attachment", "search_attachment", "read_attachment_chunk", "read_attachment_text", "read_attachment_range", "search_attachment_symbols", "read_attachment_symbol"}:
                output = self._attachment_trace_event_output(output)
            output["content_preview"] = safe_preview(event.message, 2000)
            if event.tool_name in {"read_attachment_chunk", "read_attachment_text", "read_attachment_range", "read_attachment_symbol"}:
                output["content_preview"] = safe_preview(str(output.get("text_preview") or output.get("summary") or "attachment content read"), 500)
            record_span(
                "tool.call",
                "tool",
                status="error" if event.is_error else ("pending" if details.get("staged") or details.get("approval_pending") else "ok"),
                started_at=start.timestamp if start is not None else event.timestamp,
                ended_at=event.timestamp,
                attributes={
                    "tool_name": event.tool_name,
                    "tool_call_id": details.get("tool_call_id"),
                    "requires_confirmation": details.get("requires_confirmation"),
                    "permission_domain": details.get("permission_domain"),
                    "tool_origin": details.get("tool_family") or details.get("category"),
                    "is_subagent_tool": event.tool_name in {"spawn_subagent", "orchestrate_agents"},
                    "source": "runtime_lifecycle_event",
                },
                input={"arguments": sanitize_tool_args(event.tool_args or {})},
                output=output,
                error=event.message if event.is_error else None,
            )
            if event.tool_name in {"spawn_subagent", "orchestrate_agents"}:
                record_span(
                    "subagent.run",
                    "subagent",
                    status="error" if event.is_error else "ok",
                    started_at=start.timestamp if start is not None else event.timestamp,
                    ended_at=event.timestamp,
                    attributes=details,
                    error=event.message if event.is_error else None,
                )
            return
        if event.type == TURN_END:
            start = self._trace_event_starts.pop(key or "", None)
            record_span(
                "agent.turn",
                "turn",
                status="error" if event.is_error or details.get("failed") else "ok",
                started_at=start.timestamp if start is not None else event.timestamp,
                ended_at=event.timestamp,
                attributes=details,
                error=details.get("failure_kind") if details.get("failed") else None,
            )
            return
        if event.type in {PLANNER_GATE_PENDING, PLANNER_GATE_APPROVED, PLANNER_GATE_REJECTED}:
            status = "pending" if event.type == PLANNER_GATE_PENDING else ("blocked" if event.type == PLANNER_GATE_REJECTED else "ok")
            record_span(
                "approval.decision",
                "approval",
                status=status,
                started_at=event.timestamp,
                ended_at=event.timestamp,
                attributes={
                    **details,
                    "approval_token": details.get("token"),
                    "decision": "pending" if status == "pending" else ("rejected" if status == "blocked" else "approved"),
                },
            )
            return
        if event.type == TOOL_CALL and details.get("policy_action"):
            status = "blocked" if details.get("policy_action") in {"deny", "reject"} else "ok"
            record_span(
                "policy.decision",
                "policy",
                status=status,
                started_at=event.timestamp,
                ended_at=event.timestamp,
                attributes={**details, "source_tool_name": event.tool_name},
            )
            return
        if event.type in {
            CHECKPOINT_BEFORE_CREATE,
            CHECKPOINT_CREATED,
            CHECKPOINT_RESTORE_PREVIEW,
            CHECKPOINT_BEFORE_RESTORE,
            CHECKPOINT_RESTORED,
            CHECKPOINT_RESTORE_FAILED,
            SESSION_SAFE_REWIND_STARTED,
            SESSION_SAFE_REWIND_COMPLETED,
        }:
            name = "checkpoint.create" if event.type in {CHECKPOINT_BEFORE_CREATE, CHECKPOINT_CREATED} else (
                "checkpoint.preview_rewind" if event.type == CHECKPOINT_RESTORE_PREVIEW else "checkpoint.execute_rewind"
            )
            record_span(
                name,
                "checkpoint",
                status="error" if event.is_error or event.type == CHECKPOINT_RESTORE_FAILED else "ok",
                started_at=event.timestamp,
                ended_at=event.timestamp,
                attributes=details,
                error=event.message if event.is_error else None,
            )

    def _trace_event_attributes(self, event: AgentEvent) -> dict[str, object]:
        return {
            "session_id": event.session_id,
            "turn_id": event.turn_id,
            "phase": event.phase,
            "tool_name": event.tool_name,
            "is_error": event.is_error,
        }

    def _trace_span_key(self, event: AgentEvent) -> str:
        if event.type in {TURN_START, TURN_END}:
            return f"turn:{event.turn_id}"
        if event.type in {TOOL_START, TOOL_END, TOOL_ERROR, TOOL_RESULT}:
            tool_call_id = event.details.get("tool_call_id") if event.details else None
            return f"tool:{tool_call_id or event.tool_name or ''}"
        if event.type in {BEFORE_PROVIDER_REQUEST, PROVIDER_RESPONSE, PROVIDER_ERROR}:
            return "llm"
        return ""

    @staticmethod
    def _trace_memory_count(details: dict[str, object]) -> int:
        recall = details.get("memory_recall")
        if not isinstance(recall, dict):
            return 0
        return int(recall.get("returned_count") or len(recall.get("hits") or recall.get("snippets") or []))

    @staticmethod
    def _attachment_trace_event_output(details: dict[str, object]) -> dict[str, object]:
        """
        脱敏 runtime lifecycle 生成的附件工具 trace 输出，避免完整 chunk/range 文本落盘。
        """

        output = dict(details)
        text = output.pop("text", None)
        if isinstance(text, str):
            output["text_preview"] = safe_preview(text, 240)
            output["text_length"] = len(text)
        chunk = output.get("chunk")
        if isinstance(chunk, dict):
            chunk_copy = dict(chunk)
            chunk_text = chunk_copy.pop("text", None)
            if isinstance(chunk_text, str):
                chunk_copy["text_preview"] = safe_preview(chunk_text, 240)
                chunk_copy["text_length"] = len(chunk_text)
            output["chunk"] = chunk_copy
        return output

    @staticmethod
    def _record_memory_span_from_context(event: AgentEvent, record_span) -> None:
        recall = event.details.get("memory_recall") if event.details else None
        if not isinstance(recall, dict):
            return
        record_span(
            "memory.recall",
            "memory",
            started_at=event.timestamp,
            ended_at=event.timestamp,
            input={
                "query_preview": recall.get("query") or recall.get("query_preview"),
                "scope": recall.get("scope"),
                "top_k": recall.get("top_k"),
                "mode": recall.get("mode"),
            },
            output={
                "returned_count": recall.get("returned_count") or len(recall.get("hits") or recall.get("snippets") or []),
                "injected_count": recall.get("injected_count"),
                "injected_tokens": recall.get("injected_tokens"),
                "hits": recall.get("hits") or recall.get("snippets") or [],
                "warnings": recall.get("warnings") or [],
            },
        )

    @staticmethod
    def _trace_status_from_events(events: list[AgentEvent]):
        if any(event.details.get("cancelled") for event in events if event.details):
            return "cancelled"
        if any(event.type in {PLANNER_GATE_PENDING} for event in events):
            return "pending"
        if any(event.is_error or event.type == ERROR for event in events):
            return "error"
        return "ok"

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
        injected_message = ChatMessage(role="user", content=[TextPart(text=queued.text)], timestamp=time.time())
        self.state.messages.append(injected_message)
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
        context = _TurnPersistContext(
            new_message_start_index=len(self.state.messages) - 1,
            turn_id=f"turn-{self.state.turn.turn_id + 1}",
            turn_started_at=injected_message.timestamp,
        )
        yield from self._run_loop(turn_persist_context=context)

    def _persist(
        self,
        *,
        dual_write_turn_id: Optional[str] = None,
        new_messages: Optional[list[ChatMessage]] = None,
        memory_metadata: Optional[dict[str, object]] = None,
    ) -> None:
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
        if dual_write_turn_id and new_messages is not None and self.memory_provider.is_enabled():
            try:
                self.memory_provider.on_turn_persisted(
                    session_id=self.session_id,
                    turn_id=dual_write_turn_id,
                    new_messages=new_messages,
                    metadata={
                        "source": "runtime_dual_write",
                        "workspace": str(self.tool_registry.workspace),
                        "session_head_id": record.active_head_id,
                        "turn_started_at": None,
                        "turn_finished_at": time.time(),
                        **(memory_metadata or {}),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Memory dual write failed for session=%s turn=%s; falling back to primary storage only: %s",
                    self.session_id,
                    dual_write_turn_id,
                    exc,
                )
            else:
                if self.auto_index_scheduler.is_enabled():
                    if self.auto_index_scheduler.submit():
                        logger.debug(
                            "Submitted async memory indexing for session=%s turn=%s",
                            self.session_id,
                            dual_write_turn_id,
                        )
                    else:
                        logger.debug(
                            "Skipped async memory indexing for session=%s turn=%s because a prior indexing task is still running",
                            self.session_id,
                            dual_write_turn_id,
                        )
        if dual_write_turn_id and new_messages is not None and self.learning_runtime is not None:
            try:
                candidates = self.learning_runtime.on_turn_persisted(
                    session_id=self.session_id,
                    turn_id=dual_write_turn_id,
                    new_messages=new_messages,
                )
            except Exception as exc:  # noqa: BLE001
                list(
                    self._emit(
                        self._event(
                            LEARNING_EXTRACTION_FAILED,
                            message=str(exc),
                            is_error=True,
                            details={"turn_id": dual_write_turn_id},
                        )
                    )
                )
            else:
                if candidates:
                    list(
                        self._emit(
                            self._event(
                                LEARNING_CANDIDATES_CREATED,
                                details={
                                    "turn_id": dual_write_turn_id,
                                    "candidate_count": len(candidates),
                                    "candidate_ids": [candidate.id for candidate in candidates],
                                },
                            )
                        )
                    )

    def _session_exists(self) -> bool:
        try:
            self.session_store.load(self.session_id)
            return True
        except FileNotFoundError:
            return False

    def _pending_action_store(self) -> PendingActionStore:
        root = self.tool_registry.workspace / ".pp-agent" / "pending-edits"
        return PendingActionStore(root)

    def _attach_session_to_pending_action(self, result: ToolExecutionResult) -> None:
        token = result.details.get("token") if isinstance(result.details, dict) else None
        if not isinstance(token, str) or not token:
            return
        store = self._pending_action_store()
        try:
            payload = store.load(token)
        except FileNotFoundError:
            return
        details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        details.setdefault("session_id", self.session_id)
        details.setdefault("turn_id", self.state.turn.turn_id)
        details.setdefault("tool_name", result.tool_name)
        details.setdefault("tool_call_id", result.tool_call_id)
        details.setdefault("origin", {"source": "runtime", "session_id": self.session_id})
        payload["details"] = details
        payload.setdefault("session_id", self.session_id)
        payload.setdefault("turn_id", self.state.turn.turn_id)
        payload.setdefault("tool_call_id", result.tool_call_id)
        payload.setdefault("origin", {"source": "runtime", "session_id": self.session_id})
        effect = result.details.get("effect") if isinstance(result.details, dict) else None
        if isinstance(effect, dict) and effect.get("payload_digest"):
            payload.setdefault("canonical_key", effect.get("payload_digest"))
            payload.setdefault("normalized_arguments", effect.get("normalized_arguments"))
        store.save(token, payload)

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
        subagent_failure_note = self._latest_subagent_failure_note(state)
        if subagent_failure_note:
            notes.append(subagent_failure_note)
        if (
            not self._is_subagent_runtime()
            and self._explicit_orchestrated_edit_request(state) is not None
            and self._has_orchestration_result_since_latest_user(state)
            and not self._has_patch_artifact_orchestration_since_latest_user(state)
        ):
            notes.append(
                "The current turn requires orchestrated code_change edits, but the latest orchestration produced no apply_patch_artifact. "
                "Report that failure; do not switch to direct edit_file/write_file fallback."
            )
        pending_action_note = self._latest_pending_action_note(state)
        if pending_action_note:
            notes.append(pending_action_note)
        web_lookup_note = self._latest_web_lookup_note(state)
        if web_lookup_note:
            notes.append(web_lookup_note)
        verification_note = self._verification_gate_required_note(state)
        if verification_note:
            notes.append(verification_note)
        reviewer_note = self._reviewer_escalation_note(state)
        if reviewer_note:
            notes.append(reviewer_note)
        if not notes:
            return messages
        directive = ChatMessage(
            role="system",
            content=[TextPart(text="Runtime notes:\n" + "\n".join(f"- {note}" for note in notes))],
            timestamp=time.time(),
        )
        return [messages[0], directive, *messages[1:]] if messages else [directive]

    @staticmethod
    def _latest_user_text(state: AgentState) -> str:
        for message in reversed(state.messages):
            if message.role != "user":
                continue
            parts = [part.text.strip() for part in message.content if isinstance(part, TextPart) and part.text.strip()]
            if parts:
                return "\n".join(parts).strip()
        return ""

    @staticmethod
    def _latest_user_index(state: AgentState) -> int | None:
        for index in range(len(state.messages) - 1, -1, -1):
            if state.messages[index].role == "user":
                return index
        return None

    def _has_subagent_result_since_latest_user(self, state: AgentState) -> bool:
        latest_user_index = self._latest_user_index(state)
        start = 0 if latest_user_index is None else latest_user_index + 1
        for message in state.messages[start:]:
            if message.role == "tool" and message.tool_name == "spawn_subagent":
                return True
        return False

    def _has_orchestration_result_since_latest_user(self, state: AgentState) -> bool:
        latest_user_index = self._latest_user_index(state)
        start = 0 if latest_user_index is None else latest_user_index + 1
        for message in state.messages[start:]:
            if message.role == "tool" and message.tool_name == "orchestrate_agents":
                return True
        return False

    def _has_patch_artifact_orchestration_since_latest_user(self, state: AgentState) -> bool:
        return self._latest_pending_patch_artifact_since_latest_user(state) is not None

    def _latest_pending_patch_artifact_since_latest_user(self, state: AgentState) -> dict[str, list[str]] | None:
        latest_user_index = self._latest_user_index(state)
        start = 0 if latest_user_index is None else latest_user_index + 1
        tokens: list[str] = []
        changed_paths: list[str] = []
        for message in state.messages[start:]:
            if message.role != "tool" or message.tool_name != "orchestrate_agents":
                continue
            details = dict(message.metadata.get("tool_details") or {})
            steps = details.get("steps")
            if not isinstance(steps, list):
                continue
            for raw_step in steps:
                if not isinstance(raw_step, dict):
                    continue
                staged_actions = raw_step.get("staged_actions")
                if not isinstance(staged_actions, list):
                    continue
                inspected_paths = raw_step.get("inspected_paths")
                for action in staged_actions:
                    if not isinstance(action, dict) or action.get("action_type") != "apply_patch_artifact":
                        continue
                    token = str(action.get("token") or "").strip()
                    if token:
                        tokens.append(token)
                    for path in action.get("changed_paths") or []:
                        value = str(path).replace("\\", "/").strip()
                        if value and value not in changed_paths:
                            changed_paths.append(value)
                    if isinstance(inspected_paths, list):
                        for path in inspected_paths:
                            value = str(path).replace("\\", "/").strip()
                            if value and not value.endswith(".patch") and value not in changed_paths:
                                changed_paths.append(value)
        if not tokens:
            return None
        return {"tokens": tokens, "changed_paths": changed_paths}

    def _is_subagent_runtime(self) -> bool:
        return getattr(self, "subagent_profile", None) is not None

    def _pending_patch_artifact_wait_message(self, state: AgentState, tool_calls: list[ToolCall]) -> str:
        if self._is_subagent_runtime() or not tool_calls:
            return ""
        pending_patch = self._latest_pending_patch_artifact_since_latest_user(state)
        if pending_patch is None:
            return ""
        tokens = ", ".join(pending_patch.get("tokens") or []) or "unknown"
        pending_paths = {
            path.replace("\\", "/").strip()
            for path in pending_patch.get("changed_paths", [])
            if path
        }
        attempted_tools = sorted({call.name for call in tool_calls if call.name})
        for call in tool_calls:
            if call.name not in {"read_file", "list_files"}:
                continue
            raw_path = str(call.arguments.get("path") or "").replace("\\", "/").strip()
            if raw_path and (
                raw_path in pending_paths
                or any(path.startswith(f"{raw_path.rstrip('/')}/") for path in pending_paths)
            ):
                return (
                    "The multi-agent code_change workflow has already staged an apply_patch_artifact, so this turn should stop probing and wait for approval. "
                    f"The requested path `{raw_path}` is still pending inside the patch artifact. "
                    f"Use the Approval panel or approve_pending_action first (token: {tokens}). "
                    "After approval, read the file from the main workspace."
                )
        if attempted_tools:
            return (
                "The multi-agent code_change workflow has already staged an apply_patch_artifact, so this turn should stop probing and wait for approval. "
                f"Do not continue with {', '.join(attempted_tools)} before approval. "
                f"Use the Approval panel or approve_pending_action first (token: {tokens}). "
                "The main workspace will not reflect the staged change until approval."
            )
        return ""

    @staticmethod
    def _latest_subagent_failure_note(state: AgentState) -> str:
        for message in reversed(state.messages):
            if message.role != "tool" or message.tool_name != "spawn_subagent":
                continue
            if not bool(message.metadata.get("is_error")):
                return ""
            details = dict(message.metadata.get("tool_details") or {})
            failure_kind = str(details.get("failure_kind") or "subagent_failed").strip()
            error_message = str(details.get("error_message") or details.get("summary") or "").strip()
            if error_message:
                return (
                    "The most recent subagent delegation failed "
                    f"({failure_kind}): {error_message}. Explain the failure clearly and suggest retrying or switching to direct execution. "
                    "Do not assume the delegated task already completed."
                )
            return (
                f"The most recent subagent delegation failed ({failure_kind}). Explain the failure clearly and suggest retrying or switching to direct execution. "
                "Do not assume the delegated task already completed."
            )
        return ""

    def _latest_pending_action_note(self, state: AgentState) -> str:
        latest_user_index = self._latest_user_index(state)
        start = 0 if latest_user_index is None else latest_user_index + 1
        consumed_tokens: set[str] = set()
        terminal_states = {
            "denied",
            "expired",
            "execution_failed",
            "execution_succeeded",
            "grant_consumed",
            "grant_invalidated",
            "orphaned",
            "quarantined",
            "rejected",
        }
        for message in state.messages[start:]:
            if message.role != "tool":
                continue
            details = dict(message.metadata.get("tool_details") or {})
            token = str(details.get("token") or "").strip()
            lifecycle = details.get("lifecycle") or {}
            state_name = str(lifecycle.get("state") or "").strip()
            if token and (state_name in terminal_states or bool(details.get("external_approval_result"))):
                consumed_tokens.add(token)
        staged_tokens: list[str] = []
        staged_tools: list[str] = []
        staged_kinds: list[str] = []
        for message in state.messages[start:]:
            if message.role != "tool":
                continue
            details = dict(message.metadata.get("tool_details") or {})
            if not (
                bool(details.get("staged"))
                or bool(details.get("patch_artifact_pending"))
                or (details.get("lifecycle") or {}).get("state") == "grant_attached"
            ):
                continue
            token = str(details.get("token") or "").strip()
            if token and token in consumed_tokens:
                continue
            if token and token not in staged_tokens:
                staged_tokens.append(token)
            tool_name = str(message.tool_name or details.get("tool_name") or "").strip()
            if tool_name and tool_name not in staged_tools:
                staged_tools.append(tool_name)
            kind = "patch_artifact" if bool(details.get("patch_artifact_pending")) else "staged_tool"
            if kind not in staged_kinds:
                staged_kinds.append(kind)
        if not staged_tokens and not staged_tools:
            return ""
        token_text = ", ".join(staged_tokens[:4]) or "unknown"
        tool_text = ", ".join(staged_tools[:4]) or "unknown"
        kind_text = ", ".join(staged_kinds[:2]) or "pending"
        return (
            f"A {kind_text} approval is still pending for tool(s): {tool_text}. "
            f"Pending tokens: {token_text}. Do not repeat the same call or probe for results until approval is granted."
        )

    def _latest_web_lookup_note(self, state: AgentState) -> str:
        latest_user_index = self._latest_user_index(state)
        start = 0 if latest_user_index is None else latest_user_index + 1
        attempts = self._web_lookup_attempts_since(state, start=start)
        if not attempts:
            return ""
        if attempts["count"] < WEB_LOOKUP_ATTEMPT_LIMIT and not attempts["terminal"]:
            return ""
        last = attempts["last"]
        if last is None:
            return ""
        action = str(last.get("tool_name") or "web lookup").strip()
        reason = str(last.get("reason") or "limited results").strip()
        if attempts["terminal"]:
            return (
                f"Web lookup has already reached a terminal result after {attempts['count']} attempt(s) "
                f"({action}: {reason}). Do not keep retrying the same site/provider. "
                "Summarize the best available findings, or if nothing reliable was found, state the blocker and ask for a narrower source or query."
            )
        return (
            f"Web lookup has already used {attempts['count']} attempt(s) in this turn. "
            "Do not keep cycling through search/fetch on the same topic. Summarize what you have or ask for a narrower source."
        )

    def _web_lookup_attempts_since(self, state: AgentState, *, start: int) -> dict[str, object]:
        count = 0
        terminal = False
        last: dict[str, object] | None = None
        for message in state.messages[start:]:
            if message.role != "tool":
                continue
            tool_name = str(message.tool_name or "").strip()
            if tool_name not in WEB_TOOL_NAMES:
                continue
            details = dict(message.metadata.get("tool_details") or {})
            count += 1
            reason = ""
            if bool(message.metadata.get("is_error")) or bool(details.get("is_error")):
                terminal = True
                content_text = ""
                if message.content:
                    first_part = message.content[0]
                    content_text = str(getattr(first_part, "text", "") or "")
                reason = str(details.get("error") or content_text or "error")
            elif tool_name in {"web.search", "web.news"}:
                result_count = details.get("result_count")
                if result_count == 0:
                    terminal = True
                    reason = "no results"
            elif tool_name == "web.fetch" and not details.get("text"):
                terminal = True
                reason = "empty response"
            last = {"tool_name": tool_name, "reason": reason or str(details.get("error") or details.get("status_code") or "ok")}
        return {"count": count, "terminal": terminal, "last": last}

    def _append_runtime_system_note(self, text: str, *, kind: str, details: dict[str, object] | None = None) -> None:
        self.state.messages.append(
            ChatMessage(
                role="system",
                content=[TextPart(text=text)],
                metadata={"runtime_note": kind, **(details or {})},
                timestamp=time.time(),
            )
        )

    def _verification_gate_required_note(self, state: AgentState) -> str:
        if self._is_subagent_runtime():
            return ""
        gate = self._verification_gate_state(state)
        if not gate["file_changed"] or gate["verification_passed"]:
            return ""
        return (
            "Verification required before final answer: this coding task changed workspace files, but no verification evidence is visible yet. "
            "Do not claim success. Inspect the changed file or diff, run the smallest relevant test/check when possible, then continue. "
            "If verification cannot be run, state the blocker explicitly."
        )

    def _reviewer_escalation_note(self, state: AgentState) -> str:
        if self._is_subagent_runtime():
            return ""
        gate = self._verification_gate_state(state)
        latest_text = self._latest_user_text(state).lower()
        explicit_review = any(token in latest_text for token in ("review", "审查", "评审", "diff review", "code review"))
        reasons: list[str] = []
        if gate["changed_file_count"] > 1:
            reasons.append("multiple changed files")
        if gate["patch_artifact"]:
            reasons.append("patch artifact involved")
        if gate["consecutive_failures"] >= 2:
            reasons.append("repeated tool failures")
        if explicit_review:
            reasons.append("user requested review")
        if not reasons:
            return ""
        return (
            "Reviewer escalation is optional, not mandatory. "
            f"Consider `change-reviewer` only because: {', '.join(reasons)}. "
            "For simple changes with clear verification evidence, proceed without reviewer."
        )

    def _verification_gate_state(self, state: AgentState) -> dict[str, object]:
        latest_user_index = self._latest_user_index(state)
        start = 0 if latest_user_index is None else latest_user_index + 1
        file_changed_paths: list[str] = []
        file_changed = False
        command_failed = False
        verification_passed = False
        verification_failed = False
        patch_failed = False
        patch_artifact = False
        consecutive_failures = 0
        trailing_failures = 0
        saw_file_change_before_inspect = False
        for message in state.messages[start:]:
            if message.role != "tool":
                continue
            details = dict(message.metadata.get("tool_details") or {})
            tool_name = str(message.tool_name or details.get("tool_name") or details.get("source_tool_name") or "").strip()
            action_type = str(details.get("action_type") or tool_name or "").strip()
            is_error = bool(message.metadata.get("is_error") or details.get("success") is False)
            returncode = details.get("returncode")
            if isinstance(returncode, int) and returncode != 0:
                is_error = True
            if action_type == "apply_patch_artifact" or bool(details.get("patch_artifact_pending")):
                patch_artifact = True
            if self._tool_message_changed_file(message, details, action_type):
                file_changed = True
                saw_file_change_before_inspect = True
                path = str(details.get("path") or details.get("absolute_path") or "").strip()
                if not path:
                    changed = details.get("changed_paths")
                    if isinstance(changed, list) and changed:
                        for changed_path in changed:
                            value = str(changed_path).strip()
                            if value and value not in file_changed_paths:
                                file_changed_paths.append(value)
                        path = ""
                if path and path not in file_changed_paths:
                    file_changed_paths.append(path)
            if action_type == "run_shell":
                command = str(details.get("command") or "").strip()
                if is_error:
                    command_failed = True
                    if self._looks_like_verification_command(command):
                        verification_failed = True
                elif self._looks_like_verification_command(command):
                    verification_passed = True
            if action_type in {"edit_file", "apply_patch_artifact"} and is_error:
                patch_failed = True
            if saw_file_change_before_inspect and not is_error and tool_name in {"read_file", "git_diff_worktree", "git_status", "grep_code", "search_text"}:
                verification_passed = True
            if is_error:
                trailing_failures += 1
                consecutive_failures = max(consecutive_failures, trailing_failures)
            else:
                trailing_failures = 0
        return {
            "file_changed": file_changed,
            "file_changed_paths": file_changed_paths,
            "changed_file_count": len(file_changed_paths),
            "command_failed": command_failed,
            "verification_passed": verification_passed,
            "verification_failed": verification_failed,
            "patch_failed": patch_failed,
            "patch_artifact": patch_artifact,
            "consecutive_failures": consecutive_failures,
        }

    @staticmethod
    def _tool_message_changed_file(message: ChatMessage, details: dict[str, object], action_type: str) -> bool:
        if bool(details.get("persisted")) and action_type in {"write_file", "edit_file"}:
            return True
        if bool(details.get("external_approval_result")):
            return (
                str(details.get("approval_status") or "") == "approved"
                and action_type in {"write_file", "edit_file", "apply_patch_artifact"}
            )
        return bool(details.get("patch_artifact_pending")) and action_type in {"write_file", "edit_file"}

    @staticmethod
    def _looks_like_verification_command(command: str) -> bool:
        lowered = command.lower()
        markers = (
            "pytest",
            "unittest",
            "npm test",
            "pnpm test",
            "yarn test",
            "cargo test",
            "go test",
            "mvn test",
            "gradle test",
            "ruff",
            "mypy",
            "tsc",
            "eslint",
            "vitest",
            "jest",
            "doctor",
            "report",
            "git diff",
            "git status",
        )
        return any(marker in lowered for marker in markers)

    @staticmethod
    def _assistant_declares_verification_blocker(text: str) -> bool:
        lowered = text.lower()
        return any(
            marker in lowered
            for marker in (
                "cannot verify",
                "could not verify",
                "unable to verify",
                "verification blocker",
                "blocked from verifying",
                "无法验证",
                "不能验证",
                "验证受阻",
                "阻塞",
            )
        )

    def _default_before_tool_call(self, state: AgentState, call: ToolCall, registry: ToolRegistry) -> BeforeToolCallDecision:
        """Agent 工具执行前的「最终安全校验钩子」"""
        child_runtime = self._is_subagent_runtime()
        explicit_subagent = None if child_runtime else self._explicit_subagent_request(state)
        subagent_handoff_done = self._has_subagent_result_since_latest_user(state)
        orchestrated_edit = None if child_runtime else self._explicit_orchestrated_edit_request(state)
        if (
            orchestrated_edit is not None
            and self.enforce_orchestrated_edit_contract
            and not getattr(self, "subagent_profile", None)
            and call.name in {"edit_file", "write_file", "run_shell"}
        ):
            patch_ready = self._has_patch_artifact_orchestration_since_latest_user(state)
            if self.require_patch_artifact_for_code_change or not patch_ready:
                message = (
                    "This turn is under an orchestrated edit contract. The main agent may not use "
                    f"{call.name} as a fallback. Use orchestrate_agents with workflow=code_change and "
                    "allow_edits=true; if no apply_patch_artifact is produced, report the orchestration failure."
                )
                return BeforeToolCallDecision(
                    action="reject",
                    message=message,
                    details={
                        "policy_action": "reject",
                        "permission_domain": "edit",
                        "policy_reason": message,
                        "orchestrated_edit_contract": True,
                    },
                )
        if explicit_subagent is not None and not subagent_handoff_done and call.name != "spawn_subagent":
            message = "This request explicitly asked for `@subagent`, so the main agent must hand off via `spawn_subagent` before using other tools."
            return BeforeToolCallDecision(
                action="reject",
                message=message,
                details={"policy_action": "reject", "permission_domain": "read", "policy_reason": message},
            )
        if call.name == "spawn_subagent" and explicit_subagent is None:
            message = "Subagent calls require explicit user intent. Ask the user to include `@subagent` followed by the task."
            return BeforeToolCallDecision(
                action="reject",
                message=message,
                details={"policy_action": "reject", "permission_domain": "read", "policy_reason": message},
            )
        spec = registry.get_spec(call.name)
        decision = registry.evaluate_call(call.name, call.arguments)
        metadata = registry.metadata().get(call.name)
        if decision.action == "deny":
            return BeforeToolCallDecision(
                action="reject",
                message=decision.reason,
                details={"policy_action": decision.action, "permission_domain": decision.permission_domain, "policy_reason": decision.reason, **(decision.details or {})},
            )
        if decision.action == "ask" and not self._approved_pending_plan:
            if (
                metadata is not None
                and metadata.tool_family in {"extension", "mcp"}
                and metadata.exact_effect_mode == "required"
            ):
                return BeforeToolCallDecision(
                    action="allow",
                    message=decision.reason,
                    details={
                        "policy_action": decision.action,
                        "permission_domain": decision.permission_domain,
                        "policy_reason": decision.reason,
                        "approval_expected": True,
                        **(decision.details or {}),
                    },
                )
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
        if _call.name == "spawn_subagent" and getattr(_result, "is_error", False):
            return AfterToolCallDecision(
                continue_loop=False,
                details={
                    "subagent_failure": True,
                    "failure_kind": _result.details.get("failure_kind"),
                    "next_action_hint": "Explain the subagent failure and recommend retrying or switching to direct execution.",
                },
            )
        result_details = getattr(_result, "details", {}) or {}
        if bool(result_details.get("staged")) or bool(result_details.get("patch_artifact_pending")):
            return AfterToolCallDecision(
                continue_loop=False,
                details={
                    "approval_pending": True,
                    "approval_token": result_details.get("token"),
                    "next_action_hint": "Stop the turn and wait for host approval before continuing.",
                },
            )
        if bool(result_details.get("approval_unavailable")):
            return AfterToolCallDecision(
                continue_loop=False,
                details={
                    "approval_unavailable": True,
                    "next_action_hint": "Stop the turn and report that the requested tool cannot be represented for safe approval.",
                },
            )
        if _call.name in WEB_TOOL_NAMES:
            web_failure = bool(getattr(_result, "is_error", False))
            if _call.name in {"web.search", "web.news", "web.github_trending"}:
                web_failure = web_failure or int(result_details.get("result_count") or 0) <= 0
            elif _call.name == "web.fetch":
                web_failure = web_failure or not str(result_details.get("text") or "").strip()
            if web_failure:
                attempts = self._web_lookup_attempts_since(_state, start=0 if self._latest_user_index(_state) is None else self._latest_user_index(_state) + 1)
                if attempts["count"] >= WEB_LOOKUP_ATTEMPT_LIMIT or attempts["terminal"]:
                    return AfterToolCallDecision(
                        continue_loop=False,
                        details={
                            "web_lookup_terminal": True,
                            "attempt_count": attempts["count"],
                            "next_action_hint": "Summarize the best available web findings or state the blocker; do not keep retrying the same search/fetch path.",
                        },
                    )
        return AfterToolCallDecision(continue_loop=True)

    def _default_tool_error_hook(self, _state: AgentState, _call: ToolCall, _error: Exception) -> ToolErrorDecision:
        """Keep recoverable coding-tool failures in the loop so the model can inspect, fix, and rerun."""
        if _call.name in {"write_file", "edit_file", "run_shell", "git_diff_worktree"}:
            if "host-side approval" in str(_error).lower():
                return ToolErrorDecision(
                    continue_loop=False,
                    details={
                        "recoverable_tool_error": False,
                        "next_action_hint": "Stop and wait for explicit host approval before retrying this tool call.",
                    },
                )
            return ToolErrorDecision(
                continue_loop=True,
                details={
                    "recoverable_tool_error": True,
                    "next_action_hint": "Inspect the visible error output, fix the cause, and rerun the smallest relevant check before finalizing.",
                },
            )
        return ToolErrorDecision(continue_loop=False)

    def _begin_run(self, reason: str) -> str:
        self._run_sequence += 1
        self._current_run_id = f"{self.session_id}:run:{self._run_sequence}:{uuid.uuid4().hex[:8]}"
        self._activity_starts.clear()
        return self._current_run_id

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
        return self._enrich_activity_event(AgentEvent(type=event_type, **kwargs))

    def _enrich_activity_event(self, event: AgentEvent) -> AgentEvent:
        if not event.event_id:
            self._event_sequence += 1
            event.event_id = f"{self.session_id}:{self._event_sequence}"
        if not event.run_id:
            event.run_id = self._current_run_id or f"{self.session_id}:run:0"
        if event.status is None:
            event.status = self._event_status(event)
        if not event.activity_id:
            event.activity_id = self._event_activity_id(event)
        if event.started_at is None and event.status in {"pending", "running"}:
            event.started_at = event.timestamp
        if event.activity_id:
            if event.status in {"pending", "running"}:
                self._activity_starts.setdefault(event.activity_id, event.started_at or event.timestamp)
            started = self._activity_starts.get(event.activity_id)
            if started is not None:
                event.started_at = event.started_at or started
            if event.status in {"success", "warning", "error", "cancelled"}:
                event.ended_at = event.ended_at or event.timestamp
                if event.started_at is not None:
                    event.duration_ms = max(int((event.ended_at - event.started_at) * 1000), 0)
        event.details = self._event_details_with_activity(event)
        return event

    def _event_status(self, event: AgentEvent) -> str:
        if event.is_error:
            return "cancelled" if event.details.get("failure_kind") == "canceled" else "error"
        if event.type.endswith("_start") or event.type in {
            TURN_START,
            TURN_PHASE_CHANGED,
            TURN_STATE,
            BEFORE_PROVIDER_REQUEST,
            TOOL_CALL,
            TOOL_START,
            REASONING_START,
            REASONING_DELTA,
        }:
            return "running"
        if event.type.endswith("_pending") or event.type in {PLANNER_GATE_PENDING}:
            return "pending"
        if event.type.endswith("_rejected"):
            return "warning"
        if event.type in {ERROR, TOOL_ERROR, PROVIDER_ERROR, CHECKPOINT_RESTORE_FAILED}:
            return "error"
        return "success"

    def _event_activity_id(self, event: AgentEvent) -> str:
        details = event.details or {}
        if event.type.startswith("reasoning_") or event.type in {BEFORE_PROVIDER_REQUEST, PROVIDER_RESPONSE, PROVIDER_ERROR}:
            return f"{event.run_id}:reasoning:{event.turn_id}"
        if event.type.startswith("planner_"):
            token = details.get("token")
            suffix = token if isinstance(token, str) and token else event.turn_id
            return f"{event.run_id}:planner:{suffix}"
        if event.type.startswith("tool_"):
            call_id = details.get("tool_call_id")
            suffix = call_id if isinstance(call_id, str) and call_id else event.tool_name or event.turn_id
            return f"{event.run_id}:tool:{suffix}"
        if event.type.startswith("subagent_"):
            child = details.get("child_session_id") or details.get("session_id") or details.get("spec_name")
            suffix = child if isinstance(child, str) and child else event.turn_id
            return f"{event.run_id}:subagent:{suffix}"
        if event.type.startswith("checkpoint_") or event.type.startswith("session_safe_rewind") or event.type == SESSION_SAFE_REWIND_COMPLETED:
            checkpoint = details.get("checkpoint_id") or details.get("id") or details.get("token")
            suffix = checkpoint if isinstance(checkpoint, str) and checkpoint else event.turn_id
            return f"{event.run_id}:checkpoint:{suffix}"
        if event.type.startswith("queue_") or event.type in {ERROR, COMPACTION, SESSION_COMPACTED, "cancel_requested"}:
            return f"{event.run_id}:system:{event.type}:{event.turn_id}"
        return f"{event.run_id}:event:{event.type}:{event.turn_id}"

    def _event_details_with_activity(self, event: AgentEvent) -> dict[str, object]:
        details: dict[str, object] = dict(event.details or {})
        activity = dict(details.get("activity") or {}) if isinstance(details.get("activity"), dict) else {}
        activity.update(
            {
                "event_id": event.event_id,
                "run_id": event.run_id,
                "activity_id": event.activity_id,
                "parent_activity_id": event.parent_activity_id,
                "status": event.status,
                "started_at": event.started_at,
                "ended_at": event.ended_at,
                "duration_ms": event.duration_ms,
                "phase": self._activity_phase(event),
            }
        )
        details["activity"] = {key: value for key, value in activity.items() if value is not None}
        trace = dict(details.get("trace") or {}) if isinstance(details.get("trace"), dict) else {}
        trace.update({"event_id": event.event_id, "run_id": event.run_id})
        details["trace"] = trace
        return details

    def _activity_phase(self, event: AgentEvent) -> str:
        if event.type.startswith("reasoning_") or event.type in {BEFORE_PROVIDER_REQUEST, PROVIDER_RESPONSE, PROVIDER_ERROR}:
            return "reasoning"
        if event.type.startswith("planner_"):
            return "approval" if "gate" in event.type else "planning"
        if event.type.startswith("tool_"):
            return "tool"
        if event.type.startswith("subagent_"):
            return "subagent"
        if event.type.startswith("checkpoint_") or event.type.startswith("session_safe_rewind"):
            return "checkpoint"
        if event.type == COMPACTION or event.type.startswith("learning_"):
            return "memory"
        return "system"

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
        if hasattr(self, "observability"):
            self.lifecycle.subscribe(self._observe_runtime_event)

    def _attach_runtime_context_to_tool_registry(self) -> None:
        set_emitter = getattr(self.tool_registry, "set_runtime_event_emitter", None)
        if callable(set_emitter):
            set_emitter(lambda event: list(self._emit(event)))
        set_token = getattr(self.tool_registry, "set_cancellation_token", None)
        if callable(set_token):
            set_token(self._cancellation_token)
        set_observability = getattr(self.tool_registry, "set_observability", None)
        if callable(set_observability) and hasattr(self, "observability"):
            set_observability(self.observability)

    def _refresh_config_for_turn(self) -> Iterator[AgentEvent]:
        manager = self.config_manager
        if manager is None or not hasattr(manager, "get_effective_snapshot"):
            return
        snapshot = manager.get_effective_snapshot(session_id=self.session_id)
        previous_version = self.config_version
        self.config_snapshot = snapshot
        self.config_version = getattr(snapshot, "config_version", None)
        settings = getattr(snapshot, "settings", None)
        if settings is not None:
            model_name = getattr(getattr(settings, "model", None), "model", None)
            if model_name and getattr(self.llm_client.model, "model", None) != model_name:
                try:
                    from pp_agent.llm.models import ModelConfig, ProviderConfig
                    from pp_agent.llm.registry import create_llm_client

                    self.llm_client = create_llm_client(
                        provider=ProviderConfig(**settings.provider.model_dump(mode="python")),
                        model=ModelConfig(**settings.model.model_dump(mode="python")),
                    )
                    self.state.model = self.llm_client.model.model_copy(deep=True)
                    refresh_learning_client = getattr(self.learning_runtime, "refresh_llm_client", None)
                    if callable(refresh_learning_client):
                        refresh_learning_client(self.llm_client, settings=settings.learning)
                except Exception as exc:  # noqa: BLE001
                    yield from self._emit(
                        self._event(
                            ERROR,
                            message=f"Failed to refresh model configuration: {exc}",
                            is_error=True,
                            details={"source": "config_refresh"},
                        )
                    )
            self.require_plan_approval = bool(settings.tool_policy.confirm_high_risk_plan)
            self.enforce_orchestrated_edit_contract = bool(settings.subagents.enforce_orchestrated_edit_contract)
            self.require_patch_artifact_for_code_change = bool(settings.subagents.require_patch_artifact_for_code_change)
        reload_policy = str(getattr(snapshot, "reload_policy", "hot"))
        changed = previous_version is not None and previous_version != self.config_version
        if changed and reload_policy in {"rebuild_runtime", "restart_required"} and self._config_refresh_callback is not None:
            self._config_refresh_callback(self, snapshot)
            self._attach_runtime_context_to_tool_registry()
        if changed:
            yield from self._emit(
                self._event(
                    "config_reloaded",
                    message=f"Applied config snapshot {self.config_version}",
                    details={
                        "config_version": self.config_version,
                        "config_hash": getattr(snapshot, "config_hash", None),
                        "reload_policy": reload_policy,
                    },
                )
            )

    def _provider_name(self) -> str:
        provider = getattr(self.llm_client, "provider", None)
        if provider is None:
            return "unknown"
        return getattr(provider, "name", "unknown")


AgentSession = AgentRuntime
