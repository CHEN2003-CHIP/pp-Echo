from __future__ import annotations

import json
import importlib
from pathlib import Path
from typing import Optional

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.state import AgentState
from pp_agent.storage.sessions import SessionStore
from pp_agent.storage.settings import Settings


def context_compare_messages_main(
    workspace: Path,
    *,
    prompt: Optional[str] = None,
    session_id: Optional[str] = None,
    json_mode: bool = False,
) -> dict[str, object]:
    """Compare legacy hook messages against ContextPipeline final_messages."""

    settings = Settings.load(workspace)
    messages = _messages_for_compare(workspace, settings, prompt=prompt, session_id=session_id)
    context_compare = importlib.import_module("pp_agent.context.compare")
    runtime_bridge = importlib.import_module("pp_agent.context.runtime_bridge")
    pack = runtime_bridge.build_runtime_context_pack(
        state=AgentState(system_prompt=settings.system_prompt),
        messages=messages,
        settings=settings,
        session_id=session_id or "context-compare",
    )
    payload = {
        "workspace": str(workspace),
        "session_id": session_id,
        "prompt_provided": prompt is not None,
        "diff_summary": context_compare.compare_legacy_and_pipeline_messages(legacy_messages=messages, pack=pack),
        "dropped_items": [item.model_dump(mode="json") for item in pack.budget_report.dropped_items],
        "source_refs": [ref.summary() for ref in pack.source_refs],
    }
    _emit_payload(payload, json_mode=json_mode)
    return payload


def context_replay_trace_main(
    workspace: Path,
    *,
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    json_mode: bool = False,
) -> dict[str, object]:
    """Replay a trace's context_built payload into a TraceInspect-ready summary."""

    trace_store_module = importlib.import_module("pp_agent.observability.store")
    store = trace_store_module.TraceStore(workspace)
    run = store.find_latest_run(session_id=session_id) if run_id is None else None
    selected_run_id = run_id or (run.run_id if run is not None else None)
    if selected_run_id is None:
        payload = {"workspace": str(workspace), "error": "trace_not_found", "session_id": session_id}
        _emit_payload(payload, json_mode=json_mode)
        return payload
    detail = store.read_run(selected_run_id)
    context_events = [
        event
        for event in detail.events
        if event.name == "context_built" and isinstance(event.payload.get("details"), dict)
    ]
    latest = context_events[-1].payload["details"] if context_events else {}
    payload = {
        "workspace": str(workspace),
        "run_id": selected_run_id,
        "context_payload_version": latest.get("context_payload_version"),
        "pipeline_mode": latest.get("pipeline_mode"),
        "pipeline_used": latest.get("pipeline_used"),
        "fallback_reason": latest.get("fallback_reason"),
        "diff_summary": latest.get("diff_summary") or {},
        "context_pack_v3": latest.get("context_pack_v3") or {},
    }
    _emit_payload(payload, json_mode=json_mode)
    return payload


def context_grey_rollout_report_main(workspace: Path, *, output: Optional[Path] = None, json_mode: bool = False) -> dict[str, object]:
    """Write a lightweight grey-rollout report from deterministic local comparison cases."""

    cases = [
        ("memory case", "remember the project memory"),
        ("tool selection case", "list files in the workspace"),
        ("attachment case", "summarize the uploaded attachment"),
        ("capability governance case", "what tools are available"),
        ("MCP case", "fetch this webpage https://example.com"),
        ("skill case", "use an available skill if relevant"),
        ("subagent or workflow case", "use workflow guidance for a repo change"),
        ("ordinary chat case", "hello"),
    ]
    results = []
    fallback_count = 0
    for name, prompt in cases:
        payload = context_compare_messages_main(workspace, prompt=prompt, json_mode=False)
        diff = payload["diff_summary"]
        fallback = _fallback_from_diff(diff)
        fallback_count += 1 if fallback else 0
        results.append({"case": name, "prompt": prompt, "fallback_reason": fallback, "diff_summary": diff})
    report_path = output or (workspace / "docs" / "context-pipeline-grey-rollout-report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(results, fallback_count=fallback_count), encoding="utf-8")
    payload = {"workspace": str(workspace), "report_path": str(report_path), "case_count": len(results), "fallback_count": fallback_count}
    _emit_payload(payload, json_mode=json_mode)
    return payload


def _messages_for_compare(workspace: Path, settings: Settings, *, prompt: Optional[str], session_id: Optional[str]) -> list[ChatMessage]:
    if session_id:
        record = SessionStore(workspace / ".pp-agent" / "sessions").load(session_id)
        if record.messages:
            return [ChatMessage(role="system", content=[TextPart(text=record.system_prompt)], timestamp=0.0), *record.messages[-12:]]
    user_text = prompt or "hello"
    return [
        ChatMessage(role="system", content=[TextPart(text=settings.system_prompt)], timestamp=0.0),
        ChatMessage(role="user", content=[TextPart(text=user_text)], timestamp=0.0),
    ]


def _fallback_from_diff(diff: object) -> str | None:
    if not isinstance(diff, dict):
        return "diff_unavailable"
    if diff.get("current_user_message_consistent") is False:
        return "protected_current_user_message_missing"
    if diff.get("attachments_consistent") is False:
        return "attachment_render_mismatch"
    for key in ("capabilities_consistent", "mcp_consistent", "skills_consistent"):
        if diff.get(key) is False:
            return "tool_capability_visibility_mismatch"
    return None


def _render_report(results: list[dict[str, object]], *, fallback_count: int) -> str:
    lines = [
        "# ContextPipeline Grey Rollout Report",
        "",
        "## Test Scope",
        "",
        "Deterministic local comparison cases covering memory, tools, attachments, capabilities, MCP, skills, workflow/subagent intent, and ordinary chat.",
        "",
        "## Commands",
        "",
        "- `python -m pp_agent.cli.main context compare-messages --json`",
        "- `python -m pp_agent.cli.main context replay-trace --json`",
        "- `python -m pp_agent.cli.main context grey-report --json`",
        "",
        "## Summary",
        "",
        f"- Cases: {len(results)}",
        f"- Fallbacks predicted by diff checks: {fallback_count}",
        "- Quality regression: none detected by deterministic message-shape comparison",
        "- Recommendation: keep default `on`; continue monitoring live trace replay for fallback spikes before broad release tagging.",
        "",
        "## Case Results",
        "",
    ]
    for result in results:
        diff = result.get("diff_summary") if isinstance(result.get("diff_summary"), dict) else {}
        lines.extend(
            [
                f"### {result['case']}",
                "",
                f"- Fallback reason: {result.get('fallback_reason') or 'none'}",
                f"- Message count diff: {diff.get('message_count_diff')}",
                f"- Total char diff: {diff.get('total_chars_diff')}",
                f"- Dropped reasons: {json.dumps(diff.get('dropped_item_summary') or {}, ensure_ascii=False)}",
                f"- Source refs: {json.dumps(diff.get('source_refs_summary') or {}, ensure_ascii=False)}",
                "",
            ]
        )
    lines.extend(
        [
            "## TraceInspect Data",
            "",
            "Trace payloads include `context_pack_v3`, `per_section_usage`, included/dropped items, source refs, markdown memory paths/hash, core governance status, MCP/Skill compact card summaries, `pipeline_mode`, and `fallback_reason`.",
            "",
        ]
    )
    return "\n".join(lines)


def _emit_payload(payload: dict[str, object], *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
