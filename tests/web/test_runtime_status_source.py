from __future__ import annotations

from pathlib import Path


def test_web_runtime_status_uses_snapshot_and_terminal_events() -> None:
    source = Path("web/src/App.tsx").read_text(encoding="utf-8")

    assert "export function runtimeIsBusy" in source
    assert "if (snapshot) return Boolean(snapshot.busy);" in source
    assert "function hasErrorSinceLatestStart" in source
    assert 'event.type === "agent_end"' in source
    assert 'currentStatus === "tool_start" ? "Idle"' in source
    assert 'snapshot?.cancel_requested' in source
    assert 'api.cancel(activeSessionId)' in source
    assert 'event.type.includes("subagent")' in source
    assert 'result.resumed !== true' in source
    assert 'result.success !== false' in source
