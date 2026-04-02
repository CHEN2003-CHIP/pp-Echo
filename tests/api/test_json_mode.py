from __future__ import annotations

import json

from pp_agent.cli.commands import run as run_command


def test_run_json_outputs_protocol_versioned_json_lines(monkeypatch, tmp_path) -> None:
    emitted: list[str] = []

    def fake_run(prompt, workspace, **kwargs):
        for event_type in [
            "agent_start",
            "turn_start",
            "context_built",
            "before_provider_request",
            "provider_response",
            "turn_end",
            "agent_end",
        ]:
            kwargs["subscriber"](type("Event", (), {"model_dump": lambda self, mode="json", event_type=event_type: {"type": event_type}})())
        return {"session_id": "session-1", "assistant": "ok", "pending_plan_token": None, "event_count": 7}

    monkeypatch.setattr(run_command.sdk, "run", fake_run)
    monkeypatch.setattr(run_command.console, "print", lambda line="", **kwargs: emitted.append(line))

    run_command.run_main("hello", tmp_path, json_mode=True)

    parsed = [json.loads(line) for line in emitted if line]
    assert all(item["protocol_version"] == "1" for item in parsed)
    assert [item["kind"] for item in parsed[:-1]] == ["event"] * 7
    assert parsed[-1]["kind"] == "result"
    assert all("Planner" not in line for line in emitted)
