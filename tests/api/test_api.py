from __future__ import annotations

from pathlib import Path

import pytest

from pp_agent import api
from pp_agent.api import sdk
from pp_agent.prompts.loader import load_prompt_templates
from pp_agent.skills.loader import load_skills
from pp_agent.skills.materializer import materialize_skill
from pp_agent.storage.settings import SkillCapabilityConfig


def test_api_run_returns_payload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        sdk,
        "run",
        lambda prompt, workspace, **kwargs: {
            "session_id": "session-1",
            "assistant": "",
            "pending_plan_token": None,
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


def test_prompt_loader_supports_extension_contributed_paths_with_lower_precedence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    user_root = tmp_path / "user"
    extension_root = tmp_path / "ext-prompts"
    (workspace / ".pp-agent" / "prompts").mkdir(parents=True)
    extension_root.mkdir(parents=True)
    (workspace / ".pp-agent" / "prompts" / "system.md").write_text("project", encoding="utf-8")
    (extension_root / "system.md").write_text("extension", encoding="utf-8")

    templates = load_prompt_templates(workspace, user_root, extra_paths=[extension_root])

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
    assert skills["demo"].path == project_skill
    assert skills["demo"].origin_type == "project"


def test_skill_loader_supports_custom_directory_priority_and_filters(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    user_root = tmp_path / "user"
    custom_a = tmp_path / "custom-a"
    custom_b = tmp_path / "custom-b"
    for root, description in [
        (workspace / ".pp-agent" / "skills" / "demo", "project"),
        (user_root / "skills" / "demo", "user"),
        (custom_b / "demo", "custom-b"),
        (custom_a / "demo", "custom-a"),
        (custom_a / "skip-me", "skip"),
    ]:
        root.mkdir(parents=True, exist_ok=True)
        root.joinpath("SKILL.md").write_text(f"---\nname: {root.name}\ndescription: {description}\n---\nbody", encoding="utf-8")

    skills = load_skills(
        workspace,
        user_root,
        config=SkillCapabilityConfig(
            custom_directories=[str(custom_a), str(custom_b)],
            include=["demo", "skip*"],
            ignored=["skip*"],
        ),
    )

    assert list(skills) == ["demo"]
    assert skills["demo"].description == "custom-a"
    assert skills["demo"].path == custom_a / "demo" / "SKILL.md"
    assert skills["demo"].origin_type == "custom"
    assert skills["demo"].root_name == "custom-a"
    assert skills["demo"].discovery_mode == "custom_directory"
    assert skills["demo"].discovery_root == str(custom_a)


def test_skill_loader_prefers_pi_style_ancestor_roots_over_legacy_project_root(tmp_path: Path) -> None:
    workspace = tmp_path / "repo" / "apps" / "feature"
    user_root = tmp_path / "user"
    legacy_skill = workspace / ".pp-agent" / "skills" / "demo" / "SKILL.md"
    nearest_pi_skill = workspace / ".pi" / "skills" / "demo" / "SKILL.md"
    ancestor_agents_skill = tmp_path / "repo" / ".agents" / "skills" / "demo" / "SKILL.md"
    for path, description in [
        (legacy_skill, "legacy project"),
        (nearest_pi_skill, "nearest pi"),
        (ancestor_agents_skill, "ancestor agents"),
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: demo\ndescription: {description}\n---\nbody", encoding="utf-8")

    skills = load_skills(workspace, user_root)

    assert skills["demo"].description == "nearest pi"
    assert skills["demo"].path == nearest_pi_skill
    assert skills["demo"].origin_type == "project"
    assert skills["demo"].root_name == "pi_skills"
    assert skills["demo"].discovery_mode == "project_convention"
    assert skills["demo"].discovery_root == str(workspace.resolve())


def test_skill_body_is_materialized_on_demand_and_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    user_root = tmp_path / "user"
    skill_path = workspace / ".pp-agent" / "skills" / "demo" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("---\nname: demo\ndescription: project skill\n---\nbody", encoding="utf-8")

    read_count = 0
    original_read_text = Path.read_text

    def counting_read_text(self: Path, *args, **kwargs) -> str:
        nonlocal read_count
        read_count += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    skills = load_skills(workspace, user_root)

    assert read_count == 0

    descriptor = skills["demo"]
    assert materialize_skill(descriptor) == "body"
    assert read_count == 1

    assert descriptor.body == "body"
    assert materialize_skill(descriptor) == "body"
    assert read_count == 1


def test_api_capability_helpers_forward_to_sdk(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sdk, "list_capabilities", lambda workspace, **kwargs: [{"name": "demo"}])
    monkeypatch.setattr(sdk, "get_capability", lambda workspace, **kwargs: {"name": kwargs["name"]})
    monkeypatch.setattr(sdk, "reload_capabilities", lambda workspace, **kwargs: [{"name": "demo"}, {"name": "reload"}])

    assert api.list_capabilities(workspace=tmp_path) == [{"name": "demo"}]
    assert api.get_capability(workspace=tmp_path, kind="skill", name="demo") == {"name": "demo"}
    assert api.reload_capabilities(workspace=tmp_path)[-1]["name"] == "reload"
