from __future__ import annotations

import json
from pathlib import Path

from pp_agent.coding import (
    ControlledLoopOptions,
    ControlledToolLoopResult,
    prepare_coding_workflow,
    run_controlled_coding_loop,
    start_coding_execution_session,
)
from pp_agent.cli.commands import coding as coding_cli


class FakeRuntime:
    def __init__(self) -> None:
        self.prompt_calls: list[str] = []
        self.approved: list[str] = []
        self.applied: list[str] = []
        self.runtime_execution_context = None

    def prompt(self, text: str):
        self.prompt_calls.append(text)
        return []

    def approve_pending_action(self, token: str):  # pragma: no cover - should never be called
        self.approved.append(token)

    def apply_patch_candidate(self, token: str):  # pragma: no cover - should never be called
        self.applied.append(token)


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src" / "pp_agent" / "cli").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "cli").mkdir(parents=True, exist_ok=True)
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    return tmp_path


def _result(tmp_path: Path, *, pending: list[dict] | None = None) -> ControlledToolLoopResult:
    workspace = _workspace(tmp_path)
    runtime = FakeRuntime()
    result = run_controlled_coding_loop(
        "add cli code command",
        runtime,
        workspace=workspace,
        options=ControlledLoopOptions(0, True, True, True, True),
    )
    result.pending_approvals = pending or []
    result.summary_text = "safe summary"
    return result


def test_prepare_result_to_cli_dict_is_json_safe(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workflow = prepare_coding_workflow("add cli code command", workspace=workspace)
    session = start_coding_execution_session(workflow, session_id="exec-test")

    payload = coding_cli.prepare_result_to_cli_dict(workflow, session, show_timeline=True)

    assert payload["mode"] == "prepare_only"
    assert payload["task"] == "add cli code command"
    assert payload["status"] == "prepared"
    assert payload["phase"] == "prepared"
    assert payload["plan_summary"]["step_count"] >= 1
    assert payload["predicted_impact_summary"]["predicted_impact_not_actual"] is True
    assert payload["execution_guardrails"]["stop_on_approval"] is True
    json.dumps(payload)


def test_controlled_loop_result_to_cli_dict_filters_pending_payloads(tmp_path: Path) -> None:
    result = _result(
        tmp_path,
        pending=[
            {
                "token": "tok-1",
                "action_type": "apply_patch_candidate",
                "tool_name": "apply_patch_candidate",
                "title": "Apply staged patch",
                "summary": "Apply staged patch",
                "changed_files": ["src/pp_agent/cli/main.py"],
                "command": None,
                "scope_check": {"allowed": True, "reason": "within scope", "payload": "hidden"},
                "payload": {"secret": "do-not-print"},
                "details": {"content_text": "file contents must stay hidden"},
            }
        ],
    )

    payload = coding_cli.controlled_loop_result_to_cli_dict(result, show_timeline=True)
    encoded = json.dumps(payload)

    assert payload["pending_approvals_count"] == 1
    assert payload["pending_approvals"][0] == {
        "token": "tok-1",
        "action_type": "apply_patch_candidate",
        "tool_name": "apply_patch_candidate",
        "title": "Apply staged patch",
        "summary": "Apply staged patch",
        "changed_files": ["src/pp_agent/cli/main.py"],
        "command": None,
        "scope_check": {
            "allowed": True,
            "reason": "within scope",
            "matched_rule": None,
            "risk_level": None,
        },
    }
    assert "do-not-print" not in encoded
    assert "file contents must stay hidden" not in encoded


def test_format_controlled_loop_result_includes_compact_pending_approval(tmp_path: Path) -> None:
    result = _result(
        tmp_path,
        pending=[
            {
                "token": "tok-2",
                "action_type": "run_shell",
                "tool_name": "run_shell",
                "title": "Run validation",
                "summary": "Run validation",
                "changed_files": [],
                "command": "python -m pytest tests/cli -q",
                "payload": {"secret": "hidden"},
            }
        ],
    )

    text = coding_cli.format_controlled_loop_result(result, show_timeline=True)

    assert "Controlled Coding Workflow" in text
    assert "Pending Approvals: 1" in text
    assert "tok-2 run_shell: Run validation" in text
    assert "python -m pytest tests/cli -q" in text
    assert "hidden" not in text


def test_run_code_command_prepare_only_does_not_run_loop(monkeypatch, tmp_path: Path) -> None:
    called = {"loop": False}

    def fail_loop(*args, **kwargs):  # pragma: no cover - assertion helper
        called["loop"] = True
        raise AssertionError("prepare-only must not run controlled loop")

    monkeypatch.setattr(coding_cli, "run_controlled_coding_loop", fail_loop)

    payload = coding_cli.run_code_command("add cli code command", _workspace(tmp_path), prepare_only=True, json_mode=True)

    assert payload["mode"] == "prepare_only"
    assert called["loop"] is False


def test_run_code_command_controlled_loop_passes_options(monkeypatch, tmp_path: Path) -> None:
    runtime = FakeRuntime()
    captured: dict[str, object] = {}

    def fake_build_agent(workspace: Path):
        captured["workspace"] = workspace
        return runtime

    def fake_run_loop(task, runtime_arg, workspace=None, options=None):
        captured["task"] = task
        captured["runtime"] = runtime_arg
        captured["options"] = options
        return _result(tmp_path)

    monkeypatch.setattr(coding_cli, "build_agent", fake_build_agent)
    monkeypatch.setattr(coding_cli, "run_controlled_coding_loop", fake_run_loop)

    payload = coding_cli.run_code_command(
        "add cli code command",
        _workspace(tmp_path),
        max_turns=7,
        dry_run=True,
        json_mode=True,
    )

    options = captured["options"]
    assert payload["mode"] == "controlled_loop"
    assert captured["task"] == "add cli code command"
    assert captured["runtime"] is runtime
    assert options.max_model_turns == 7
    assert options.dry_run is True
    assert options.stop_on_approval is True
    assert options.stop_on_guardrail_block is True
    assert options.stop_on_scope_block is True
    assert runtime.approved == []
    assert runtime.applied == []


def test_public_cli_helpers_have_docstrings() -> None:
    assert coding_cli.run_code_command.__doc__
    assert coding_cli.format_controlled_loop_result.__doc__
    assert coding_cli.format_prepare_only_result.__doc__
    assert coding_cli.controlled_loop_result_to_cli_dict.__doc__
    assert coding_cli.prepare_result_to_cli_dict.__doc__
