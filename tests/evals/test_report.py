from __future__ import annotations

import json
from pathlib import Path

from pp_agent.evaluation.models import CaseScore
from pp_agent.evaluation.reports import build_report, write_report


def test_build_report_aggregates_required_metrics() -> None:
    report = build_report(
        suite="baseline",
        mode="deterministic",
        provider="scripted",
        model="ScriptedLLM",
        commit_hash="abc123",
        scores=[
            CaseScore(task_id="pass", category="file_edit", passed=True, state_reward=1.0, communication_reward=1.0, action_reward=1.0, tool_call_count=2, duration_seconds=0.2),
            CaseScore(
                task_id="fail",
                category="safety",
                passed=False,
                failure_reasons=["forbidden file changed: .env"],
                safety_violations=["forbidden file changed: .env"],
                approval_recall=0.0,
                tool_success_rate=0.0,
                tool_call_count=1,
                duration_seconds=0.4,
            ),
            CaseScore(task_id="pending", category="memory", passed=False, pending=True, failure_reasons=["pending action"], state_reward=1.0, communication_reward=1.0, action_reward=0.0),
        ],
    )

    assert report.commit_hash == "abc123"
    assert report.total_cases == 3
    assert report.passed == 1
    assert report.failed == 1
    assert report.pending == 1
    assert report.safety_violations == 1
    assert report.task_success_rate == 1 / 3
    assert report.approval_recall == 2 / 3
    assert report.tool_success_rate == 2 / 3
    assert report.average_tool_calls == 1.0
    assert report.state_reward == 2 / 3
    assert report.category_summary["file_edit"]["success_rate"] == 1.0


def test_write_report_creates_latest_json_and_markdown(tmp_path: Path) -> None:
    report = build_report(
        suite="baseline",
        mode="deterministic",
        provider="scripted",
        model="ScriptedLLM",
        commit_hash="abc123",
        scores=[CaseScore(task_id="case-1", category="unit", passed=True, state_reward=1.0, communication_reward=1.0, action_reward=1.0, tool_call_count=1, duration_seconds=0.1)],
    )

    json_path, md_path = write_report(report, tmp_path)

    assert json_path == tmp_path / "latest.json"
    assert md_path == tmp_path / "latest.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["commit_hash"] == "abc123"
    assert payload["total_cases"] == 1
    assert (tmp_path / "latest.svg").exists()
    assert "| `case-1` | `unit` | PASS | - |" in md_path.read_text(encoding="utf-8")
