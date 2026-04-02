from __future__ import annotations

import json
from pathlib import Path

from pp_agent.app.bootstrap import create_mcp_manager


class ExecutingClient:
    def initialize(self) -> None:
        return None

    def list_tools(self) -> list[dict]:
        return [{"name": "echo", "description": "Echo tool"}]

    def list_resources(self) -> list[dict]:
        return [{"uri": "memo://notes", "name": "Notes"}]

    def list_prompts(self) -> list[dict]:
        return [{"name": "summarize", "description": "Summarize"}]

    def call_tool(self, name: str, arguments: dict) -> dict:
        return {"content": f"tool:{name}", "payload": {"arguments": arguments}}

    def read_resource(self, uri: str) -> dict:
        return {"content": f"resource:{uri}", "payload": {"uri": uri}}

    def get_prompt(self, name: str, arguments: dict | None = None) -> dict:
        return {"content": f"prompt:{name}", "payload": {"arguments": arguments or {}}}

    def close(self) -> None:
        return None


def _write_config(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "mcp.json").write_text(json.dumps({"servers": [{"name": "demo"}]}), encoding="utf-8")


def test_call_mcp_tool_returns_result_model(tmp_path: Path) -> None:
    _write_config(tmp_path)
    manager = create_mcp_manager(tmp_path, transport_factory=lambda _config: ExecutingClient())

    result = manager.call_mcp_tool("demo", "echo", {"message": "hi"})

    assert result.kind == "mcp_tool"
    assert result.server_name == "demo"
    assert result.name_or_uri == "echo"
    assert result.content == "tool:echo"
    assert result.payload["arguments"] == {"message": "hi"}


def test_read_mcp_resource_returns_result_model(tmp_path: Path) -> None:
    _write_config(tmp_path)
    manager = create_mcp_manager(tmp_path, transport_factory=lambda _config: ExecutingClient())

    result = manager.read_mcp_resource("demo", "memo://notes")

    assert result.kind == "mcp_resource"
    assert result.server_name == "demo"
    assert result.name_or_uri == "memo://notes"
    assert result.content == "resource:memo://notes"


def test_get_mcp_prompt_returns_result_model(tmp_path: Path) -> None:
    _write_config(tmp_path)
    manager = create_mcp_manager(tmp_path, transport_factory=lambda _config: ExecutingClient())

    result = manager.get_mcp_prompt("demo", "summarize", {"topic": "notes"})

    assert result.kind == "mcp_prompt"
    assert result.server_name == "demo"
    assert result.name_or_uri == "summarize"
    assert result.content == "prompt:summarize"
    assert result.payload["arguments"] == {"topic": "notes"}
