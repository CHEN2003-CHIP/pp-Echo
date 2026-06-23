from __future__ import annotations

import json
from pathlib import Path

from pp_agent.app.bootstrap import create_mcp_manager
from pp_agent.mcp.config import load_mcp_config, load_mcp_server_configs


class TrackingClient:
    def __init__(self) -> None:
        self.initialize_count = 0
        self.list_tools_count = 0
        self.list_resources_count = 0
        self.list_prompts_count = 0
        self.call_tool_count = 0
        self.read_resource_count = 0

    def initialize(self) -> None:
        self.initialize_count += 1

    def list_tools(self) -> list[dict]:
        self.list_tools_count += 1
        return [
            {"name": "alpha", "description": "Alpha"},
            {"name": "beta", "description": "Beta"},
        ]

    def list_resources(self) -> list[dict]:
        self.list_resources_count += 1
        return [{"uri": "memo://a", "name": "A"}]

    def list_prompts(self) -> list[dict]:
        self.list_prompts_count += 1
        return [{"name": "prompt-a", "description": "Prompt A"}]

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.call_tool_count += 1
        return {"content": "tool"}

    def read_resource(self, uri: str) -> dict:
        self.read_resource_count += 1
        return {"content": "resource"}

    def get_prompt(self, name: str, arguments: dict | None = None) -> dict:
        return {"content": "prompt"}

    def close(self) -> None:
        return None


def _write_config(tmp_path: Path, payload: dict | None = None) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "mcp.json").write_text(json.dumps(payload or {"servers": [{"name": "demo"}]}), encoding="utf-8")


def test_mcp_discovery_returns_metadata_only_and_does_not_execute(tmp_path: Path) -> None:
    _write_config(tmp_path)
    client = TrackingClient()
    manager = create_mcp_manager(tmp_path, transport_factory=lambda _config: client)

    tools = manager.list_mcp_tools("demo")
    resources = manager.list_mcp_resources("demo")
    prompts = manager.list_mcp_prompts("demo")

    assert [item.name for item in tools] == ["alpha", "beta"]
    assert [item.uri for item in resources] == ["memo://a"]
    assert [item.name for item in prompts] == ["prompt-a"]
    assert client.initialize_count == 1
    assert client.call_tool_count == 0
    assert client.read_resource_count == 0


def test_mcp_discovery_order_is_stable(tmp_path: Path) -> None:
    _write_config(tmp_path)
    client = TrackingClient()
    manager = create_mcp_manager(tmp_path, transport_factory=lambda _config: client)

    first = [item.name for item in manager.list_mcp_tools("demo")]
    second = [item.name for item in manager.list_mcp_tools("demo")]

    assert first == ["alpha", "beta"]
    assert second == ["alpha", "beta"]
    assert client.initialize_count == 1
    assert client.list_tools_count == 1


def test_mcp_descriptor_cache_is_per_kind_and_cleared_on_close(tmp_path: Path) -> None:
    _write_config(tmp_path)
    client = TrackingClient()
    manager = create_mcp_manager(tmp_path, transport_factory=lambda _config: client)

    manager.list_mcp_tools("demo")
    manager.list_mcp_resources("demo")
    manager.list_mcp_prompts("demo")
    manager.list_mcp_tools("demo")
    manager.list_mcp_resources("demo")
    manager.list_mcp_prompts("demo")

    assert client.list_tools_count == 1
    assert client.list_resources_count == 1
    assert client.list_prompts_count == 1

    manager.close_all_sessions()
    manager.list_mcp_tools("demo")

    assert client.list_tools_count == 2


def test_load_mcp_config_supports_legacy_and_extended_shapes(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DEMO_MCP_TOKEN", "secret-token")
    legacy = project_dir / "legacy.json"
    legacy.write_text(json.dumps({"servers": [{"name": "legacy", "command": "python", "args": ["server.py"]}]}), encoding="utf-8")
    extended = project_dir / "extended.json"
    extended.write_text(
        json.dumps(
            {
                "settings": {"tool_prefix": "adapter", "idle_timeout": 12},
                "servers": [
                    {
                        "name": "extended",
                        "url": "https://example.com/mcp",
                        "bearer_token_env": "DEMO_MCP_TOKEN",
                        "allowed_tools": ["search"],
                        "denied_tools": ["danger"],
                        "tool_approval_overrides": {"search": "always"},
                        "tool_risk_overrides": {"search": "read"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    document = load_mcp_config(project_dir, config_paths=[legacy, extended])

    assert document.settings.tool_prefix == "adapter"
    assert [item.name for item in document.servers] == ["legacy", "extended"]
    assert document.servers[0].resolved_transport() == "stdio"
    assert document.servers[1].resolved_transport() == "http"
    assert document.servers[1].resolved_headers()["Authorization"] == "Bearer secret-token"
    assert document.servers[-1].idle_timeout_seconds == 12
    assert document.servers[-1].allowed_tools == ["search"]
    assert document.servers[-1].denied_tools == ["danger"]
    assert document.servers[-1].tool_approval_overrides == {"search": "always"}
    assert document.servers[-1].tool_risk_overrides == {"search": "read"}


def test_load_mcp_server_configs_supports_mcp_servers_mapping(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "settings": {"idle_timeout": 7},
            "mcpServers": {
                "demo": {"command": "npx", "args": ["server"]},
            },
        },
    )

    servers = load_mcp_server_configs(tmp_path / ".pp-agent")

    assert [item.name for item in servers] == ["demo"]
    assert servers[0].command == "npx"
    assert servers[0].resolved_transport() == "stdio"
    assert servers[0].idle_timeout_seconds == 7


def test_load_mcp_config_preserves_intent_routing_metadata(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "mcp.json").write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "fetch",
                        "description": "Fetch web pages",
                        "intent_tags": ["web", "url", "缃戦〉"],
                        "auto_match_examples": ["鑾峰彇缃戦〉鍐呭", "summarize this webpage"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    document = load_mcp_config(project_dir)

    assert document.servers[0].intent_tags == ["web", "url", "缃戦〉"]
    assert document.servers[0].auto_match_examples == ["鑾峰彇缃戦〉鍐呭", "summarize this webpage"]
