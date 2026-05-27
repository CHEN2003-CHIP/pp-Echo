from __future__ import annotations

from pathlib import Path

from evals.scorers import AgentTrace, CommandResult, EvalTask, load_task, score_case, snapshot_files


def make_task(**overrides) -> EvalTask:
    data = {
        "id": "case",
        "name": "Case",
        "category": "unit",
        "workspace_fixture": "fixture",
        "user_goal": "goal",
        "expected_files_changed": [],
        "forbidden_files_changed": [],
        "required_approvals": [],
        "forbidden_tools": [],
        "verification_commands": [],
        "success_criteria": {},
    }
    data.update(overrides)
    return EvalTask(**data)


def test_load_task_reads_yaml_compatible_json() -> None:
    task = load_task(Path("evals/tasks/file_edit_basic.yaml"))

    assert task.id == "file_edit_basic"
    assert task.workspace_fixture == "python_basic"
    assert "app.py" in task.expected_files_changed


def test_score_case_passes_expected_file_change(tmp_path: Path) -> None:
    workspace = tmp_path
    target = workspace / "app.py"
    target.write_text("return 0\n", encoding="utf-8")
    before = snapshot_files(workspace)
    target.write_text("return 1\n", encoding="utf-8")
    after = snapshot_files(workspace)

    task = make_task(expected_files_changed=["app.py"])
    score = score_case(
        task,
        before_snapshot=before,
        after_snapshot=after,
        trace=AgentTrace(tool_calls=["edit_file"]),
        verification_results=[CommandResult("check", 0)],
    )

    assert score.passed is True
    assert score.failure_reasons == []
    assert score.tool_success_rate == 1.0


def test_score_case_blocks_forbidden_file_change(tmp_path: Path) -> None:
    secret = tmp_path / ".env"
    secret.write_text("A=1\n", encoding="utf-8")
    before = snapshot_files(tmp_path)
    secret.write_text("A=2\n", encoding="utf-8")
    after = snapshot_files(tmp_path)

    task = make_task(forbidden_files_changed=[".env"])
    score = score_case(
        task,
        before_snapshot=before,
        after_snapshot=after,
        trace=AgentTrace(),
        verification_results=[],
    )

    assert score.passed is False
    assert score.safety_violations == ["forbidden file changed: .env"]


def test_score_case_checks_approval_and_forbidden_tool() -> None:
    task = make_task(required_approvals=["write_file"], forbidden_tools=["run_shell"])

    score = score_case(
        task,
        before_snapshot={},
        after_snapshot={},
        trace=AgentTrace(tool_calls=["run_shell"], approvals=[]),
        verification_results=[],
    )

    assert score.passed is False
    assert score.approval_recall == 0.0
    assert score.tool_success_rate == 1.0
    assert "forbidden tool called: run_shell" in score.failure_reasons
    assert "missing required approvals: write_file" in score.failure_reasons


def test_score_case_marks_memory_recall_as_pending_without_event() -> None:
    task = make_task(success_criteria={"memory_recall_required": True})

    score = score_case(
        task,
        before_snapshot={},
        after_snapshot={},
        trace=AgentTrace(events=[{"type": "memory_recall_pending"}]),
        verification_results=[],
    )

    assert score.passed is False
    assert score.pending is True
    assert score.failure_reasons == ["memory recall trace is pending until runtime event wiring exists"]


def test_score_case_marks_unwired_adapter_as_pending() -> None:
    task = make_task(expected_files_changed=["app.py"])

    score = score_case(
        task,
        before_snapshot={},
        after_snapshot={},
        trace=AgentTrace(events=[{"type": "adapter_pending", "message": "live adapter pending"}]),
        verification_results=[CommandResult("check", 1)],
    )

    assert score.passed is False
    assert score.pending is True
    assert score.failure_reasons == ["live adapter pending"]


def test_score_case_fails_on_tool_result_error() -> None:
    task = make_task()

    score = score_case(
        task,
        before_snapshot={},
        after_snapshot={},
        trace=AgentTrace(tool_calls=["read_file"], tool_results=[False]),
        verification_results=[],
    )

    assert score.passed is False
    assert score.tool_success_rate == 0.0
    assert "one or more tool calls failed" in score.failure_reasons


def test_score_case_accepts_checkpoint_rewind_restore() -> None:
    task = make_task(success_criteria={"checkpoint_rewind_restored": True, "rewind_files": ["app.py"]})
    before = {"app.py": "same"}
    after = {"app.py": "same"}

    score = score_case(
        task,
        before_snapshot=before,
        after_snapshot=after,
        trace=AgentTrace(checkpoint_rewind_restored=True),
        verification_results=[],
    )

    assert score.passed is True
