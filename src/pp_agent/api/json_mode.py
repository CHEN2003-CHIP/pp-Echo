from __future__ import annotations

import json

PROTOCOL_VERSION = "1"


def emit_json_event(event) -> str:
    payload = event.model_dump(mode="json") if hasattr(event, "model_dump") else event
    return json.dumps({"protocol_version": PROTOCOL_VERSION, "kind": "event", "event": payload}, ensure_ascii=False)


def emit_json_result(result) -> str:
    return json.dumps({"protocol_version": PROTOCOL_VERSION, "kind": "result", "result": result}, ensure_ascii=False)


def emit_json_error(code, message) -> str:
    return json.dumps({"protocol_version": PROTOCOL_VERSION, "kind": "error", "error": {"code": code, "message": message}}, ensure_ascii=False)


def events_to_json_lines(events, *, result=None) -> list[str]:
    lines = [emit_json_event(event) for event in events]
    if result is not None:
        lines.append(emit_json_result(result))
    return lines
