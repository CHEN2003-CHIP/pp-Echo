from __future__ import annotations

import json
from pathlib import Path

import pytest

from pp_agent.app.bootstrap import create_capability_catalog, create_capability_catalog_with_mcp
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


class TrackingMCPClient:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def initialize(self) -> None:
        self._events.append("demo:initialize")

    def list_tools(self) -> list[dict]:
        self._events.append("demo:list_tools")
        return [{"name": "echo", "description": "Echo tool", "input_schema": {"type": "object"}}]

    def list_resources(self) -> list[dict]:
        self._events.append("demo:list_resources")
        return [{"uri": "memo://notes", "name": "notes", "description": "Notes"}]

    def list_prompts(self) -> list[dict]:
        self._events.append("demo:list_prompts")
        return [{"name": "summarize", "description": "Summarize prompt"}]

    def call_tool(self, name: str, arguments: dict) -> dict:
        raise AssertionError(f"unexpected tool execution: {name} {arguments}")

    def read_resource(self, uri: str) -> dict:
        raise AssertionError(f"unexpected resource read: {uri}")

    def get_prompt(self, name: str, arguments: dict | None = None) -> dict:
        raise AssertionError(f"unexpected prompt fetch: {name} {arguments}")

    def close(self) -> None:
        self._events.append("demo:close")


def _write_mcp_config(tmp_path: Path, payload: dict | None = None) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "mcp.json").write_text(
        json.dumps(payload or {"servers": [{"name": "demo", "transport": "memory"}]}),
        encoding="utf-8",
    )


def _write_extension_descriptor(path: Path, *, name: str, description: str, entrypoint: str = "extension.py", provides: list[str] | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "EXTENSION.json").write_text(
        json.dumps(
            {
                "name": name,
                "description": description,
                "entrypoint": entrypoint,
                "provides": provides or ["hooks"],
            }
        ),
        encoding="utf-8",
    )


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
        "preview_safe_rewind",
        "execute_safe_rewind",
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


def test_create_capability_catalog_does_not_connect_mcp_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    _write_mcp_config(tmp_path)

    catalog = create_capability_catalog(tmp_path)

    assert catalog.list(kind="mcp_tool") == []
    assert catalog.list(kind="mcp_resource") == []
    assert catalog.list(kind="mcp_prompt") == []


def test_create_capability_catalog_with_mcp_discovers_mcp_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    _write_mcp_config(tmp_path)
    events: list[str] = []

    catalog = create_capability_catalog_with_mcp(
        tmp_path,
        transport_factory=lambda _config: TrackingMCPClient(events),
    )

    assert [item.name for item in catalog.list(kind="mcp_tool")] == ["demo.echo"]
    assert [item.name for item in catalog.list(kind="mcp_resource")] == ["demo.notes"]
    assert [item.name for item in catalog.list(kind="mcp_prompt")] == ["demo.summarize"]
    assert [item.name for item in catalog.list(kind="extension")] == ["mcp_adapter"]
    assert catalog.get("extension", "mcp_adapter").status == "loaded"
    assert catalog.get("mcp_tool", "demo.echo").metadata["server_name"] == "demo"
    assert catalog.get("mcp_resource", "demo.notes").metadata["uri"] == "memo://notes"
    assert events == [
        "demo:initialize",
        "demo:list_tools",
        "demo:list_resources",
        "demo:list_prompts",
    ]


def test_capability_catalog_uses_configured_skill_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "config.json").write_text(
        json.dumps(
            {
                "capabilities": {
                    "skills": {
                        "include": ["keep*"],
                        "ignored": ["skip*"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    for name in ["keep-demo", "skip-demo"]:
        path = project_dir / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: {name}\ndescription: {name}\n---\nbody", encoding="utf-8")

    catalog = create_capability_catalog(tmp_path)

    assert [item.name for item in catalog.list(kind="skill")] == ["keep-demo"]


def test_capability_catalog_reload_picks_up_mcp_config_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "config.json").write_text(json.dumps({"capabilities": {"mcp": {"enable": True}}}), encoding="utf-8")
    _write_mcp_config(tmp_path, {"servers": [{"name": "demo", "transport": "memory"}]})
    events: list[str] = []
    catalog = create_capability_catalog(tmp_path, transport_factory=lambda _config: TrackingMCPClient(events))

    assert [item.name for item in catalog.list(kind="mcp_tool")] == ["demo.echo"]

    _write_mcp_config(tmp_path, {"servers": [{"name": "demo", "transport": "memory"}, {"name": "demo2", "transport": "memory"}]})
    catalog.reload()

    assert [item.name for item in catalog.list(kind="mcp_tool")] == ["demo.echo", "demo2.echo"]
    assert "demo:close" in events


def test_extension_discovery_prefers_custom_and_manifest_project_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    custom_root = tmp_path / "custom-extensions"
    user_root = tmp_path / "user-home" / "extensions" / "demo"
    manifest_root = project_dir / "manifest-ext" / "demo"
    conventional_project_root = project_dir / "extensions" / "demo"
    _write_extension_descriptor(custom_root / "demo", name="demo", description="custom extension")
    _write_extension_descriptor(user_root, name="demo", description="user extension")
    _write_extension_descriptor(manifest_root, name="demo", description="manifest extension")
    _write_extension_descriptor(conventional_project_root, name="demo", description="conventional project extension")
    (project_dir / "resources.json").write_text(json.dumps({"extensions": ["manifest-ext"]}), encoding="utf-8")
    (project_dir / "config.json").write_text(
        json.dumps({"capabilities": {"extensions": {"custom_directories": [str(custom_root)]}}}),
        encoding="utf-8",
    )

    catalog = create_capability_catalog(tmp_path)

    extension = catalog.get("extension", "demo")
    assert extension.description == "custom extension"
    assert extension.origin_type == "custom"
    assert extension.metadata["root_name"] == "custom-extensions"



def test_extension_catalog_reload_discovers_new_extension(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    catalog = create_capability_catalog(tmp_path)
    assert catalog.list(kind="extension") == []

    _write_extension_descriptor(tmp_path / ".pp-agent" / "extensions" / "demo", name="demo", description="project extension")
    catalog.reload()

    extension = catalog.get("extension", "demo")
    assert extension.name == "demo"
    assert extension.status == "discovered"
    assert extension.metadata["entrypoint"] == "extension.py"



def test_skill_and_extension_metadata_include_origin_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "resources.json").write_text(json.dumps({"skills": ["manifest-skills"], "extensions": ["manifest-ext"]}), encoding="utf-8")
    skill_path = project_dir / "manifest-skills" / "demo" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text("---\nname: demo\ndescription: manifest skill\n---\nbody", encoding="utf-8")
    _write_extension_descriptor(project_dir / "manifest-ext" / "demo-ext", name="demo_ext", description="manifest extension")

    catalog = create_capability_catalog(tmp_path)

    skill = catalog.get("skill", "demo")
    extension = catalog.get("extension", "demo_ext")
    assert skill.origin_type == "project"
    assert skill.metadata["declared_by_manifest"] is True
    assert skill.metadata["discovery_root"] == str(project_dir / "manifest-skills")
    assert skill.metadata["discovery_mode"] == "legacy_project"
    assert extension.origin_type == "project"
    assert extension.metadata["declared_by_manifest"] is True
    assert extension.metadata["event_counts"] == {}
    assert extension.metadata["resource_roots"] == {}

