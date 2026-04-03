from __future__ import annotations

import json
from pathlib import Path

from pp_agent.app.bootstrap import reload_runtime_extensions
from pp_agent.app.extensions_runtime import discover_extension_resource_roots, load_executable_extensions
from pp_agent.cli.dispatcher import handle_command
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.emitter import LifecycleEmitter
from pp_agent.runtime.hooks import RuntimeHooks
from pp_agent.runtime.state import AgentEvent
from pp_agent.storage.settings import Settings
from pp_agent.tools.registry import ToolRegistry


def _write_extension(root: Path, *, name: str, description: str, source: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "EXTENSION.json").write_text(
        json.dumps(
            {
                "name": name,
                "description": description,
                "entrypoint": "extension.py",
                "provides": ["tools", "commands", "hooks"],
            }
        ),
        encoding="utf-8",
    )
    (root / "extension.py").write_text(source, encoding="utf-8")


class TrackingMCPClient:
    def initialize(self) -> None:
        return None

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": "echo",
                "description": "Echo tool",
                "input_schema": {"type": "object", "properties": {"message": {"type": "string"}}},
            }
        ]

    def list_resources(self) -> list[dict]:
        return [{"uri": "memo://notes", "name": "notes", "description": "Notes"}]

    def list_prompts(self) -> list[dict]:
        return [{"name": "summarize", "description": "Summarize"}]

    def call_tool(self, name: str, arguments: dict) -> dict:
        return {"content": f"{name}:{arguments.get('message', '')}", "payload": {"echoed": arguments}, "is_error": False}

    def read_resource(self, uri: str) -> dict:
        return {"content": uri, "payload": {}, "is_error": False}

    def get_prompt(self, name: str, arguments: dict | None = None) -> dict:
        return {"content": name, "payload": {}, "is_error": False}

    def close(self) -> None:
        return None


def test_executable_extensions_register_tools_commands_and_hooks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    project_dir = tmp_path / ".pp-agent" / "extensions" / "demo"
    _write_extension(
        project_dir,
        name="demo",
        description="Demo extension",
        source="""
from pp_agent.domain import ChatMessage, TextPart

def register(api):
    api.register_tool(
        name="demo_echo",
        description="Echo from extension",
        parameters={"type": "object", "properties": {"message": {"type": "string"}}},
        handler=lambda workspace, arguments: f"{workspace.name}:{arguments.get('message', '')}",
    )
    api.register_command("hello", lambda agent, args, workspace: setattr(agent, 'last_extension_command', f'{workspace.name}:{args}') or 'handled')
    api.on_context_built(lambda state, messages: [messages[0], ChatMessage(role='system', content=[TextPart(text='extension-note')], timestamp=0), *messages[1:]])
""",
    )

    settings = Settings.load(tmp_path)
    tool_registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    runtime_hooks = RuntimeHooks()

    loaded = load_executable_extensions(tmp_path, settings=settings, tool_registry=tool_registry, runtime_hooks=runtime_hooks)

    spec = tool_registry.get_spec("demo_echo")
    result = tool_registry.execute("demo_echo", {"message": "hi"})
    messages = runtime_hooks.transform_context(
        type("State", (), {"queued_messages": [], "pending_plan_token": None})(),
        [ChatMessage(role="system", content=[TextPart(text="base")], timestamp=0)],
    )

    assert spec.description == "Echo from extension"
    assert result.content == f"{tmp_path.name}:hi"
    assert loaded.registry.get("demo").status == "loaded"
    assert loaded.registry.get("demo").loaded_commands == ["hello"]
    assert loaded.commands.list_names() == ["hello"]
    assert len(messages) == 2


