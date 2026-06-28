from __future__ import annotations

from pathlib import Path

from pp_agent.runtime.control_plane import build_runtime_doctor_report
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.sessions import SessionStore


def test_workflow_doctor_report_includes_contract_status(tmp_path: Path) -> None:
    report = build_runtime_doctor_report(
        tmp_path,
        session_store=SessionStore(tmp_path / ".pp-agent" / "sessions"),
        pending_store=PendingActionStore(tmp_path / ".pp-agent" / "pending-edits"),
    )

    contracts = report["contracts"]
    assert contracts["runtime_channel_boundary"] == "ok"
    assert contracts["tool_policy"] == "ok"
    assert contracts["audit_graph"] == "ok"
    assert contracts["trace_store"] in {"ok", "warning"}
    assert contracts["profile_mode"] == "default-only"


def test_new_adapter_template_documents_required_prohibitions() -> None:
    path = Path("docs/examples/new_adapter_template.md")
    text = path.read_text(encoding="utf-8")

    assert "RuntimeInput" in text
    assert "RuntimeResult" in text
    assert "runtime_trace_run_id" in text
    assert "Call `ToolRegistry` directly" in text
    assert "Call providers directly" in text
    assert "Construct a final answer outside `AgentRuntime` output" in text
    assert "Mutate prompts after `ContextPipeline`" in text
    assert "Create unrelated `run_id`" in text
