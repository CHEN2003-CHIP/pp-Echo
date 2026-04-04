from __future__ import annotations

import json
from pathlib import Path

import pytest

from pp_agent.app import skills_runtime as skills_runtime_module
from pp_agent.app.extensions_runtime import load_executable_extensions
from pp_agent.app.skills_runtime import SkillRuntime
from pp_agent.cli.dispatcher import handle_command
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.hooks import RuntimeHooks
from pp_agent.skills import materializer as skill_materializer
from pp_agent.storage.settings import Settings
from pp_agent.tools.registry import ToolRegistry


def _write_skill(path: Path, *, name: str, description: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}", encoding="utf-8")


class TrackingMCPClient:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def initialize(self) -> None:
        self.events.append("initialize")

    def list_tools(self) -> list[dict]:
        self.events.append("list_tools")
        return [{"name": "echo", "description": "Echo tool", "input_schema": {"type": "object", "properties": {"message": {"type": "string"}}}}]

    def list_resources(self) -> list[dict]:
        self.events.append("list_resources")
        return [{"uri": "memo://notes", "name": "notes", "description": "Notes"}]

    def list_prompts(self) -> list[dict]:
        self.events.append("list_prompts")
        return [{"name": "summarize", "description": "Summarize"}]

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.events.append(f"call_tool:{name}")
        return {"content": f"{name}:{arguments.get('message', '')}", "payload": {}, "is_error": False}

    def read_resource(self, uri: str) -> dict:
        raise AssertionError(uri)

    def get_prompt(self, name: str, arguments: dict | None = None) -> dict:
        raise AssertionError(name)

    def close(self) -> None:
        self.events.append("close")


def test_skill_runtime_is_lazy_until_match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    _write_skill(
        tmp_path / ".pp-agent" / "skills" / "review-helper" / "SKILL.md",
        name="review-helper",
        description="Review pull requests carefully",
        body="Detailed review instructions",
    )
    runtime = SkillRuntime(
        workspace=tmp_path,
        user_root=tmp_path / "user-home",
        config=Settings.load(tmp_path).capabilities.skills,
    )
    calls: list[str] = []
    original = skill_materializer.materialize_skill

    def tracking_materialize(descriptor):
        calls.append(descriptor.name)
        return original(descriptor)

    monkeypatch.setattr(skill_materializer, "materialize_skill", tracking_materialize)
    monkeypatch.setattr(skills_runtime_module, "_materialize_skill", tracking_materialize)

    available = runtime.available_skills()
    assert list(available) == ["review-helper"]
    assert calls == []

    messages = runtime.transform_context(
        type(
            "State",
            (),
            {
                "messages": [ChatMessage(role="user", content=[TextPart(text="please use review-helper on this PR")], timestamp=0)],
            },
        )(),
        [ChatMessage(role="system", content=[TextPart(text="base")], timestamp=0)],
    )

    assert calls == ["review-helper"]
    assert len(messages) == 2
    assert "review-helper" in messages[1].content[0].text
    active = runtime.active_skills()
    assert active[0].name == "review-helper"
    assert active[0].source == "explicit_name"
    assert active[0].body_loaded is True


def test_skill_runtime_description_match_and_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    _write_skill(
        tmp_path / ".pp-agent" / "skills" / "review-helper" / "SKILL.md",
        name="review-helper",
        description="Review pull requests carefully",
        body="Review body",
    )
    settings = Settings.load(tmp_path)
    skill_runtime = SkillRuntime(
        workspace=tmp_path,
        user_root=settings.global_dir,
        config=settings.capabilities.skills,
    )
    agent = type("Agent", (), {"session_id": "session-1", "llm_client": type("Client", (), {"model": type("Model", (), {"model": "fake"})()})(), "state": type("State", (), {"model": type("Model", (), {"model": "fake"})()})()})()
    agent.skill_runtime = skill_runtime
    agent.mcp_runtime = None
    agent.extension_commands = None
    agent.tool_registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    agent.runtime_hooks = RuntimeHooks()
    agent.extension_registry = None
    agent.extension_resources = {}
    agent._extension_runtime = type("Runtime", (), {"close": lambda self: None})()
    agent._baseline_runtime_hooks_snapshot = agent.runtime_hooks.snapshot()

    result = handle_command(agent, "/skill use review-helper", tmp_path)
    assert result == "handled"
    assert [item.name for item in skill_runtime.active_skills()] == ["review-helper"]
    assert skill_runtime.active_skills()[0].source == "manual"

    skill_runtime.clear_active()
    skill_runtime.transform_context(
        type("State", (), {"messages": [ChatMessage(role="user", content=[TextPart(text="please review this pull request carefully")], timestamp=0)]})(),
        [ChatMessage(role="system", content=[TextPart(text="base")], timestamp=0)],
    )
    assert skill_runtime.active_skills()[0].source == "description_match"

    skill_runtime.clear_active()
    skill_runtime.transform_context(
        type("State", (), {"messages": [ChatMessage(role="user", content=[TextPart(text="can you review PR changes carefully before merge")], timestamp=0)]})(),
        [ChatMessage(role="system", content=[TextPart(text="base")], timestamp=0)],
    )
    assert skill_runtime.active_skills()[0].name == "review-helper"

    assert handle_command(agent, "/skill clear", tmp_path) == "handled"
    assert skill_runtime.active_skills() == []


