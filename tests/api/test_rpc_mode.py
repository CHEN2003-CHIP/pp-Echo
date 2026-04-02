from __future__ import annotations

import io
import json

from pp_agent.api import rpc_mode


def test_rpc_mode_emits_events_and_result(monkeypatch, tmp_path) -> None:
    def fake_run(prompt, workspace, **kwargs):
        kwargs["subscriber"](type("Event", (), {"model_dump": lambda self, mode="json": {"type": "agent_start"}})())
        return {"session_id": "session-1", "event_count": 1, "assistant": "ok", "pending_plan_token": None}

    monkeypatch.setattr(rpc_mode.sdk, "run", fake_run)
    stdin = io.StringIO('{"protocol_version":"1","id":"1","method":"run","params":{"prompt":"hello"}}\n')
    stdout = io.StringIO()

    rpc_mode.run_stdio_rpc(tmp_path, stdin=stdin, stdout=stdout)

    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert lines[0]["protocol_version"] == "1"
    assert "event" in lines[0]
    assert lines[1]["protocol_version"] == "1"
    assert lines[1]["ok"] is True


def test_rpc_mode_returns_structured_error_for_unknown_method(tmp_path) -> None:
    stdin = io.StringIO('{"protocol_version":"1","id":"1","method":"nope","params":{}}\n')
    stdout = io.StringIO()

    rpc_mode.run_stdio_rpc(tmp_path, stdin=stdin, stdout=stdout)

    line = json.loads(stdout.getvalue().strip())
    assert line["protocol_version"] == "1"
    assert line["ok"] is False