def test_extension_commands_dispatch_through_cli_handler(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    extension_dir = tmp_path / ".pp-agent" / "extensions" / "demo"
    _write_extension(
        extension_dir,
        name="demo",
        description="Demo extension",
        source="""
def register(api):
    api.register_command("hello", lambda agent, args, workspace: setattr(agent, 'handled_value', f'{workspace.name}:{args}') or 'handled')
""",
    )
    settings = Settings.load(tmp_path)
    tool_registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    runtime_hooks = RuntimeHooks()
    loaded = load_executable_extensions(tmp_path, settings=settings, tool_registry=tool_registry, runtime_hooks=runtime_hooks)
    agent = type("Agent", (), {"session_id": "session-1", "llm_client": None, "state": None})()
    agent.extension_commands = loaded.commands

    result = handle_command(agent, "/hello world", tmp_path)

    assert result == "handled"
    assert agent.handled_value == f"{tmp_path.name}:world"


def test_mcp_adapter_registers_runtime_tools_when_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "config.json").write_text(json.dumps({"capabilities": {"mcp": {"enable": True}}}), encoding="utf-8")
    (project_dir / "mcp.json").write_text(json.dumps({"servers": [{"name": "demo", "transport": "memory"}]}), encoding="utf-8")
    settings = Settings.load(tmp_path)
    tool_registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    runtime_hooks = RuntimeHooks()

    loaded = load_executable_extensions(
        tmp_path,
        settings=settings,
        tool_registry=tool_registry,
        runtime_hooks=runtime_hooks,
        transport_factory=lambda _config: TrackingMCPClient(),
    )

    assert loaded.mcp_runtime is not None
    assert loaded.mcp_runtime.status()["discovered"] is False
    payload = loaded.mcp_runtime.list_servers()
    spec = tool_registry.get_spec("demo.echo")
    result = tool_registry.execute("demo.echo", {"message": "hello"})

    assert payload == [
        {
            "server": "demo",
            "description": "",
            "tool_count": 1,
            "resource_count": 1,
            "prompt_count": 1,
            "session_active": True,
            "tools": ["demo.echo"],
        }
    ]
    assert spec.description == "Echo tool"
    assert result.content == "echo:hello"
    assert loaded.registry.get("mcp_adapter").status == "loaded"
    assert loaded.registry.get("mcp_adapter").loaded_tools == ["demo.echo"]
    assert "demo.notes" in loaded.registry.get("mcp_adapter").loaded_resources


def test_reload_command_refreshes_extensions_and_runs_unload_callbacks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    extension_dir = tmp_path / ".pp-agent" / "extensions" / "demo"
    marker = tmp_path / "unload.txt"
    _write_extension(
        extension_dir,
        name="demo",
        description="Demo extension",
        source=f"""
def register(api):
    api.register_tool(
        name=\"demo_echo\",
        description=\"Echo v1\",
        parameters={{\"type\": \"object\", \"properties\": {{\"message\": {{\"type\": \"string\"}}}}}},
        handler=lambda workspace, arguments: f\"v1:{{arguments.get('message', '')}}\",
    )
    api.register_command(\"hello\", lambda agent, args, workspace: setattr(agent, 'handled_value', f'v1:{{args}}') or 'handled')
    api.on_unload(lambda: open(r\"{marker}\", \"a\", encoding=\"utf-8\").write(\"v1\\n\"))
""",
    )
    settings = Settings.load(tmp_path)
    tool_registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    runtime_hooks = RuntimeHooks()
    baseline_snapshot = runtime_hooks.snapshot()
    loaded = load_executable_extensions(tmp_path, settings=settings, tool_registry=tool_registry, runtime_hooks=runtime_hooks)
    agent = type("Agent", (), {"session_id": "session-1", "llm_client": None, "state": None})()
    agent.tool_registry = tool_registry
    agent.runtime_hooks = runtime_hooks
    agent.extension_registry = loaded.registry
    agent.extension_commands = loaded.commands
    agent.extension_resources = loaded.resources
    agent._extension_runtime = loaded
    agent._baseline_runtime_hooks_snapshot = baseline_snapshot

    assert handle_command(agent, "/hello first", tmp_path) == "handled"
    assert agent.handled_value == "v1:first"
    assert tool_registry.execute("demo_echo", {"message": "hi"}).content == "v1:hi"

    _write_extension(
        extension_dir,
        name="demo",
        description="Demo extension",
        source=f"""
def register(api):
    api.register_tool(
        name=\"demo_echo\",
        description=\"Echo v2\",
        parameters={{\"type\": \"object\", \"properties\": {{\"message\": {{\"type\": \"string\"}}}}}},
        handler=lambda workspace, arguments: f\"v2:{{arguments.get('message', '')}}\",
    )
    api.register_command(\"hello\", lambda agent, args, workspace: setattr(agent, 'handled_value', f'v2:{{args}}') or 'handled')
    api.on_unload(lambda: open(r\"{marker}\", \"a\", encoding=\"utf-8\").write(\"v2\\n\"))
""",
    )

    assert handle_command(agent, "/reload", tmp_path) == "handled"
    assert marker.read_text(encoding="utf-8") == "v1\n"
    assert handle_command(agent, "/hello second", tmp_path) == "handled"
    assert agent.handled_value == "v2:second"
    assert tool_registry.execute("demo_echo", {"message": "hi"}).content == "v2:hi"

    payload = reload_runtime_extensions(agent, tmp_path)
    assert payload["extension_count"] == 1