def test_skill_colon_command_marks_explicit_command_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    _write_skill(
        tmp_path / ".pi" / "skills" / "review-helper" / "SKILL.md",
        name="review-helper",
        description="Review pull requests carefully",
        body="Review body",
    )
    settings = Settings.load(tmp_path)
    skill_runtime = SkillRuntime(
        workspace=tmp_path,
        user_root=settings.global_dir,
        config=settings.capabilities.skills,
    )
    agent = type("Agent", (), {"session_id": "session-1", "llm_client": type("Client", (), {"model": type("Model", (), {"model": "fake"})()})(), "state": type("State", (), {"model": type("Model", (), {"model": "fake"})()})()})()
    agent.skill_runtime = skill_runtime
    agent.mcp_runtime = None
    agent.extension_commands = None
    agent.tool_registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    agent.runtime_hooks = RuntimeHooks()
    agent.extension_registry = None
    agent.extension_resources = {}
    agent._extension_runtime = type("Runtime", (), {"close": lambda self: None})()
    agent._baseline_runtime_hooks_snapshot = agent.runtime_hooks.snapshot()

    result = handle_command(agent, "/skill:review-helper", tmp_path)

    assert result == "handled"
    active = skill_runtime.active_skills()
    assert active[0].name == "review-helper"
    assert active[0].source == "explicit_command"
    assert active[0].discovery_mode == "project_convention"


def test_mcp_runtime_is_lazy_until_list_call_or_natural_language_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "config.json").write_text(json.dumps({"capabilities": {"mcp": {"enable": True}}}), encoding="utf-8")
    (project_dir / "mcp.json").write_text(
        json.dumps({"servers": [{"name": "demo", "description": "Echo back user text and short summaries", "transport": "memory"}]}),
        encoding="utf-8",
    )
    settings = Settings.load(tmp_path)
    tool_registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    events: list[str] = []
    runtime = load_executable_extensions(
        tmp_path,
        settings=settings,
        tool_registry=tool_registry,
        runtime_hooks=RuntimeHooks(),
        transport_factory=lambda _config: TrackingMCPClient(events),
    )
    assert runtime.mcp_runtime is not None
    assert runtime.mcp_runtime.status()["discovered"] is False
    assert events == []

    messages = runtime.mcp_runtime.transform_context(
        type("State", (), {"messages": [ChatMessage(role="user", content=[TextPart(text="please echo this sentence back to me")], timestamp=0)]})(),
        [ChatMessage(role="system", content=[TextPart(text="base")], timestamp=0)],
    )

    assert len(messages) == 2
    assert "demo.echo" in messages[1].content[0].text
    assert events == ["initialize", "list_tools", "list_resources", "list_prompts"]
    assert tool_registry.execute("demo.echo", {"message": "hi"}).content == "echo:hi"


def test_mcp_call_command_supports_text_and_json_args(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "config.json").write_text(json.dumps({"capabilities": {"mcp": {"enable": True}}}), encoding="utf-8")
    (project_dir / "mcp.json").write_text(json.dumps({"servers": [{"name": "demo", "description": "Echo back user text", "transport": "memory"}]}), encoding="utf-8")
    settings = Settings.load(tmp_path)
    tool_registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    events: list[str] = []
    extension_runtime = load_executable_extensions(
        tmp_path,
        settings=settings,
        tool_registry=tool_registry,
        runtime_hooks=RuntimeHooks(),
        transport_factory=lambda _config: TrackingMCPClient(events),
    )
    agent = type("Agent", (), {"session_id": "session-1", "llm_client": type("Client", (), {"model": type("Model", (), {"model": "fake"})()})(), "state": type("State", (), {"model": type("Model", (), {"model": "fake"})()})()})()
    agent.mcp_runtime = extension_runtime.mcp_runtime
    agent.skill_runtime = None
    agent.extension_commands = None
    agent.tool_registry = tool_registry
    agent.runtime_hooks = RuntimeHooks()
    agent.extension_registry = extension_runtime.registry
    agent.extension_resources = extension_runtime.resources
    agent._extension_runtime = extension_runtime
    agent._baseline_runtime_hooks_snapshot = agent.runtime_hooks.snapshot()

    assert handle_command(agent, "/mcp call demo.echo hello world", tmp_path) == "handled"
    assert "call_tool:echo" in events
    events.clear()

    assert handle_command(agent, '/mcp call demo.echo {"message":"json"}', tmp_path) == "handled"
    assert "call_tool:echo" in events


