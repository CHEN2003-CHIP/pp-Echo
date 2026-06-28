from __future__ import annotations

from pathlib import Path

from pp_agent.observability.audit_graph import (
    DUPLICATE_FINAL_ANSWER,
    MISSING_RUN_LINK,
    MISSING_TOOL_POLICY,
    UNBUDGETED_CONTEXT_ITEM,
    UNRELATED_BOT_DELIVERY,
    build_audit_graph,
)
from pp_agent.observability.recorder import TraceRecorder
from pp_agent.observability.store import TraceStore
from pp_agent.storage.settings import ToolPolicyConfig
from pp_agent.tools.registry import ToolRegistry


def _normal_trace(tmp_path: Path):
    trace_store = TraceStore(tmp_path)
    recorder = TraceRecorder(trace_store, workspace=tmp_path)
    registry = ToolRegistry(tmp_path, policy=ToolPolicyConfig(permission_mode="workspace-write"), observability=recorder)
    run_id = recorder.start_run(
        session_id="session-graph",
        user_goal_preview="audit",
        attributes={"profile_id": "default", "channel_id": "local"},
    )
    recorder.record_completed_span(
        "memory.recall",
        "memory",
        output={"returned_count": 1},
    )
    recorder.record_completed_span(
        "context.build",
        "context",
        output={
            "context": {
                "budget_report": {
                    "used": 4,
                    "total_budget": 100,
                    "included_items": [{"id": "memory:1", "section": "episodic_recall", "estimated_chars": 4}],
                }
            }
        },
    )
    registry.execute("list_files", {"path": "."}, tool_call_id="call-graph")
    recorder.record_completed_span("final.answer", "llm", attributes={"source": "provider_response"})
    recorder.end_run()
    return trace_store.read_run(run_id)


def test_audit_graph_reconstructs_normal_runtime_path(tmp_path: Path) -> None:
    detail = _normal_trace(tmp_path)

    graph = build_audit_graph(
        detail,
        bot_traces=[
            {
                "trace_id": "bot-trace",
                "session_id": "session-graph",
                "runtime_trace_run_id": detail.run.run_id,
                "parent_id": detail.run.run_id,
            }
        ],
    )

    assert not graph.violations
    assert graph.nodes_by_kind("user.message")
    assert graph.nodes_by_kind("memory.lookup")
    assert graph.nodes_by_kind("context.item")
    assert graph.nodes_by_kind("tool.policy")
    assert graph.nodes_by_kind("tool.call")
    assert graph.nodes_by_kind("tool.result")
    assert graph.nodes_by_kind("final.answer")
    assert graph.nodes_by_kind("bot.delivery")


def test_audit_graph_detects_duplicate_final_answer(tmp_path: Path) -> None:
    detail = _normal_trace(tmp_path)
    recorder = TraceRecorder(TraceStore(tmp_path), workspace=tmp_path)
    recorder.current_run_id = detail.run.run_id
    recorder.current_session_id = detail.run.session_id
    recorder.record_completed_span("final.answer", "llm")
    detail = TraceStore(tmp_path).read_run(detail.run.run_id)

    graph = build_audit_graph(detail)

    assert "duplicate_final_answer" in graph.violations
    assert DUPLICATE_FINAL_ANSWER in graph.warning_codes()


def test_audit_graph_detects_tool_call_without_policy(tmp_path: Path) -> None:
    trace_store = TraceStore(tmp_path)
    recorder = TraceRecorder(trace_store, workspace=tmp_path)
    run_id = recorder.start_run(session_id="s1", user_goal_preview="bad")
    recorder.record_completed_span("tool.call", "tool", attributes={"tool_name": "direct_tool"})
    recorder.end_run()

    graph = build_audit_graph(trace_store.read_run(run_id))

    assert "tool_without_policy:direct_tool" in graph.violations
    assert MISSING_TOOL_POLICY in graph.warning_codes()


def test_audit_graph_detects_missing_run_linkage_and_unbudgeted_context_item(tmp_path: Path) -> None:
    trace_store = TraceStore(tmp_path)
    recorder = TraceRecorder(trace_store, workspace=tmp_path)
    run_id = recorder.start_run(session_id="s1", user_goal_preview="bad-budget")
    recorder.record_completed_span(
        "context.build",
        "context",
        output={"context": {"budget_report": {"included_items": [{"id": "ctx:1"}]}}},
    )
    recorder.end_run()
    detail = trace_store.read_run(run_id)
    detail.run = None

    graph = build_audit_graph(detail)

    assert "missing_run_record" in graph.violations
    assert "unbudgeted_context_item:ctx:1" in graph.violations
    assert MISSING_RUN_LINK in graph.warning_codes()
    assert UNBUDGETED_CONTEXT_ITEM in graph.warning_codes()


def test_audit_graph_detects_bot_delivery_unrelated_to_runtime_run(tmp_path: Path) -> None:
    detail = _normal_trace(tmp_path)

    graph = build_audit_graph(detail, bot_traces=[{"trace_id": "bot-bad", "session_id": "other", "runtime_trace_run_id": "wrong", "parent_id": "wrong"}])

    assert "bot_delivery_unlinked_runtime_run" in graph.violations
    assert "bot_delivery_session_mismatch" in graph.violations
    assert UNRELATED_BOT_DELIVERY in graph.warning_codes()