def test_extension_on_api_bridges_runtime_and_lifecycle_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    marker = tmp_path / "events.txt"
    extension_dir = tmp_path / ".pp-agent" / "extensions" / "demo"
    _write_extension(
        extension_dir,
        name="demo",
        description="Demo extension",
        source=f"""
from pp_agent.runtime.hooks import BeforeToolCallDecision

def register(api):
    api.on("context_built", lambda state, messages: messages + [messages[0].model_copy()])
    api.on("tool_call", lambda state, call, registry: BeforeToolCallDecision(action="block", message="blocked"))
    api.on("session_start", lambda event: open(r"{marker}", "a", encoding="utf-8").write(event.type + \"\\n\"))
""",
    )
    settings = Settings.load(tmp_path)
    tool_registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    runtime_hooks = RuntimeHooks()
    loaded = load_executable_extensions(tmp_path, settings=settings, tool_registry=tool_registry, runtime_hooks=runtime_hooks)
    emitter = LifecycleEmitter()
    runtime_hooks.register_with_lifecycle(emitter)

    messages = runtime_hooks.transform_context(
        type("State", (), {"queued_messages": [], "pending_plan_token": None})(),
        [ChatMessage(role="system", content=[TextPart(text="base")], timestamp=0)],
    )
    decision = runtime_hooks.before_tool_call(
        type("State", (), {"queued_messages": [], "pending_plan_token": None})(),
        type("Call", (), {"name": "demo", "arguments": {}})(),
        tool_registry,
    )
    emitter.emit(AgentEvent(type="session_start"))
    binding = loaded.registry.get("demo")

    assert len(messages) == 2
    assert decision.action == "block"
    assert decision.message == "blocked"
    assert marker.read_text(encoding="utf-8") == "session_start\n"
    assert binding is not None
    assert binding.event_counts["context_built"] == 1
    assert binding.event_counts["tool_call"] == 1
    assert binding.event_counts["session_start"] == 1


def test_extension_resources_discover_adds_skill_roots_and_refreshes_on_reload(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    extension_dir = tmp_path / ".pp-agent" / "extensions" / "demo"
    skill_root_a = tmp_path / "ext-skills-a"
    skill_root_b = tmp_path / "ext-skills-b"
    for root, name in [(skill_root_a, "ext_a"), (skill_root_b, "ext_b")]:
        skill_path = root / name / "SKILL.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(f"---\nname: {name}\ndescription: {name}\n---\nbody", encoding="utf-8")
    _write_extension(
        extension_dir,
        name="demo",
        description="Demo extension",
        source=f"""
def register(api):
    api.on("resources_discover", lambda event: {{"skill_paths": [r"{skill_root_a}"], "prompt_paths": [], "theme_paths": []}})
""",
    )
    settings = Settings.load(tmp_path)
    tool_registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    runtime_hooks = RuntimeHooks()
    baseline_snapshot = runtime_hooks.snapshot()
    loaded = load_executable_extensions(tmp_path, settings=settings, tool_registry=tool_registry, runtime_hooks=runtime_hooks)
    contributions = discover_extension_resource_roots(loaded, tmp_path, reason="startup")
    agent = type("Agent", (), {"session_id": "session-1", "llm_client": None, "state": None})()
    agent.tool_registry = tool_registry
    agent.runtime_hooks = runtime_hooks
    agent.extension_registry = loaded.registry
    agent.extension_commands = loaded.commands
    agent.extension_resources = loaded.resources
    agent.extension_resource_roots = contributions
    agent._extension_runtime = loaded
    agent._baseline_runtime_hooks_snapshot = baseline_snapshot

    payload = reload_runtime_extensions(agent, tmp_path)
    binding = agent.extension_registry.get("demo")

    assert payload["skill_count"] == 1
    assert "ext_a" in agent.skill_runtime.available_skills()
    assert binding is not None
    assert binding.resource_roots["skill_paths"] == [str(skill_root_a.resolve())]

    _write_extension(
        extension_dir,
        name="demo",
        description="Demo extension",
        source=f"""
def register(api):
    api.on("resources_discover", lambda event: {{"skill_paths": [r"{skill_root_b}"], "prompt_paths": [], "theme_paths": []}})
""",
    )

    payload = reload_runtime_extensions(agent, tmp_path)
    binding = agent.extension_registry.get("demo")

    assert payload["skill_count"] == 1
    assert "ext_b" in agent.skill_runtime.available_skills()
    assert "ext_a" not in agent.skill_runtime.available_skills()
    assert binding is not None
    assert binding.resource_roots["skill_paths"] == [str(skill_root_b.resolve())]
