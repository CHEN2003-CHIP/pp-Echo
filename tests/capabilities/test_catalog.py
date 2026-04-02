from __future__ import annotations

import json
from pathlib import Path

import pytest

from pp_agent.app.bootstrap import create_capability_catalog
from pp_agent.capabilities import CapabilityCatalog, CapabilityDescriptor
from pp_agent.skills import materializer as skill_materializer
from pp_agent.tools.shell_tool import PowerShellTool


class StaticProvider:
    def __init__(self, descriptors: list[CapabilityDescriptor]) -> None:
        self._descriptors = descriptors

    def discover(self) -> list[CapabilityDescriptor]:
        return [item.model_copy(deep=True) for item in self._descriptors]


class FailingProvider:
    def discover(self) -> list[CapabilityDescriptor]:
        raise RuntimeError("provider failed")


def test_create_capability_catalog_discovers_skills_and_builtin_tools_without_materializing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    skill_path = tmp_path / ".pp-agent" / "skills" / "demo" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("---\nname: demo\ndescription: project skill\n---\nbody", encoding="utf-8")

    def fail_if_materialized(_descriptor):
        raise AssertionError("skill body should not be materialized")

    def fail_if_instantiated(self, workspace, default_timeout_seconds: int = 30):
        raise AssertionError("tool should not be instantiated")

    monkeypatch.setattr(skill_materializer, "materialize_skill", fail_if_materialized)
    monkeypatch.setattr(PowerShellTool, "__init__", fail_if_instantiated)

    catalog = create_capability_catalog(tmp_path)
    keys = {(item.kind, item.name) for item in catalog.list()}

    assert ("skill", "demo") in keys
    assert ("builtin_tool", "run_shell") in keys


def test_capability_catalog_list_and_get_are_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    catalog = create_capability_catalog(tmp_path)

    expected_order = [item.model_dump(mode="json") for item in catalog.list()]

    assert [item.model_dump(mode="json") for item in catalog.list()] == expected_order
    assert [item.model_dump(mode="json") for item in catalog.list()] == expected_order

    builtin_tools = catalog.list(kind="builtin_tool")
    assert [item.name for item in builtin_tools] == [
        "read_file",
        "write_file",
        "edit_file",
        "preview_pending_action",
        "approve_pending_action",
        "reject_pending_action",
        "list_pending_actions",
        "list_files",
        "search_text",
        "grep_code",
        "git_status",
        "git_diff_worktree",
        "run_shell",
    ]
    assert catalog.get("builtin_tool", "run_shell").source == "builtin:run_shell"


def test_capability_catalog_refresh_discovers_new_project_skill_and_keeps_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    catalog = create_capability_catalog(tmp_path)
    initial_builtin_order = [item.name for item in catalog.list(kind="builtin_tool")]

    skill_path = tmp_path / ".pp-agent" / "skills" / "new-skill" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("---\nname: new_skill\ndescription: new project skill\n---\nbody", encoding="utf-8")

    catalog.refresh()

    assert [item.name for item in catalog.list(kind="builtin_tool")] == initial_builtin_order
    assert [item.name for item in catalog.list(kind="skill")] == ["new_skill"]


def test_capability_catalog_refresh_is_atomic_on_provider_failure() -> None:
    provider = StaticProvider(
        [
            CapabilityDescriptor(
                kind="skill",
                name="demo",
                description="demo",
                source="skill:demo",
                metadata={"origin": "skill"},
            )
        ]
    )
    catalog = CapabilityCatalog([provider])

    catalog._providers = [provider, FailingProvider()]

    with pytest.raises(RuntimeError, match="provider failed"):
        catalog.refresh()

    assert [(item.kind, item.name) for item in catalog.list()] == [("skill", "demo")]


def test_capability_catalog_rejects_duplicate_keys() -> None:
    duplicate = CapabilityDescriptor(
        kind="skill",
        name="demo",
        description="demo",
        source="skill:demo",
        metadata={"origin": "skill"},
    )

    with pytest.raises(ValueError, match="Duplicate capability discovered"):
        CapabilityCatalog([StaticProvider([duplicate]), StaticProvider([duplicate])])


def test_capability_metadata_is_lightweight_and_serializable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    skill_path = tmp_path / ".pp-agent" / "skills" / "demo" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("---\nname: demo\ndescription: project skill\n---\nbody", encoding="utf-8")

    catalog = create_capability_catalog(tmp_path)

    for item in catalog.list():
        json.dumps(item.metadata)
        assert "body" not in item.metadata
        assert "tool" not in item.metadata
        assert "registry" not in item.metadata
