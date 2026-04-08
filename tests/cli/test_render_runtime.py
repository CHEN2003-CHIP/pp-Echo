from __future__ import annotations

from types import SimpleNamespace

from pp_agent.cli.render import runtime as runtime_render
from pp_agent.cli.render.runtime import ChatEventRenderer, EMPTY_TURN_FALLBACK
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime import AgentEvent


class FakeConsole:
    def __init__(self) -> None:
        self.lines: list[tuple[tuple, dict]] = []

    def print(self, *args, **kwargs) -> None:
        self.lines.append((args, kwargs))

    def rendered_text(self) -> str:
        chunks: list[str] = []
        for args, kwargs in self.lines:
            end = kwargs.get("end", "\n")
            chunks.append(" ".join(str(arg) for arg in args) + end)
        return "".join(chunks)


def _event(event_type: str, **kwargs) -> AgentEvent:
    details = kwargs.pop("details", {})
    return AgentEvent(type=event_type, details=details, **kwargs)


def _assistant_message(text: str) -> ChatMessage:
    return ChatMessage(role="assistant", content=[TextPart(text=text)], timestamp=1.0)


def test_chat_renderer_keeps_streamed_text_single(monkeypatch) -> None:
    fake_console = FakeConsole()
    monkeypatch.setattr(runtime_render, "console", fake_console)
    agent = SimpleNamespace(state=SimpleNamespace(messages=[_assistant_message("Hello")]))
    renderer = ChatEventRenderer(agent)

    renderer.render(_event("turn_start", details={"turn_id": 1}))
    renderer.render(_event("message_delta", delta="Hello"))
    renderer.render(_event("turn_end", details={"turn_id": 1}))

    assert fake_console.rendered_text() == "Hello"


def test_chat_renderer_prints_non_streamed_final_assistant_message(monkeypatch) -> None:
    fake_console = FakeConsole()
    monkeypatch.setattr(runtime_render, "console", fake_console)
    agent = SimpleNamespace(state=SimpleNamespace(messages=[]))
    renderer = ChatEventRenderer(agent)

    renderer.render(_event("turn_start", details={"turn_id": 1}))
    agent.state.messages.append(_assistant_message("Final reply"))
    renderer.render(_event("turn_end", details={"turn_id": 1}))

    assert fake_console.rendered_text() == "Final reply\n"


def test_chat_renderer_prints_fallback_for_empty_silent_turn(monkeypatch) -> None:
    fake_console = FakeConsole()
    monkeypatch.setattr(runtime_render, "console", fake_console)
    agent = SimpleNamespace(state=SimpleNamespace(messages=[]))
    renderer = ChatEventRenderer(agent)

    renderer.render(_event("turn_start", details={"turn_id": 1}))
    renderer.render(_event("turn_end", details={"turn_id": 1}))

    assert fake_console.rendered_text() == EMPTY_TURN_FALLBACK + "\n"


def test_chat_renderer_does_not_duplicate_after_tool_heavy_turn(monkeypatch) -> None:
    fake_console = FakeConsole()
    monkeypatch.setattr(runtime_render, "console", fake_console)
    agent = SimpleNamespace(state=SimpleNamespace(messages=[]))
    renderer = ChatEventRenderer(agent)

    renderer.render(_event("turn_start", details={"turn_id": 1}))
    renderer.render(_event("planner_start"))
    renderer.render(_event("tool_start", tool_name="list_files", tool_args={"path": "."}))
    renderer.render(_event("tool_end", tool_name="list_files", message="README.md", is_error=False))
    agent.state.messages.append(_assistant_message("Here are the files."))
    renderer.render(_event("turn_end", details={"turn_id": 1}))
    renderer.render(_event("turn_end", details={"turn_id": 1}))

    text = fake_console.rendered_text()
    assert text.count("Here are the files.") == 1


def test_chat_renderer_resets_between_turns(monkeypatch) -> None:
    fake_console = FakeConsole()
    monkeypatch.setattr(runtime_render, "console", fake_console)
    agent = SimpleNamespace(state=SimpleNamespace(messages=[]))
    renderer = ChatEventRenderer(agent)

    renderer.render(_event("turn_start", details={"turn_id": 1}))
    agent.state.messages.append(_assistant_message("First turn"))
    renderer.render(_event("turn_end", details={"turn_id": 1}))

    renderer.render(_event("turn_start", details={"turn_id": 2}))
    agent.state.messages.append(_assistant_message("Second turn"))
    renderer.render(_event("turn_end", details={"turn_id": 2}))

    text = fake_console.rendered_text()
    assert "First turn\n" in text
    assert "Second turn\n" in text
