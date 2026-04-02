from __future__ import annotations

import sys
from pathlib import Path

from pp_agent.api import sdk
from pp_agent.api.rpc_protocol import parse_request, serialize_error, serialize_event, serialize_result


def run_stdio_rpc(workspace: Path, stdin=None, stdout=None) -> None:
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    for raw_line in input_stream:
        line = raw_line.strip()
        if not line:
            continue
        request_id = ""
        try:
            request = parse_request(line)
            request_id = str(request["id"])
            result = _dispatch_request(workspace, request, output_stream)
            output_stream.write(serialize_result(request_id, result) + "\n")
            output_stream.flush()
        except Exception as exc:  # noqa: BLE001
            output_stream.write(serialize_error(request_id or "unknown", "rpc_error", str(exc)) + "\n")
            output_stream.flush()


def _dispatch_request(workspace: Path, request: dict, output_stream) -> dict:
    method = request["method"]
    params = dict(request.get("params") or {})
    request_id = str(request["id"])

    def emit(event) -> None:
        output_stream.write(serialize_event(event, request_id) + "\n")
        output_stream.flush()

    if method == "run":
        return sdk.run(params.get("prompt", ""), workspace, session_id=params.get("session_id"), subscriber=emit)
    if method == "continue_session":
        return sdk.continue_session(workspace, params["session_id"], subscriber=emit)
    if method == "create_session":
        runtime = sdk.create_session(workspace, lifecycle_subscribers=[emit])
        return {"session_id": runtime.session_id}
    if method == "restore_session":
        runtime = sdk.restore_session(workspace, params["session_id"], lifecycle_subscribers=[emit])
        return {"session_id": runtime.session_id}
    if method == "list_sessions":
        return {"sessions": sdk.list_sessions(workspace)}
    if method == "get_session_tree":
        return sdk.get_session_tree(workspace, session_id=params.get("session_id"), sort_mode=params.get("sort_mode", "branch"), lifecycle_subscribers=[emit])
    if method == "fork_session":
        return sdk.fork_session(workspace, params["session_id"], head_id=params.get("head_id"), lifecycle_subscribers=[emit])
    if method == "rewind_session":
        return sdk.rewind_session(
            workspace,
            params["session_id"],
            turn_count=params.get("turn_count"),
            message_count=params.get("message_count"),
            lifecycle_subscribers=[emit],
        )
    if method == "approvals_summary":
        return sdk.approvals_summary(workspace)
    raise ValueError(f"Unsupported rpc method: {method}")
