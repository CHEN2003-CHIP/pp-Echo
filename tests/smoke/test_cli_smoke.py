from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run_module(*args: str, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["COLUMNS"] = "240"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_pp_agent_help_smoke() -> None:
    result = _run_module("pp_agent.cli.main", "--help")

    assert result.returncode == 0
    assert "Personal Python coding agent" in result.stdout


def test_pp_agent_sessions_tree_smoke() -> None:
    result = _run_module("pp_agent.cli.main", "sessions", "tree")

    assert result.returncode == 0
    assert "Session Tree" in result.stdout


def test_pp_agent_approvals_summary_smoke() -> None:
    result = _run_module("pp_agent.cli.main", "approvals", "summary")

    assert result.returncode == 0
    assert "Approvals Queue" in result.stdout


def test_pp_agent_capabilities_list_smoke(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    skill_path = tmp_path / ".pi" / "skills" / "demo" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text("---\nname: demo\ndescription: smoke skill\n---\nbody", encoding="utf-8")

    result = _run_module(
        "pp_agent.cli.main",
        "capabilities",
        "list",
        "--workspace",
        str(tmp_path),
        env_overrides={"PP_AGENT_HOME": str(tmp_path / ".pp-agent-home")},
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    demo = next(item for item in payload if item["name"] == "demo")
    assert demo["status"] == "discovered"
    assert demo["metadata"]["origin_type"] == "project"


def test_pp_agent_skills_commands_smoke(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    skill_path = tmp_path / ".pi" / "skills" / "demo" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text("---\nname: demo\ndescription: smoke skill\n---\nbody", encoding="utf-8")
    env = {"PP_AGENT_HOME": str(tmp_path / ".pp-agent-home")}

    list_result = _run_module("pp_agent.cli.main", "skills", "list", "--workspace", str(tmp_path), env_overrides=env)
    show_result = _run_module("pp_agent.cli.main", "skills", "show", "demo", "--workspace", str(tmp_path), env_overrides=env)

    assert list_result.returncode == 0
    assert show_result.returncode == 0
    list_payload = json.loads(list_result.stdout)
    demo = next(item for item in list_payload if item["name"] == "demo")
    assert demo["metadata"]["discovery_mode"] == "project_convention"
    assert demo["metadata"]["discovery_root"] == str(tmp_path.resolve())
    assert json.loads(show_result.stdout)["name"] == "demo"


def test_pp_agent_skills_add_dir_smoke(tmp_path: Path) -> None:
    external = tmp_path / "experiment-report-skill"
    external.mkdir(parents=True)
    external.joinpath("SKILL.md").write_text(
        "---\nname: experiment-report\ndescription: Experiment reports\n---\nbody",
        encoding="utf-8",
    )
    env = {"PP_AGENT_HOME": str(tmp_path / ".pp-agent-home")}

    add_result = _run_module("pp_agent.cli.main", "skills", "add-dir", str(external), "--workspace", str(tmp_path), env_overrides=env)
    list_result = _run_module("pp_agent.cli.main", "skills", "list", "--workspace", str(tmp_path), env_overrides=env)

    assert add_result.returncode == 0
    assert list_result.returncode == 0
    assert any(item["name"] == "experiment-report" for item in json.loads(list_result.stdout))


def test_pp_agent_module_help_smoke() -> None:
    result = _run_module("pp_agent.cli.main", "--help")

    assert result.returncode == 0
    assert "Personal Python coding agent" in result.stdout


def test_pp_agent_tui_help_smoke() -> None:
    result = _run_module("pp_agent.cli.main", "tui", "--help")

    assert result.returncode == 0
    assert "workspace" in result.stdout


def test_run_hello_wiring_smoke(monkeypatch, tmp_path: Path) -> None:
    from pp_agent.cli.commands import run as run_command

    class FakeEvent:
        def model_dump(self, mode: str = "json") -> dict:
            return {"type": "agent_end"}

    class FakeRuntime:
        session_id = "session-1"

        def __init__(self) -> None:
            self.state = type(
                "State",
                (),
                {
                    "pending_plan_token": None,
                    "pending_tool_calls": [],
                    "queued_messages": [],
                    "messages": [],
                },
            )()

        def subscribe(self, callback) -> None:
            self.callback = callback

        def prompt(self, text: str):
            assert text == "hello"
            return [FakeEvent()]

    monkeypatch.setattr(run_command, "build_agent", lambda workspace, session_id=None: FakeRuntime())

    payload = run_command.run_main("hello", tmp_path, json_mode=True)

    assert payload["session_id"] == "session-1"
    assert payload["event_count"] == 1


def test_chat_main_enters_loop(monkeypatch, tmp_path: Path) -> None:
    from pp_agent.cli import chat as chat_module
    from pp_agent.runtime.events import RuntimeMonitor

    class FakeRuntime:
        session_id = "session-1"

        def __init__(self) -> None:
            self.llm_client = type("Client", (), {"model": type("Model", (), {"model": "fake-model"})()})()
            self.state = type(
                "State",
                (),
                {
                    "pending_plan_token": None,
                    "pending_tool_calls": [],
                    "queued_messages": [],
                    "turn": type("Turn", (), {"turn_id": 0, "phase": "idle", "reason": ""})(),
                    "compaction": type("Compaction", (), {"summary": "", "summarized_message_count": 0})(),
                },
            )()
            self.runtime_monitor = RuntimeMonitor()

        def subscribe(self, callback) -> None:
            self.callback = callback

    monkeypatch.setattr(chat_module, "build_agent", lambda workspace, session_id=None: FakeRuntime())
    monkeypatch.setattr(chat_module, "PromptSession", None)
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(EOFError()))

    chat_module.chat_main(tmp_path)
