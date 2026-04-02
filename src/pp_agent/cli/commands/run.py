from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pp_agent.app.bootstrap import build_agent
from pp_agent.cli.render.runtime import compact_text, console, render_event


def _assistant_preview(agent, limit: int = 400) -> str:
    for message in reversed(agent.state.messages):
        if message.role != "assistant":
            continue
        parts = [part.text.strip() for part in message.content if getattr(part, "text", "").strip()]
        text = " ".join(parts)
        return compact_text(text, limit=limit) if text else ""
    return ""


def run_main(
    prompt: str,
    workspace: Path,
    session_id: Optional[str] = None,
    json_mode: bool = False,
    mode: str = "default",
) -> dict:
    agent = build_agent(workspace, session_id=session_id)
    if not json_mode and mode != "rpc":
        agent.subscribe(render_event)
    events = agent.prompt(prompt)
    payload = {
        "mode": mode,
        "session_id": agent.session_id,
        "pending_plan_token": agent.state.pending_plan_token,
        "pending_tool_call_count": len(agent.state.pending_tool_calls),
        "queued_message_count": len(agent.state.queued_messages),
        "event_count": len(events),
        "assistant": _assistant_preview(agent, limit=400),
        "events": [event.model_dump(mode="json") for event in events] if mode == "rpc" else None,
    }
    if json_mode or mode == "rpc":
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        console.print()
    return payload


__all__ = ["run_main"]
