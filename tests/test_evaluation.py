from __future__ import annotations

import io
import json
from pathlib import Path

from pp_agent.cli.commands import eval as eval_command
from pp_agent.cli.commands import claw_tui as claw_tui_command
from pp_agent.cli.commands.claw_tui import claw_tui_main
from pp_agent.evaluation import evaluate_expectation, load_eval_cases, load_eval_summary, metrics_from_payload, run_eval_file


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_EVAL_METADATA = {
    "capability",
    "risk_level",
    "demo_point",
    "expected_tools",
    "interview_notes",
}
MOJIBAKE_MARKERS = ("�", "銆", "涓", "鎬", "璇", "楠")


def test_load_eval_cases_supports_json_object(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.json"
    dataset.write_text(
        json.dumps({"cases": [{"id": "hello", "prompt": "Say hello", "expect": {"contains": "hello"}}]}),
        encoding="utf-8",
    )

    cases = load_eval_cases(dataset)

    assert cases[0].id == "hello"
    assert cases[0].expect == {"contains": "hello"}


def test_load_interview_eval_cases() -> None:
    cases = load_eval_cases(ROOT / "example-interview-eval-cases.json")

    ids = {case.id for case in cases}
    assert len(cases) == 12
    assert "direct_answer_no_tool" in ids
    assert "protected_env_safety" in ids
    assert "write_requires_approval" in ids
    assert all("interview" in case.tags for case in cases)
    assert all(REQUIRED_EVAL_METADATA <= set(case.metadata) for case in cases)
    assert all(case.prompt.strip() for case in cases)
    assert not any(marker in case.prompt for case in cases for marker in MOJIBAKE_MARKERS)


def test_load_core_60_eval_cases() -> None:
    cases = load_eval_cases(ROOT / "evals" / "datasets" / "agent-core-60.json")

    assert len(cases) == 60
    assert all("core60" in case.tags for case in cases)
    assert all(REQUIRED_EVAL_METADATA <= set(case.metadata) for case in cases)
    assert all(isinstance(case.metadata["expected_tools"], list) for case in cases)
    assert not any(marker in case.prompt for case in cases for marker in MOJIBAKE_MARKERS)

    capability_counts: dict[str, int] = {}
    for case in cases:
        capability = str(case.metadata["capability"])
        capability_counts[capability] = capability_counts.get(capability, 0) + 1
    assert sum(capability_counts.values()) == 60
    assert len([case for case in cases if case.id.startswith("direct.")]) == 8
    assert len([case for case in cases if case.id.startswith("repo.")]) == 12
    assert len([case for case in cases if case.id.startswith("tool.")]) == 10
    assert len([case for case in cases if case.id.startswith("safety.")]) == 10
    assert len([case for case in cases if case.id.startswith("collab.")]) == 8
    assert len([case for case in cases if case.id.startswith("memory.")]) == 6
    assert len([case for case in cases if case.id.startswith("chinese.")]) == 6


def test_load_stress_eval_cases() -> None:
    cases = load_eval_cases(ROOT / "evals" / "datasets" / "agent-stress-10.json")

    assert len(cases) == 10
    assert all("stress" in case.tags for case in cases)
    assert all(REQUIRED_EVAL_METADATA <= set(case.metadata) for case in cases)
    assert not any(marker in case.prompt for case in cases for marker in MOJIBAKE_MARKERS)


def test_load_memory_recall_eval_cases() -> None:
    cases = load_eval_cases(ROOT / "example-memory-recall-eval-cases.json")

    ids = {case.id for case in cases}
    assert "memory_cross_session_preference" in ids
    assert "memory_error_fix_path" in ids
    assert all("memory_recall" in case.tags for case in cases)


def test_evaluate_expectation_checks_metrics_and_text() -> None:
    payload = {
        "assistant": "hello from pp-agent",
        "events": [
            {"type": "before_provider_request"},
            {"type": "tool_call", "tool_name": "read_file"},
            {"type": "tool_result", "tool_name": "read_file"},
        ],
        "event_count": 3,
    }
    metrics = metrics_from_payload(payload)

    passed, reason = evaluate_expectation(
        [{"contains": "pp-agent"}, {"tool_called": "read_file"}, "no_tool_errors"],
        payload,
        metrics,
    )

    assert passed is True
    assert reason == "all expectations passed"


def test_metrics_extract_memory_recall_details() -> None:
    payload = {
        "assistant": "ok",
        "events": [
            {
                "type": "context_built",
                "details": {
                    "memory_recall": {
                        "recalled_chunk_ids": ["chunk-1", "chunk-2"],
                        "source_session_ids": ["session-a"],
                        "categories": ["preference", "error_fix"],
                        "snippet_chars": 123,
                    }
                },
            }
        ],
    }

    metrics = metrics_from_payload(payload)

    assert metrics["memory_recall_event_count"] == 1
    assert metrics["memory_recalled_chunk_count"] == 2
    assert metrics["memory_recall_source_session_count"] == 1
    assert metrics["memory_recall_snippet_chars"] == 123
    assert metrics["memory_recall_categories"] == ["preference", "error_fix"]


def test_run_eval_file_writes_results_and_summary(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        '\n'.join(
            [
                json.dumps({"id": "case-1", "prompt": "hello", "expect": {"contains": "hello"}, "tags": ["answer_quality"]}),
                json.dumps({"id": "case-2", "prompt": "read", "expect": {"tool_called": "read_file"}, "tags": ["tool_use"]}),
            ]
        ),
        encoding="utf-8",
    )

    def fake_run(prompt, workspace, session_id=None, collect_events=False):
        events = [{"type": "before_provider_request"}]
        if prompt == "read":
            events.extend(
                [
                    {"type": "tool_call", "tool_name": "read_file"},
                    {"type": "tool_result", "tool_name": "read_file"},
                ]
            )
        return {
            "session_id": "session-1",
            "assistant": f"hello {prompt}",
            "pending_plan_token": None,
            "event_count": len(events),
            "events": events if collect_events else [],
        }

    summary = run_eval_file(dataset, tmp_path, run_id="demo", run_callable=fake_run)

    assert summary.case_count == 2
    assert summary.passed_count == 2
    assert summary.tag_summary["answer_quality"]["pass_rate"] == 1.0
    assert summary.tag_summary["tool_use"]["passed_count"] == 1
    assert Path(summary.result_path).exists()
    assert load_eval_summary(tmp_path, run_id="demo").pass_rate == 1.0


def test_provider_error_is_infrastructure_failure(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.json"
    dataset.write_text(json.dumps([{"id": "case-1", "prompt": "hello", "expect": "no_errors"}]), encoding="utf-8")

    def fake_run(prompt, workspace, session_id=None, collect_events=False):
        events = [
            {"type": "before_provider_request"},
            {"type": "provider_error", "message": "LLM request failed: EOF occurred in violation of protocol (_ssl.c:1129)", "is_error": True},
            {"type": "turn_end", "details": {"failed": True, "failure_kind": "provider_empty_or_invalid_response"}},
        ]
        return {"session_id": "session-1", "assistant": "", "event_count": len(events), "events": events}

    summary = run_eval_file(dataset, tmp_path, run_id="infra-demo", run_callable=fake_run)

    assert summary.passed_count == 0
    assert summary.infra_failed_count == 1
    assert summary.assertion_failed_count == 0
    assert "EOF occurred" in summary.error_messages[0]


def test_preflight_stops_before_cases_on_infra_failure(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.json"
    dataset.write_text(json.dumps([{"id": "case-1", "prompt": "hello"}]), encoding="utf-8")
    calls = []

    def fake_run(prompt, workspace, session_id=None, collect_events=False):
        calls.append(prompt)
        events = [{"type": "provider_error", "message": "LLM request failed: timeout", "is_error": True}]
        return {"session_id": "session-1", "assistant": "", "event_count": len(events), "events": events}

    summary = run_eval_file(dataset, tmp_path, run_id="preflight-demo", preflight=True, run_callable=fake_run)

    assert calls == ["Reply with OK."]
    assert summary.case_count == 0
    assert summary.preflight_result is not None
    assert summary.error_messages == ["LLM request failed: timeout"]


def test_eval_command_report_reads_latest_summary(monkeypatch, tmp_path: Path) -> None:
    dataset = tmp_path / "cases.json"
    dataset.write_text(json.dumps([{"id": "case-1", "prompt": "hello"}]), encoding="utf-8")

    def fake_run_file(dataset_path, workspace, **kwargs):
        return run_eval_file(
            dataset_path,
            workspace,
            run_id="cli-demo",
            run_callable=lambda prompt, workspace, session_id=None, collect_events=False: {
                "session_id": "session-1",
                "assistant": "ok",
                "event_count": 0,
                "events": [],
            },
        )

    monkeypatch.setattr(eval_command, "run_eval_file", fake_run_file)

    summary = eval_command.eval_run_main(dataset, tmp_path, json_mode=False)
    report = eval_command.eval_report_main(tmp_path, run_id=summary.run_id, json_mode=False)

    assert report.run_id == "cli-demo"


def test_eval_report_prints_tag_summary(monkeypatch, tmp_path: Path) -> None:
    dataset = tmp_path / "cases.json"
    dataset.write_text(
        json.dumps(
            [
                {"id": "case-1", "prompt": "hello", "tags": ["tool_use"], "expect": {"contains": "ok"}},
                {"id": "case-2", "prompt": "safe", "tags": ["safety"], "expect": {"contains": "ok"}},
            ]
        ),
        encoding="utf-8",
    )
    run_eval_file(
        dataset,
        tmp_path,
        run_id="tag-demo",
        run_callable=lambda prompt, workspace, session_id=None, collect_events=False: {
            "session_id": "session-1",
            "assistant": "ok",
            "event_count": 0,
            "events": [],
        },
    )
    buffer = io.StringIO()

    class BufferConsole:
        def print(self, *args, **kwargs) -> None:
            end = kwargs.get("end", "\n")
            buffer.write(" ".join(str(arg) for arg in args) + end)

    monkeypatch.setattr(eval_command, "console", BufferConsole())

    eval_command.eval_report_main(tmp_path, run_id="tag-demo", json_mode=False)

    output = buffer.getvalue()
    assert "Tag Summary" in output
    assert "tool_use: 1/1 passed" in output
    assert "safety: 1/1 passed" in output


def test_claw_tui_command_reports_missing_binary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(claw_tui_command, "_binary_path", lambda _repo_root: tmp_path / "missing.exe")

    assert claw_tui_main(tmp_path) == 1
