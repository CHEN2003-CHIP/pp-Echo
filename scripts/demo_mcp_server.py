from __future__ import annotations

import json
import sys


def _reply(request_id: object, *, result: dict | None = None, error: str | None = None) -> None:
    payload: dict[str, object] = {"id": request_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result or {}
    print(json.dumps(payload, ensure_ascii=False), flush=True)


for line in sys.stdin:
    raw = line.strip()
    if not raw:
        continue
    request = json.loads(raw)
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})
    if method == "initialize":
        _reply(request_id, result={"ok": True, "server": "demo"})
        continue
    if method == "list_tools":
        _reply(
            request_id,
            result={
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo back a short message or text fragment.",
                        "input_schema": {
                            "type": "object",
                            "properties": {"message": {"type": "string"}},
                            "required": ["message"],
                        },
                    },
                    {
                        "name": "summarize",
                        "description": "Return a short uppercase summary of the provided text.",
                        "input_schema": {
                            "type": "object",
                            "properties": {"message": {"type": "string"}},
                            "required": ["message"],
                        },
                    },
                ]
            },
        )
        continue
    if method == "list_resources":
        _reply(
            request_id,
            result={
                "resources": [
                    {
                        "uri": "demo://readme",
                        "name": "readme",
                        "description": "Demo MCP resource information.",
                        "mime_type": "text/plain",
                    }
                ]
            },
        )
        continue
    if method == "list_prompts":
        _reply(
            request_id,
            result={
                "prompts": [
                    {
                        "name": "summarize_prompt",
                        "description": "Summarize text through the demo server.",
                        "arguments_schema": {
                            "type": "object",
                            "properties": {"message": {"type": "string"}},
                        },
                    }
                ]
            },
        )
        continue
    if method == "call_tool":
        name = params.get("name")
        arguments = params.get("arguments", {})
        message = str(arguments.get("message", ""))
        if name == "echo":
            _reply(request_id, result={"content": message, "payload": {"echoed": message}, "is_error": False})
            continue
        if name == "summarize":
            summary = " ".join(message.split())[:80].upper()
            _reply(request_id, result={"content": summary, "payload": {"summary": summary}, "is_error": False})
            continue
        _reply(request_id, error=f"unknown tool: {name}")
        continue
    if method == "read_resource":
        _reply(request_id, result={"content": "Demo MCP resource", "payload": {}, "is_error": False})
        continue
    if method == "get_prompt":
        message = str(params.get("arguments", {}).get("message", ""))
        _reply(request_id, result={"content": f"Summarize this: {message}", "payload": {}, "is_error": False})
        continue
    if method == "close":
        _reply(request_id, result={"closed": True})
        break
    _reply(request_id, error=f"unknown method: {method}")
