from __future__ import annotations

import json
from pathlib import Path

from pp_agent.evaluation.adapter import ScriptedAgentAdapter
from pp_agent.evaluation.environment import WorkspaceEnvironment, snapshot_files
from pp_agent.evaluation.models import EvalTask
from pp_agent.evaluation.reports import load_latest_report
from pp_agent.evaluation.runner import load_suite, load_task, run_suite
from pp_agent.evaluation.scoring import score_case
from pp_agent.evaluation.user_simulator import ScriptedUserSimulator


ROOT = Path(__file__).resolve().parents[2]


def test_load_task_rejects_unknown_schema_field(tmp_path: Path) -> None:
    task_path = tmp_path / "bad.json"
    task_path.write_text(
        json.dumps(
            {
                "id": "bad",
                "name": "Bad",
                "category": "unit",
                "workspace_fixture": "python_basic",
                "user_agenda": [{"kind": "message", "text": "hello"}],
                "legacy_expect": {"contains": "hello"},
            }
        ),
        encoding="utf-8",
    )

    try:
        load_task(task_path)
    except Exception as exc:  # noqa: BLE001
        assert "legacy_expect" in str(exc)
    else:
        raise AssertionError("invalid tau-style eval schema was accepted")


def test_core_suite_loads_canonical_json_tasks() -> None:
    tasks = load_suite(ROOT, "pp_echo_core")

    assert {task.id for task in tasks} == {
        "file_edit_basic",
        "tool_selection",
        "approval_required",
        "protected_path",
        "checkpoint_rewind",
        "memory_recall",
        "subagent_limited_tools",
    }
    assert all(task.user_agenda for task in tasks)
    assert all(task.max_turns > 0 for task in tasks)


def test_environment_snapshots_and_verification(tmp_path: Path) -> None:
    task = load_task(ROOT / "evals" / "tasks" / "file_edit_basic.json")
    env = WorkspaceEnvironment(ROOT, task, tmp_path)
    workspace = env.prepare()
    before = snapshot_files(workspace)

    app = workspace / "app.py"
    app.write_text(app.read_text(encoding="utf-8").replace("return 0", "return a + b"), encoding="utf-8")
    results = env.run_verification_commands()
    after = snapshot_files(workspace)

    assert before["app.py"] != after["app.py"]
    assert all(result.returncode == 0 for result in results)


def test_scripted_user_handles_approval_agenda(tmp_path: Path) -> None:
    task = load_task(ROOT / "evals" / "tasks" / "approval_required.json")
    env = WorkspaceEnvironment(ROOT, task, tmp_path)
    workspace = env.prepare()

    trace = ScriptedUserSimulator().run(task, workspace, ScriptedAgentAdapter())

    assert "write_file" in trace.approvals
    assert "write_file" in trace.tool_calls
    assert (workspace / "approved.txt").exists()
    assert trace.pending_actions == []


def test_scorer_uses_state_communication_and_action_rewards(tmp_path: Path) -> None:
    task = load_task(ROOT / "evals" / "tasks" / "file_edit_basic.json")
    env = WorkspaceEnvironment(ROOT, task, tmp_path)
    workspace = env.prepare()
    before = env.snapshot()
    trace = ScriptedUserSimulator().run(task, workspace, ScriptedAgentAdapter())
    after = env.snapshot()

    score = score_case(
        task,
        workspace=workspace,
        before_snapshot=before,
        after_snapshot=after,
        trace=trace,
        verification_results=env.run_verification_commands(),
    )

    assert score.passed is True
    assert score.state_reward == 1.0
    assert score.communication_reward == 1.0
    assert score.action_reward == 1.0


def test_memory_recall_is_scored_as_real_event(tmp_path: Path) -> None:
    task = load_task(ROOT / "evals" / "tasks" / "memory_recall.json")
    env = WorkspaceEnvironment(ROOT, task, tmp_path)
    workspace = env.prepare()
    before = env.snapshot()
    trace = ScriptedUserSimulator().run(task, workspace, ScriptedAgentAdapter())
    after = env.snapshot()

    score = score_case(
        task,
        workspace=workspace,
        before_snapshot=before,
        after_snapshot=after,
        trace=trace,
        verification_results=env.run_verification_commands(),
    )

    assert score.passed is True
    assert any(event["type"] == "memory_recall" for event in score.trace_events)


def test_run_suite_writes_tau_style_report(tmp_path: Path) -> None:
    report = run_suite(ROOT, suite="pp_echo_core", mode="deterministic", case_count=3, output_dir=tmp_path)

    assert report.total_cases == 3
    assert report.passed == 3
    assert (tmp_path / "latest.json").exists()
    assert (tmp_path / "latest.md").exists()
    assert (tmp_path / "latest.svg").exists()
    assert load_latest_report(tmp_path).suite == "pp_echo_core"
