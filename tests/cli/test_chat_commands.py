from __future__ import annotations

from types import SimpleNamespace

from pp_agent.cli import dispatcher


class FakeConsole:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *args, **kwargs) -> None:
        text = " ".join(str(arg) for arg in args)
        self.lines.append(text)

    def rendered_text(self) -> str:
        return "\n".join(self.lines)


def _agent() -> SimpleNamespace:
    return SimpleNamespace(
        session_id="session-1",
        llm_client=SimpleNamespace(model=SimpleNamespace(model="demo-model")),
        state=SimpleNamespace(
            model=SimpleNamespace(model="demo-model"),
            pending_plan_token=None,
            pending_tool_calls=[],
            queued_messages=[],
            compaction=SimpleNamespace(summary="", summarized_message_count=0),
        ),
    )


def test_handle_command_shows_hint_for_approve_list(monkeypatch, tmp_path) -> None:
    fake_console = FakeConsole()
    monkeypatch.setattr(dispatcher, "console", fake_console)

    result = dispatcher.handle_command(_agent(), "/approve list", tmp_path)

    assert result == "handled"
    assert "Use /approvals in chat mode" in fake_console.rendered_text()
    assert "pp-agent approvals list" in fake_console.rendered_text()
