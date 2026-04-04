from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading

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


def test_default_http_transport_can_talk_to_demo_server(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    requests_seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
            request = json.loads(body)
            requests_seen.append(request)
            method = request.get("method")
            params = request.get("params", {})
            result: dict[str, object]
            if method == "initialize":
                result = {"ok": True}
            elif method == "list_tools":
                result = {"tools": [{"name": "echo", "description": "Echo tool"}]}
            elif method == "list_resources":
                result = {"resources": []}
            elif method == "list_prompts":
                result = {"prompts": []}
            elif method == "call_tool":
                result = {"content": params.get("arguments", {}).get("message", ""), "payload": {}, "is_error": False}
            else:
                result = {"ok": True}
            payload = json.dumps({"id": request.get("id"), "result": result}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (project_dir / "mcp.json").write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": "demo-http",
                            "url": f"http://127.0.0.1:{server.server_port}/mcp",
                            "bearer_token": "token-123",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        manager = create_mcp_manager(tmp_path)

        tools = manager.list_mcp_tools("demo-http")
        result = manager.call_mcp_tool("demo-http", "echo", {"message": "hello"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert tools[0].name == "echo"
    assert result.content == "hello"
    assert requests_seen[0]["method"] == "initialize"
    assert requests_seen[-1]["method"] == "call_tool"



def test_standard_stdio_transport_can_talk_to_mcp_framed_server(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    server_script = tmp_path / "standard_server.py"
    server_script.write_text(
        r"""
import json
import sys


def read_message() -> dict:
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            raise SystemExit(0)
        if line in (b"\r\n", b"\n"):
            break
        key, _, value = line.decode("utf-8").partition(":")
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def write_message(payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


while True:
    request = read_message()
    method = request.get("method")
    if method == "initialize":
        write_message({"jsonrpc": "2.0", "id": request.get("id"), "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "demo", "version": "1.0"}}})
    elif method == "tools/list":
        write_message({"jsonrpc": "2.0", "id": request.get("id"), "result": {"tools": [{"name": "echo", "description": "Echo tool", "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}}]}})
    elif method == "resources/list":
        write_message({"jsonrpc": "2.0", "id": request.get("id"), "result": {"resources": []}})
    elif method == "prompts/list":
        write_message({"jsonrpc": "2.0", "id": request.get("id"), "result": {"prompts": []}})
    elif method == "tools/call":
        message = request.get("params", {}).get("arguments", {}).get("message", "")
        write_message({"jsonrpc": "2.0", "id": request.get("id"), "result": {"content": [{"type": "text", "text": message}], "isError": False}})
    elif method == "notifications/initialized":
        continue
    else:
        write_message({"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32601, "message": f"unknown method: {method}"}})
""".strip(),
        encoding="utf-8",
    )
    (project_dir / "mcp.json").write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "demo-standard",
                        "command": sys.executable,
                        "args": [str(server_script)],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    manager = create_mcp_manager(tmp_path)

    tools = manager.list_mcp_tools("demo-standard")
    result = manager.call_mcp_tool("demo-standard", "echo", {"message": "hello"})

    assert tools[0].name == "echo"
    assert tools[0].input_schema["required"] == ["message"]
    assert result.content == "hello"


def test_standard_stdio_tool_only_server_tolerates_missing_resource_and_prompt_handlers(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    server_script = tmp_path / "tool_only_server.py"
    server_script.write_text(
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "tool-only", "version": "1.0"}}
        print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}), flush=True)
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "description": "Echo tool", "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}}}]}
        print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}), flush=True)
    elif method == "tools/call":
        message = request.get("params", {}).get("arguments", {}).get("message", "")
        print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": {"content": [{"type": "text", "text": message}], "isError": False}}), flush=True)
    elif method in {"resources/list", "prompts/list"}:
        print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32601, "message": "Method not found"}}), flush=True)
    elif method == "notifications/initialized":
        continue
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32601, "message": f"unknown method: {method}"}}), flush=True)
""".strip(),
        encoding="utf-8",
    )
    (project_dir / "mcp.json").write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "tool-only",
                        "command": sys.executable,
                        "args": [str(server_script)],
                        "protocol": "standard",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    manager = create_mcp_manager(tmp_path)

    tools = manager.list_mcp_tools("tool-only")
    resources = manager.list_mcp_resources("tool-only")
    prompts = manager.list_mcp_prompts("tool-only")
    result = manager.call_mcp_tool("tool-only", "echo", {"message": "hello"})

    assert tools[0].name == "echo"
    assert resources == []
    assert prompts == []
    assert result.content == "hello"


def test_standard_stdio_transport_can_talk_to_line_delimited_mcp_server(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    server_script = tmp_path / "standard_line_server.py"
    server_script.write_text(
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "demo-line", "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "description": "Echo tool", "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}}]}
    elif method == "resources/list":
        result = {"resources": []}
    elif method == "prompts/list":
        result = {"prompts": []}
    elif method == "tools/call":
        message = request.get("params", {}).get("arguments", {}).get("message", "")
        result = {"content": [{"type": "text", "text": message}], "isError": False}
    elif method == "notifications/initialized":
        continue
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32601, "message": f"unknown method: {method}"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}), flush=True)
""".strip(),
        encoding="utf-8",
    )
    (project_dir / "mcp.json").write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "demo-standard-line",
                        "command": sys.executable,
                        "args": [str(server_script)],
                        "protocol": "standard",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    manager = create_mcp_manager(tmp_path)

    tools = manager.list_mcp_tools("demo-standard-line")
    result = manager.call_mcp_tool("demo-standard-line", "echo", {"message": "hello"})

    assert tools[0].name == "echo"
    assert tools[0].input_schema["required"] == ["message"]
    assert result.content == "hello"


def test_standard_http_transport_can_talk_to_jsonrpc_server(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    requests_seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
            request = json.loads(body)
            requests_seen.append(request)
            method = request.get("method")
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "demo-http", "version": "1.0"}}
            elif method == "tools/list":
                result = {"tools": [{"name": "echo", "description": "Echo tool", "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}}}]}
            elif method == "resources/list":
                result = {"resources": []}
            elif method == "prompts/list":
                result = {"prompts": []}
            elif method == "tools/call":
                result = {"content": [{"type": "text", "text": request.get("params", {}).get("arguments", {}).get("message", "")}], "isError": False}
            else:
                result = {}
            payload = json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (project_dir / "mcp.json").write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": "demo-http-standard",
                            "url": f"http://127.0.0.1:{server.server_port}/mcp",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        manager = create_mcp_manager(tmp_path)

        tools = manager.list_mcp_tools("demo-http-standard")
        result = manager.call_mcp_tool("demo-http-standard", "echo", {"message": "hello"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert tools[0].name == "echo"
    assert result.content == "hello"
    assert requests_seen[0]["method"] == "initialize"
    assert requests_seen[-1]["method"] == "tools/call"
