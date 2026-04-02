from __future__ import annotations

from pathlib import Path

from pp_agent import api
from pp_agent.api import sdk
from pp_agent.prompts.loader import load_prompt_templates
from pp_agent.skills.loader import load_skills


def test_api_run_returns_payload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        sdk,
        "run",
        lambda prompt, workspace, **kwargs: {
            "session_id": "session-1",
            "assistant": "",
            "pending_plan_token": None,
            "pending_tool_call_count": 0,
            "queued_message_count": 0,
            "event_count": 1,
        },
    )

    payload = api.run("hello", workspace=tmp_path)

    assert payload["session_id"] == "session-1"
    assert payload["event_count"] == 1


def test_api_module_does_not_import_cli_commands() -> None:
    text = (Path(__file__).resolve().parents[2] / "src" / "pp_agent" / "api" / "__init__.py").read_text(encoding="utf-8")

    assert "cli.commands.run" not in text
    assert "cli.commands.sessions" not in text
    assert "cli.commands.approvals" not in text


def test_prompt_loader_prefers_project_over_user_and_builtin(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    user_root = tmp_path / "user"
    (workspace / ".pp-agent" / "prompts").mkdir(parents=True)
    (user_root / "prompts").mkdir(parents=True)
    (workspace / ".pp-agent" / "prompts" / "system.md").write_text("project", encoding="utf-8")
    (user_root / "prompts" / "system.md").write_text("user", encoding="utf-8")

    templates = load_prompt_templates(workspace, user_root)

    assert templates["system"] == "project"


def test_skill_loader_requires_frontmatter_and_prefers_project(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    user_root = tmp_path / "user"
    project_skill = workspace / ".pp-agent" / "skills" / "demo" / "SKILL.md"
    user_skill = user_root / "skills" / "demo" / "SKILL.md"
    project_skill.parent.mkdir(parents=True)
    user_skill.parent.mkdir(parents=True)
    project_skill.write_text("---\nname: demo\ndescription: project skill\n---\nbody", encoding="utf-8")
    user_skill.write_text("---\nname: demo\ndescription: user skill\n---\nbody", encoding="utf-8")

    skills = load_skills(workspace, user_root)

    assert skills["demo"].description == "project skill"
