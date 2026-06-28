from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

from pp_agent.context.item import ContextItem
from pp_agent.context.source_ref import SourceRef
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.llm import ModelConfig
from pp_agent.observability.recorder import TraceRecorder
from pp_agent.observability.store import TraceStore
from pp_agent.runtime.hooks import RuntimeHooks
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.sessions import SessionStore
from pp_agent.storage.settings import ToolPolicyConfig
from pp_agent.tools.base import ToolExecutionResult
from pp_agent.tools.registry import ToolRegistry

from tests.integrations.test_qqbot_runtime_boundary import BotLLMClient, _adapter, _c2c


class CrossSystemLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()
        self.seen_messages: list[list[ChatMessage]] = []
        self.calls = 0

    def stream_chat(self, messages, tools=None) -> Iterator[dict]:
        self.calls += 1
        self.seen_messages.append(list(messages))
        if self.calls == 1:
            yield {
                "text": "",
                "tool_calls": [
                    {
                        "id": "call-cross-tool",
                        "name": "cross_context_tool",
                        "arguments_chunk": '{"query":"context"}',
                    }
                ],
                "finish_reason": "tool_calls",
                "raw": {},
            }
            return
        yield {"text": "cross-system-ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class FinalOnlyLLMClient:
    def __init__(self, text: str = "final-ok") -> None:
        self.model = ModelConfig()
        self.text = text
        self.seen_messages: list[list[ChatMessage]] = []

    def stream_chat(self, messages, tools=None) -> Iterator[dict]:
        self.seen_messages.append(list(messages))
        yield {"text": self.text, "tool_calls": [], "finish_reason": "stop", "raw": {}}


class ApprovalWriteLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()
        self.seen_messages: list[list[ChatMessage]] = []
        self.calls = 0

    def stream_chat(self, messages, tools=None) -> Iterator[dict]:
        self.calls += 1
        self.seen_messages.append(list(messages))
        if self.calls > 1:
            yield {"text": "approval-followup-ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}
            return
        yield {
            "text": "",
            "tool_calls": [
                {
                    "id": "call-approval-write",
                    "name": "write_file",
                    "arguments_chunk": '{"path":"approval.txt","content":"approved"}',
                }
            ],
            "finish_reason": "tool_calls",
            "raw": {},
        }


def _text(message: ChatMessage) -> str:
    return "\n".join(part.text for part in message.content if isinstance(part, TextPart))


def _memory_hook(_state, messages: list[ChatMessage]) -> list[ChatMessage]:
    return [
        *messages[:1],
        ChatMessage(
            role="system",
            content=[TextPart(text="Cross memory recall: project semaphore")],
            metadata={
                "context_section": "episodic_recall",
                "context_item_id": "memory:cross",
                "source_type": "episodic_memory",
                "source_id": "memory:cross",
            },
            timestamp=0.0,
        ),
        *messages[1:],
    ]


def _raw_runtime_injection_hook(_state, messages: list[ChatMessage]) -> list[ChatMessage]:
    return [
        *messages[:1],
        ChatMessage(
            role="system",
            content=[TextPart(text="Raw runtime injection without context metadata")],
            timestamp=0.0,
        ),
        *messages[1:],
    ]


def _agent(tmp_path: Path) -> tuple[AgentRuntime, CrossSystemLLMClient, TraceStore]:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    trace_store = TraceStore(tmp_path)
    recorder = TraceRecorder(trace_store, workspace=tmp_path)
    registry = ToolRegistry(tmp_path, policy=ToolPolicyConfig(permission_mode="workspace-write"), observability=recorder)
    registry.register_function_tool(
        name="cross_context_tool",
        description="Return a governed ContextItem-like tool result.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        executor=lambda _workspace, _arguments: ToolExecutionResult(
            tool_call_id="",
            tool_name="cross_context_tool",
            content="Tool response entered the conversation pipeline",
            details={
                "context_items": [
                    ContextItem(
                        id="tool-result:cross",
                        type="project_context",
                        title="Cross Tool Result",
                        content="Tool response entered the conversation pipeline",
                        source_ref=SourceRef(source_type="tool", source_id="cross_context_tool"),
                        metadata={"context_section": "project_context"},
                    ).model_dump(mode="json")
                ],
            },
        ),
        permission_domain="read",
        tool_family="extension",
        exact_effect_mode="auto",
        non_side_effectful=True,
        known_safe_inspect=True,
    )
    llm = CrossSystemLLMClient()
    runtime = AgentRuntime(
        llm_client=llm,
        tool_registry=registry,
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        runtime_hooks=RuntimeHooks(transform_context=[_memory_hook]),
        require_plan_approval=False,
        observability=recorder,
    )
    runtime.restore_session_record(record)
    runtime.config_snapshot.settings.context_pipeline.context_pipeline_mode = "on"
    runtime.context_pipeline_mode = "on"
    return runtime, llm, trace_store


def _runtime_with_llm(
    tmp_path: Path,
    llm,
    *,
    mode: str = "on",
    require_plan_approval: bool = False,
    policy: ToolPolicyConfig | None = None,
) -> tuple[AgentRuntime, TraceStore]:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    trace_store = TraceStore(tmp_path)
    recorder = TraceRecorder(trace_store, workspace=tmp_path)
    runtime = AgentRuntime(
        llm_client=llm,
        tool_registry=ToolRegistry(tmp_path, policy=policy, observability=recorder),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        runtime_hooks=RuntimeHooks(transform_context=[_memory_hook]),
        require_plan_approval=require_plan_approval,
        observability=recorder,
    )
    runtime.restore_session_record(record)
    runtime.config_snapshot.settings.context_pipeline.context_pipeline_mode = mode
    runtime.context_pipeline_mode = mode
    return runtime, trace_store


def _latest_detail(trace_store: TraceStore, session_id: str):
    latest = trace_store.find_latest_run(session_id=session_id)
    assert latest is not None
    return latest, trace_store.read_run(latest.run_id)


def _context_events(detail) -> list:
    return [event for event in detail.events if event.name == "context_built"]


def _final_spans(detail) -> list:
    return [span for span in detail.spans if span.name == "final.answer"]


def _provider_events(detail) -> list:
    return [event for event in detail.events if event.name == "provider_response"]


def test_final_messages_have_single_semantic_source_per_run(tmp_path: Path) -> None:
    pipeline_llm = FinalOnlyLLMClient("pipeline-final")
    pipeline_runtime, pipeline_store = _runtime_with_llm(tmp_path / "pipeline", pipeline_llm, mode="on")

    pipeline_runtime.prompt("answer through pipeline")
    _pipeline_run, pipeline_detail = _latest_detail(pipeline_store, pipeline_runtime.session_id)
    pipeline_context = _context_events(pipeline_detail)
    pipeline_final = _final_spans(pipeline_detail)
    pipeline_provider = _provider_events(pipeline_detail)

    assert len(pipeline_context) == 1
    assert len(pipeline_final) == 1
    assert len(pipeline_provider) == 1
    assert pipeline_context[0].payload["details"]["pipeline_used"] is True
    assert pipeline_context[0].payload["details"]["context_source"] == "context_pipeline"
    assert pipeline_provider[0].payload["details"]["context_source"] == "context_pipeline"
    assert pipeline_final[0].attributes["context_source"] == "context_pipeline"
    assert pipeline_final[0].attributes["pipeline_used"] is True
    assert all(message.metadata.get("context_section") for message in pipeline_llm.seen_messages[0])

    legacy_llm = FinalOnlyLLMClient("legacy-final")
    legacy_runtime, legacy_store = _runtime_with_llm(tmp_path / "legacy", legacy_llm, mode="off")

    legacy_runtime.prompt("answer through legacy")
    _legacy_run, legacy_detail = _latest_detail(legacy_store, legacy_runtime.session_id)
    legacy_context = _context_events(legacy_detail)
    legacy_final = _final_spans(legacy_detail)
    legacy_provider = _provider_events(legacy_detail)

    assert len(legacy_context) == 1
    assert len(legacy_final) == 1
    assert len(legacy_provider) == 1
    assert legacy_context[0].payload["details"]["pipeline_used"] is False
    assert legacy_context[0].payload["details"]["context_source"] == "legacy"
    assert legacy_context[0].payload["details"]["fallback_reason"] == "mode_off"
    assert legacy_provider[0].payload["details"]["context_source"] == "legacy"
    assert legacy_final[0].attributes["context_source"] == "legacy"
    assert legacy_final[0].attributes["pipeline_used"] is False
    assert any(not message.metadata.get("context_section") for message in legacy_llm.seen_messages[0])


def test_runtime_raw_injection_is_normalized_before_provider_prompt(tmp_path: Path) -> None:
    llm = FinalOnlyLLMClient()
    runtime, trace_store = _runtime_with_llm(tmp_path, llm, mode="on")
    runtime.runtime_hooks.add_transform_context_hook("raw_runtime_injection", "runtime", _raw_runtime_injection_hook)

    runtime.prompt("normalize runtime injection")
    _run, detail = _latest_detail(trace_store, runtime.session_id)
    rendered_messages = llm.seen_messages[0]
    raw_injection = [message for message in rendered_messages if "Raw runtime injection" in _text(message)]

    assert raw_injection
    assert all(message.metadata.get("context_section") == "project_context" for message in raw_injection)
    assert all(message.metadata.get("context_item_id") for message in raw_injection)
    assert all(message.metadata.get("source_ref") for message in raw_injection)
    context_span = next(span for span in detail.spans if span.name == "context.build")
    source_refs = context_span.output["context"]["source_refs"]
    assert any(ref["source_type"] in {"conversation", "project_map"} for ref in source_refs)


def test_runtime_context_tool_memory_and_trace_share_one_execution_graph(tmp_path: Path) -> None:
    runtime, llm, trace_store = _agent(tmp_path)

    events = runtime.prompt("audit the governed graph")
    tool_run = trace_store.find_latest_run(session_id=runtime.session_id)
    assert tool_run is not None
    tool_detail = trace_store.read_run(tool_run.run_id)
    context_event = next(event for event in events if event.type == "context_built" and event.details.get("pipeline_used") is True)
    provider_event = next(event for event in events if event.type == "before_provider_request")
    tool_event = next(event for event in events if event.type == "tool_end" and event.tool_name == "cross_context_tool")
    response_event = next(event for event in events if event.type == "provider_response" and event.details.get("tool_count") == 1)

    first_messages = llm.seen_messages[0]
    assert all(message.metadata.get("context_section") for message in first_messages)
    assert any(message.metadata.get("context_section") == "episodic_recall" for message in first_messages)
    assert "Cross memory recall" in "\n".join(_text(message) for message in first_messages)

    assert context_event.details["pipeline_message_count"] == context_event.details["rendered_message_count"]
    assert context_event.details["pipeline_used"] is True
    assert context_event.details["legacy_message_count"] != context_event.details["pipeline_message_count"]

    run_ids = {event.run_id for event in (context_event, provider_event, tool_event, response_event)}
    assert run_ids == {tool_run.run_id}
    assert {span.run_id for span in tool_detail.spans} == {tool_run.run_id}
    assert {event.run_id for event in tool_detail.events} == {tool_run.run_id}

    context_span = next(span for span in tool_detail.spans if span.name == "context.build")
    memory_span = next(span for span in tool_detail.spans if span.name == "memory.recall")
    tool_spans = [span for span in tool_detail.spans if span.name == "tool.call" and span.attributes.get("tool_call_id") == "call-cross-tool"]
    policy_span = next(span for span in tool_detail.spans if span.name == "policy.decision")

    assert context_span.attributes["context_used"] <= context_span.attributes["context_total_budget"]
    assert "returned_count" in memory_span.output
    assert any(ref["source_type"] == "episodic_memory" for ref in context_span.output["context"]["source_refs"])
    assert {span.attributes.get("source") for span in tool_spans} == {"runtime_lifecycle_event", "tool_registry_middleware"}
    assert policy_span.attributes["policy_action"] == "allow"

    response_events = runtime.continue_()
    response_run = trace_store.find_latest_run(session_id=runtime.session_id)
    assert response_run is not None and response_run.run_id != tool_run.run_id
    response_detail = trace_store.read_run(response_run.run_id)
    final_response = next(event for event in response_events if event.type == "provider_response" and event.details.get("tool_count") == 0)
    second_messages = llm.seen_messages[1]
    assert any(
        message.role == "tool"
        and message.tool_call_id == "call-cross-tool"
        and message.metadata.get("context_section") == "conversation"
        for message in second_messages
    )
    assert final_response.run_id == response_run.run_id
    final_span = next(span for span in response_detail.spans if span.name == "final.answer")
    assert final_span.attributes["source"] == "provider_response"


def test_context_budget_report_covers_memory_capability_tool_and_response_inputs(tmp_path: Path) -> None:
    runtime, llm, trace_store = _agent(tmp_path)

    runtime.prompt("audit budget controller")
    runtime.continue_()
    _run, detail = _latest_detail(trace_store, runtime.session_id)
    context_span = next(span for span in detail.spans if span.name == "context.build")
    context = context_span.output["context"]
    budget_report = context["budget_report"]
    sections = context["sections"]
    per_section = budget_report["per_section"]
    included_sections = {item["section"] for item in budget_report["included_items"]}

    assert context_span.attributes["context_used"] == budget_report["used"]
    assert context_span.attributes["context_total_budget"] == budget_report["total_budget"]
    assert budget_report["used"] <= budget_report["total_budget"]
    assert {"episodic_recall", "conversation"}.issubset(included_sections)
    assert sections["episodic_recall"]["count"] >= 1
    assert sections["conversation"]["count"] >= 1
    assert per_section["episodic_recall"]["used"] > 0
    assert per_section["conversation"]["used"] > 0
    assert "capabilities" in per_section
    assert any(message.role == "tool" and message.tool_call_id == "call-cross-tool" for message in llm.seen_messages[-1])


def test_approval_resume_preserves_policy_trace_and_parent_run_link(tmp_path: Path) -> None:
    llm = ApprovalWriteLLMClient()
    runtime, trace_store = _runtime_with_llm(tmp_path, llm, mode="on", require_plan_approval=True)

    pending_events = runtime.prompt("write through approval")
    pending_run, pending_detail = _latest_detail(trace_store, runtime.session_id)
    token = runtime.state.pending_plan_token
    assert token is not None
    pending_payload = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").load(token)

    assert pending_payload["details"]["run_id"] == pending_run.run_id
    assert pending_payload["origin"]["run_id"] == pending_run.run_id
    assert len(_final_spans(pending_detail)) == 0
    assert any(event.type == "planner_gate_pending" and event.run_id == pending_run.run_id for event in pending_events)
    approval_span = next(span for span in pending_detail.spans if span.name == "approval.decision")
    assert approval_span.status == "pending"
    assert approval_span.attributes["approval_token"] == token

    approved_events = runtime.approve_pending_plan(token)
    approval_run, approval_detail = _latest_detail(trace_store, runtime.session_id)
    assert approval_run.run_id != pending_run.run_id
    assert approval_detail.run is not None
    assert approval_detail.run.attributes["entrypoint"] == "approval"
    assert approval_detail.run.attributes["parent_run_id"] == pending_run.run_id
    assert approval_detail.run.attributes["approval_token"] == token
    assert any(event.type == "planner_gate_approved" and event.run_id == approval_run.run_id for event in approved_events)
    policy_span = next(span for span in approval_detail.spans if span.name == "policy.decision")
    assert policy_span.attributes["policy_action"] == "ask"
    assert policy_span.attributes["permission_domain"] == "edit"
    tool_spans = [span for span in approval_detail.spans if span.name == "tool.call" and span.attributes.get("tool_call_id") == "call-approval-write"]
    assert {span.attributes.get("source") for span in tool_spans} == {"runtime_lifecycle_event", "tool_registry_middleware"}
    assert any(span.status == "pending" for span in tool_spans)
    assert not (tmp_path / "approval.txt").exists()


def test_unsafe_tool_cannot_execute_through_runtime_without_policy_trace(tmp_path: Path) -> None:
    llm = ApprovalWriteLLMClient()
    runtime, trace_store = _runtime_with_llm(
        tmp_path,
        llm,
        mode="on",
        require_plan_approval=False,
        policy=ToolPolicyConfig(permission_mode="read-only"),
    )

    events = runtime.prompt("try unsafe write")
    run, detail = _latest_detail(trace_store, runtime.session_id)
    tool_message = next(message for message in runtime.state.messages if message.role == "tool" and message.tool_call_id == "call-approval-write")

    assert not (tmp_path / "approval.txt").exists()
    assert tool_message.metadata["is_error"] is True
    assert "read-only" in _text(tool_message).lower()
    assert any(event.type == "tool_error" and event.run_id == run.run_id for event in events)
    assert any(span.name == "policy.decision" and span.status == "blocked" for span in detail.spans)
    tool_spans = [span for span in detail.spans if span.name == "tool.call" and span.attributes.get("tool_call_id") == "call-approval-write"]
    assert tool_spans
    assert all(span.status == "error" for span in tool_spans)
    assert all(span.run_id == run.run_id for span in tool_spans)


def test_bot_trace_points_to_runtime_trace_run_for_execution_graph(tmp_path: Path) -> None:
    llm = BotLLMClient(tool_name="list_files", arguments='{"path":"."}')
    adapter, _client, session_manager, manager = _adapter(tmp_path, llm)

    asyncio.run(adapter.handle_payload(_c2c()))

    run = manager.event_store.list_runs("qq", "qq-main")[0]
    bot_trace = manager.event_store.list_traces("qq", "qq-main")[0]
    runtime_store = TraceStore(tmp_path / ".pp-agent" / "traces")
    runtime_run = runtime_store.find_latest_run(session_id=run["session_id"])

    assert runtime_run is not None
    assert bot_trace["run_id"] == run["run_id"]
    assert bot_trace["runtime_trace_run_id"] == runtime_run.run_id
    assert bot_trace["parent_id"] == runtime_run.run_id
    assert bot_trace["session_id"] == session_manager.list_active()[0]["session_id"]
    runtime_detail = runtime_store.read_run(runtime_run.run_id)
    assert any(span.name == "context.build" for span in runtime_detail.spans)
    assert any(span.name == "tool.call" and span.attributes.get("tool_name") == "list_files" for span in runtime_detail.spans)
    assert json.dumps(bot_trace, ensure_ascii=False).count(runtime_run.run_id) >= 2
