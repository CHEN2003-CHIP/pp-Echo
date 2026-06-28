from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.llm import ModelConfig
from pp_agent.observability.recorder import TraceRecorder
from pp_agent.observability.store import TraceStore
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.sessions import SessionStore
from pp_agent.storage.settings import ToolPolicyConfig
from pp_agent.tools.registry import ToolRegistry


class ScriptedToolLLMClient:
    def __init__(self, calls: list[dict[str, object]]) -> None:
        self.model = ModelConfig()
        self.calls = list(calls)
        self.seen_messages: list[list[ChatMessage]] = []

    def stream_chat(self, messages, tools=None) -> Iterator[dict]:
        self.seen_messages.append(list(messages))
        if self.calls:
            yield self.calls.pop(0)
            return
        yield {"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def _tool_event(tool_call: dict[str, object]) -> dict[str, object]:
    return {"text": "", "tool_calls": [tool_call], "finish_reason": "tool_calls", "raw": {}}


def _agent(
    tmp_path: Path,
    llm: ScriptedToolLLMClient,
    *,
    policy: ToolPolicyConfig | None = None,
    require_plan_approval: bool = False,
) -> tuple[AgentRuntime, TraceRecorder, TraceStore]:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    trace_store = TraceStore(tmp_path / "traces")
    recorder = TraceRecorder(trace_store, workspace=tmp_path)
    registry = ToolRegistry(tmp_path, policy=policy, observability=recorder)
    runtime = AgentRuntime(
        llm_client=llm,
        tool_registry=registry,
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        require_plan_approval=require_plan_approval,
        observability=recorder,
    )
    runtime.restore_session_record(record)
    return runtime, recorder, trace_store


def _latest_run_spans(recorder: TraceRecorder, trace_store: TraceStore):
    run_id = recorder.current_run_id
    assert run_id is None
    latest = trace_store.find_latest_run()
    assert latest is not None
    return trace_store.read_run(latest.run_id).spans


def _tool_messages(runtime: AgentRuntime) -> list[ChatMessage]:
    return [message for message in runtime.state.messages if message.role == "tool"]


def test_low_risk_tool_call_has_unified_trace_and_observation(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello trace", encoding="utf-8")
    llm = ScriptedToolLLMClient([
        _tool_event({"id": "call-read", "name": "read_file", "arguments_chunk": '{"path":"notes.txt"}'})
    ])
    runtime, recorder, trace_store = _agent(tmp_path, llm)

    runtime.prompt("read notes")
    spans = _latest_run_spans(recorder, trace_store)
    middleware = next(span for span in spans if span.name == "tool.call" and span.attributes.get("source") == "tool_registry_middleware")

    assert middleware.attributes["tool_name"] == "read_file"
    assert middleware.attributes["tool_call_id"] == "call-read"
    assert middleware.attributes["tool_origin"] == "file"
    assert middleware.attributes["tool_family"] == "file"
    assert middleware.attributes["tool_category"] == "files"
    assert middleware.input["arguments"] == {"path": "notes.txt"}
    assert middleware.output["content_preview"] == "hello trace"
    assert middleware.output["is_error"] is False
    assert middleware.duration_ms is not None
    assert _tool_messages(runtime)[0].tool_call_id == "call-read"
    assert _tool_messages(runtime)[0].metadata["tool_details"]["trace_tool_call_id"] == "call-read"


def test_tool_failure_returns_error_observation_without_runtime_crash(tmp_path: Path) -> None:
    llm = ScriptedToolLLMClient([
        _tool_event({"id": "call-missing-file", "name": "read_file", "arguments_chunk": '{"path":"missing.txt"}'})
    ])
    runtime, recorder, trace_store = _agent(tmp_path, llm)

    events = runtime.prompt("read missing")
    spans = _latest_run_spans(recorder, trace_store)
    tool_message = _tool_messages(runtime)[0]
    middleware = next(span for span in spans if span.name == "tool.call" and span.attributes.get("tool_call_id") == "call-missing-file" and span.attributes.get("source") == "tool_registry_middleware")

    assert any(event.type == "tool_error" for event in events)
    assert tool_message.metadata["is_error"] is True
    assert "missing.txt" in tool_message.content[0].text
    assert middleware.status == "error"
    assert middleware.error_message


def test_unregistered_tool_call_becomes_understandable_observation(tmp_path: Path) -> None:
    llm = ScriptedToolLLMClient([
        _tool_event({"id": "call-unknown", "name": "not_registered", "arguments_chunk": '{"x":1}'})
    ])
    runtime, _recorder, _trace_store = _agent(tmp_path, llm)

    events = runtime.prompt("use unknown tool")
    tool_message = _tool_messages(runtime)[0]

    assert any(event.type == "tool_error" for event in events)
    assert tool_message.tool_call_id == "call-unknown"
    assert tool_message.tool_name == "not_registered"
    assert tool_message.metadata["is_error"] is True
    assert "not registered" in tool_message.content[0].text.lower() or "unknown tool" in tool_message.content[0].text.lower()


def test_sensitive_arguments_are_redacted_in_tool_trace(tmp_path: Path) -> None:
    llm = ScriptedToolLLMClient([
        _tool_event(
            {
                "id": "call-secret",
                "name": "demo_secret",
                "arguments_chunk": '{"api_key":"sk-secret-value","query":"status"}',
            }
        )
    ])
    runtime, recorder, trace_store = _agent(tmp_path, llm)
    runtime.tool_registry.register_function_tool(
        name="demo_secret",
        description="Inspect local state",
        parameters={"type": "object", "properties": {"api_key": {"type": "string"}, "query": {"type": "string"}}},
        executor=lambda _workspace, _arguments: "ok",
        permission_domain="read",
        tool_family="extension",
        exact_effect_mode="auto",
        non_side_effectful=True,
        known_safe_inspect=True,
    )

    runtime.prompt("secret trace")
    spans = _latest_run_spans(recorder, trace_store)
    middleware = next(
        span
        for span in spans
        if span.name == "tool.call"
        and span.attributes.get("tool_call_id") == "call-secret"
        and span.attributes.get("source") == "tool_registry_middleware"
    )

    assert middleware.input["arguments"]["api_key"] == "[REDACTED]"
    assert "sk-secret-value" not in str(middleware.model_dump(mode="json"))


def test_write_tool_requires_approval_and_records_token_alignment(tmp_path: Path) -> None:
    llm = ScriptedToolLLMClient([
        _tool_event({"id": "call-write", "name": "write_file", "arguments_chunk": '{"path":"notes.txt","content":"alpha"}'})
    ])
    runtime, recorder, trace_store = _agent(tmp_path, llm, require_plan_approval=True)

    events = runtime.prompt("write notes")
    spans = _latest_run_spans(recorder, trace_store)
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()

    assert runtime.state.pending_tool_calls[0].id == "call-write"
    assert runtime.state.pending_plan_token is not None
    assert pending and pending[0]["action_type"] == "planner_approval"
    assert pending[0]["details"]["tool_calls"][0]["id"] == "call-write"
    assert not (tmp_path / "notes.txt").exists()
    assert any(event.type == "planner_gate_pending" for event in events)
    approval_span = next(span for span in spans if span.name == "approval.decision")
    assert approval_span.attributes["approval_token"] == runtime.state.pending_plan_token


def test_rejected_approval_does_not_execute_and_records_observation(tmp_path: Path) -> None:
    llm = ScriptedToolLLMClient([])
    runtime, _recorder, _trace_store = _agent(tmp_path, llm)
    staged = runtime.tool_registry.execute("write_file", {"path": "notes.txt", "content": "alpha"}, tool_call_id="call-write")
    rejected = runtime.tool_registry.host_execute("reject_pending_action", {"token": staged.details["token"]})
    message = runtime.record_external_approval_result(
        {
            "session_id": runtime.session_id,
            "token": staged.details["token"],
            "action_type": "reject_pending_action",
            "source_tool_name": "reject_pending_action",
            "tool_call_id": "call-write",
            "success": True,
            "approval_action": "reject",
            "approved": False,
            "rejected": True,
            "result": rejected.content,
            "details": rejected.details,
        }
    )

    assert not (tmp_path / "notes.txt").exists()
    assert message.role == "tool"
    assert message.tool_call_id == "call-write"
    assert message.metadata["tool_details"]["approval_status"] == "rejected"


def test_read_only_policy_blocks_write_with_error_observation(tmp_path: Path) -> None:
    llm = ScriptedToolLLMClient([
        _tool_event({"id": "call-readonly-write", "name": "write_file", "arguments_chunk": '{"path":"notes.txt","content":"alpha"}'})
    ])
    runtime, _recorder, _trace_store = _agent(tmp_path, llm, policy=ToolPolicyConfig(permission_mode="read-only"))

    runtime.prompt("write in readonly")
    tool_message = _tool_messages(runtime)[0]

    assert not (tmp_path / "notes.txt").exists()
    assert tool_message.metadata["is_error"] is True
    assert "read-only" in tool_message.content[0].text.lower()
