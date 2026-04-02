from __future__ import annotations

import json
from pathlib import Path
import sys

from pp_agent.app.bootstrap import create_mcp_manager


class FakeMCPClient:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    def initialize(self) -> None:
        self.events.append(f"{self.name}:initialize")

    def list_tools(self) -> list[dict]:
        self.events.append(f"{self.name}:list_tools")
        return [{"name": "echo", "description": "Echo tool"}]

    def list_resources(self) -> list[dict]:
        self.events.append(f"{self.name}:list_resources")
        return [{"uri": "memo://notes", "name": "notes"}]

    def list_prompts(self) -> list[dict]:
        self.events.append(f"{self.name}:list_prompts")
        return [{"name": "summarize", "description": "Summarize prompt"}]

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.events.append(f"{self.name}:call_tool:{name}")
        return {"content": "ok", "payload": {"arguments": arguments}}

    def read_resource(self, uri: str) -> dict:
        self.events.append(f"{self.name}:read_resource:{uri}")
        return {"content": "resource"}

    def get_prompt(self, name: str, arguments: dict | None = None) -> dict:
        self.events.append(f"{self.name}:get_prompt:{name}")
        return {"content": "prompt"}

    def close(self) -> None:
        self.events.append(f"{self.name}:close")


def _write_config(tmp_path: Path, idle_timeout_seconds: int = 300) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "mcp.json").write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "demo",
                        "transport": "memory",
                        "is_remote": False,
                        "requires_auth": False,
                        "idle_timeout_seconds": idle_timeout_seconds,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_mcp_manager_startup_does_not_connect_servers(tmp_path: Path) -> None:
    events: list[str] = []
    _write_config(tmp_path)

    manager = create_mcp_manager(tmp_path, transport_factory=lambda config: FakeMCPClient(config.name, events))

    assert manager.server_names() == ["demo"]
    assert manager.active_session_names() == []
    assert events == []


def test_mcp_discovery_connects_on_first_access_and_reuses_session(tmp_path: Path) -> None:
    events: list[str] = []
    _write_config(tmp_path)
    manager = create_mcp_manager(tmp_path, transport_factory=lambda config: FakeMCPClient(config.name, events))

    manager.list_mcp_tools("demo")
    manager.list_mcp_resources("demo")

    assert events == [
        "demo:initialize",
        "demo:list_tools",
        "demo:list_resources",
    ]
    assert manager.active_session_names() == ["demo"]


def test_mcp_close_idle_sessions_reclaims_cached_session(tmp_path: Path) -> None:
    events: list[str] = []
    current_time = 100.0

    def time_fn() -> float:
        return current_time

    _write_config(tmp_path, idle_timeout_seconds=5)
    manager = create_mcp_manager(
        tmp_path,
        transport_factory=lambda config: FakeMCPClient(config.name, events),
        time_fn=time_fn,
    )

    manager.list_mcp_tools("demo")
    current_time = 106.0

    assert manager.close_idle_sessions() == ["demo"]
    assert events[-1] == "demo:close"
    assert manager.active_session_names() == []


def test_default_stdio_transport_can_talk_to_demo_server(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    server_script = tmp_path / "demo_server.py"
    server_script.write_text(
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    params = request.get("params", {})
    result = {}
    if method == "initialize":
        result = {"ok": True}
    elif method == "list_tools":
        result = {"tools": [{"name": "echo", "description": "Echo tool", "input_schema": {"type": "object", "properties": {"message": {"type": "string"}}}}]}
    elif method == "list_resources":
        result = {"resources": []}
    elif method == "list_prompts":
        result = {"prompts": []}
    elif method == "call_tool":
        result = {"content": params.get("arguments", {}).get("message", ""), "payload": {}, "is_error": False}
    elif method == "close":
        result = {"closed": True}
    else:
        print(json.dumps({"id": request.get("id"), "error": f"unknown method: {method}"}), flush=True)
        continue
    print(json.dumps({"id": request.get("id"), "result": result}), flush=True)
    if method == "close":
        break
""".strip(),
        encoding="utf-8",
    )
    (project_dir / "mcp.json").write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "demo",
                        "description": "Echo back user text",
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": [str(server_script)],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    manager = create_mcp_manager(tmp_path)

    tools = manager.list_mcp_tools("demo")
    result = manager.call_mcp_tool("demo", "echo", {"message": "hello"})

    assert tools[0].name == "echo"
    assert result.content == "hello"
