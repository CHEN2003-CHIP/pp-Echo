from __future__ import annotations

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from pp_agent.tui.state import TuiMessage, TuiState


class TranscriptView(VerticalScroll):
    def compose(self):
        yield Static(id="transcript_body")

    def update_state(self, state: TuiState) -> None:
        follow_tail = self.scroll_y >= max(0, self.max_scroll_y - 3)
        renderable = Text()
        previous: TuiMessage | None = None

        for message in state.messages:
            if renderable.plain:
                renderable.append(_separator(previous, message))
            renderable.append_text(_render_message(message))
            previous = message

        if state.awaiting_assistant and not state.active_assistant_message.text:
            if renderable.plain:
                renderable.append(_trailing_spacing(previous))
            renderable.append_text(_render_waiting_message())
        elif state.active_assistant_message.text:
            if renderable.plain:
                renderable.append(_trailing_spacing(previous))
            renderable.append_text(
                _render_streaming_message(
                    state.active_assistant_message.text,
                    state.active_assistant_message.streaming,
                )
            )

        if not renderable.plain:
            renderable.append("Conversation will appear here.", style="dim")

        self.query_one("#transcript_body", Static).update(renderable)
        if follow_tail:
            self.scroll_end(animate=False)


def _render_message(message: TuiMessage) -> Text:
    if message.kind == "status":
        return _render_status_line(message.text.strip() or "status update")

    title_style = {
        "assistant": "bold cyan",
        "user": "bold green",
        "system": "bold yellow",
    }.get(message.role, "bold white")
    body_style = {
        "assistant": "white",
        "user": "bright_white",
        "system": "bright_white",
    }.get(message.role, "white")

    text = Text()
    text.append(_message_title(message), style=title_style)
    text.append("\n")
    _append_indented_lines(text, message.text.strip() or "(empty)", body_style)
    return text


def _render_streaming_message(text_value: str, streaming: bool) -> Text:
    text = Text()
    text.append("assistant", style="bold cyan")
    text.append("\n")
    _append_indented_lines(text, text_value.strip() or "...", "white")
    if streaming:
        text.append("\n")
        text.append("  ...", style="dim bright_cyan")
    return text


def _render_waiting_message() -> Text:
    return _render_status_line("assistant is thinking ...")


def _render_status_line(body: str) -> Text:
    text = Text()
    text.append(". ", style="dim bright_black")
    text.append(body, style="italic dim cyan")
    return text


def _append_indented_lines(text: Text, body: str, style: str) -> None:
    lines = body.splitlines() or [body]
    for index, line in enumerate(lines):
        if index:
            text.append("\n")
        text.append(f"  {line}", style=style)


def _separator(previous: TuiMessage | None, current: TuiMessage) -> str:
    if previous is None:
        return ""
    if previous.kind == "status" and current.kind == "status":
        return "\n"
    if previous.kind == "status" or current.kind == "status":
        return "\n"
    if previous.role == current.role:
        return "\n"
    return "\n\n"


def _trailing_spacing(previous: TuiMessage | None) -> str:
    if previous is None:
        return ""
    if previous.kind == "status":
        return "\n"
    return "\n\n"


def _message_title(message: TuiMessage) -> str:
    if message.role == "user":
        return "you"
    if message.role == "assistant":
        return "assistant"
    return message.role
