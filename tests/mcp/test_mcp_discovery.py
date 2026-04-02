from __future__ import annotations

import json
from pathlib import Path

from pp_agent.app.bootstrap import create_mcp_manager


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


def _write_config(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "mcp.json").write_text(json.dumps({"servers": [{"name": "demo"}]}), encoding="utf-8")


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
    manager = create_mcp_manager(tmp_path, transport_factory=lambda _config: TrackingClient())

    first = [item.name for item in manager.list_mcp_tools("demo")]
    second = [item.name for item in manager.list_mcp_tools("demo")]

    assert first == ["alpha", "beta"]
    assert second == ["alpha", "beta"]