class TrackingFetchMCPClient:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def initialize(self) -> None:
        self.events.append("initialize")

    def list_tools(self) -> list[dict]:
        self.events.append("list_tools")
        return [
            {"name": "fetch_markdown", "description": "Fetch webpage markdown", "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}}},
            {"name": "fetch_readable", "description": "Fetch readable article", "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}}},
        ]

    def list_resources(self) -> list[dict]:
        self.events.append("list_resources")
        return []

    def list_prompts(self) -> list[dict]:
        self.events.append("list_prompts")
        return []

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.events.append(f"call_tool:{name}")
        return {"content": f"{name}:{arguments.get('url', '')}", "payload": {}, "is_error": False}

    def read_resource(self, uri: str) -> dict:
        raise AssertionError(uri)

    def get_prompt(self, name: str, arguments: dict | None = None) -> dict:
        raise AssertionError(name)

    def close(self) -> None:
        self.events.append("close")


def test_mcp_runtime_matches_chinese_web_request_to_fetch_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "config.json").write_text(json.dumps({"capabilities": {"mcp": {"enable": True}}}), encoding="utf-8")
    (project_dir / "mcp.json").write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "fetch",
                        "description": "Community standard MCP server for fetching web pages as HTML, text, markdown, JSON, and readable article content.",
                        "transport": "memory",
                        "intent_tags": ["web", "url", "fetch", "article", "缃戦〉", "缃戠珯", "鏂伴椈", "鎶撳彇", "閾炬帴"],
                        "auto_match_examples": ["鑾峰彇缃戦〉鍐呭", "鎬荤粨杩欎釜閾炬帴", "fetch this url"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings.load(tmp_path)
    tool_registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    events: list[str] = []
    runtime = load_executable_extensions(
        tmp_path,
        settings=settings,
        tool_registry=tool_registry,
        runtime_hooks=RuntimeHooks(),
        transport_factory=lambda _config: TrackingFetchMCPClient(events),
    )

    messages = runtime.mcp_runtime.transform_context(
        type("State", (), {"messages": [ChatMessage(role="user", content=[TextPart(text="鑾峰彇 https://example.com 杩欎釜缃戦〉鍐呭锛屽苟绠€瑕佸憡璇夋垜閲嶇偣")], timestamp=0)]})(),
        [ChatMessage(role="system", content=[TextPart(text="base")], timestamp=0)],
    )

    assert len(messages) == 2
    system_text = messages[1].content[0].text
    assert "fetch.fetch_markdown" in system_text
    assert "fetch.fetch_readable" in system_text
    assert "Do not say you cannot access the internet" in system_text
    assert runtime.mcp_runtime.status()["last_match"]["matched_server"] == "fetch"
    assert runtime.mcp_runtime.status()["last_match"]["matched_by"] in {"tags", "url_intent"}
    assert events == ["initialize", "list_tools", "list_resources", "list_prompts"]


def test_mcp_runtime_matches_url_only_and_does_not_match_local_file_requests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "config.json").write_text(json.dumps({"capabilities": {"mcp": {"enable": True}}}), encoding="utf-8")
    (project_dir / "mcp.json").write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "fetch",
                        "description": "Fetch webpages and links.",
                        "transport": "memory",
                        "intent_tags": ["web", "url", "缃戦〉", "閾炬帴"],
                    },
                    {
                        "name": "demo",
                        "description": "Echo local text only.",
                        "transport": "memory",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings.load(tmp_path)
    tool_registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    events: list[str] = []
    runtime = load_executable_extensions(
        tmp_path,
        settings=settings,
        tool_registry=tool_registry,
        runtime_hooks=RuntimeHooks(),
        transport_factory=lambda _config: TrackingFetchMCPClient(events),
    )

    url_only = runtime.mcp_runtime.transform_context(
        type("State", (), {"messages": [ChatMessage(role="user", content=[TextPart(text="https://example.com")], timestamp=0)]})(),
        [ChatMessage(role="system", content=[TextPart(text="base")], timestamp=0)],
    )
    assert len(url_only) == 2
    assert runtime.mcp_runtime.status()["last_match"]["matched_server"] == "fetch"

    events.clear()
    no_match = runtime.mcp_runtime.transform_context(
        type("State", (), {"messages": [ChatMessage(role="user", content=[TextPart(text="甯垜鐪?src 鐩綍")], timestamp=0)]})(),
        [ChatMessage(role="system", content=[TextPart(text="base")], timestamp=0)],
    )
    assert len(no_match) == 1
    assert runtime.mcp_runtime.status()["last_match"] == {}
    assert events == []
