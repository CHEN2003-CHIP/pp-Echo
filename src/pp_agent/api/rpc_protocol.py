from __future__ import annotations

import json

PROTOCOL_VERSION = "1"


def parse_request(line):
    payload = json.loads(line)
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("Unsupported protocol_version")
    if "id" not in payload or "method" not in payload:
        raise ValueError("Invalid rpc request")
    return payload


def serialize_event(event, request_id):
    payload = event.model_dump(mode="json") if hasattr(event, "model_dump") else event
    return json.dumps({"protocol_version": PROTOCOL_VERSION, "id": request_id, "event": payload}, ensure_ascii=False)


def serialize_result(request_id, result):
    return json.dumps({"protocol_version": PROTOCOL_VERSION, "id": request_id, "ok": True, "result": result}, ensure_ascii=False)


def serialize_error(request_id, code, message):
    return json.dumps(
        {"protocol_version": PROTOCOL_VERSION, "id": request_id, "ok": False, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )
