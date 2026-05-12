from __future__ import annotations

from pathlib import Path
from typing import Optional

from pp_agent.api import sdk
from pp_agent.api.json_mode import emit_json_error, emit_json_event, emit_json_result
from pp_agent.api.rpc_mode import run_stdio_rpc
from pp_agent.cli.render.runtime import console, render_event


def build_agent(workspace: Path, session_id: Optional[str] = None):
    return sdk.create_runtime(workspace, session_id=session_id)


_DEFAULT_BUILD_AGENT = build_agent


def run_main(
    prompt: Optional[str],
    workspace: Path,
    session_id: Optional[str] = None,
    json_mode: bool = False,
    mode: str = "default",
) -> dict:
    if mode == "rpc":
        run_stdio_rpc(workspace)
        return {"mode": "rpc"}
    if prompt is None:
        raise ValueError("Prompt is required unless --mode rpc is used.")

    if build_agent is not _DEFAULT_BUILD_AGENT:
        agent = build_agent(workspace, session_id=session_id)
        events = agent.prompt(prompt)
        payload = {
            "session_id": agent.session_id,
            "assistant": "",
            "pending_plan_token": agent.state.pending_plan_token,
            "event_count": len(events),
        }
        stats = {
            "pending_tool_call_count": len(agent.state.pending_tool_calls),
            "queued_message_count": len(agent.state.queued_messages),
        }
        if any(value for value in stats.values()):
            payload["stats"] = stats
        if json_mode:
            console.print(emit_json_result(payload))
        else:
            console.print()
        return payload

    if json_mode:
        def emit(event) -> None:
            console.print(emit_json_event(event))

        try:
            payload = sdk.run(prompt, workspace, session_id=session_id, subscriber=emit)
        except Exception as exc:  # noqa: BLE001
            console.print(emit_json_error("run_failed", str(exc)))
            return {"error": str(exc)}
        console.print(emit_json_result(payload))
        return payload

    payload = sdk.run(prompt, workspace, session_id=session_id, subscriber=render_event)
    console.print()
    return payload


__all__ = ["run_main"]
