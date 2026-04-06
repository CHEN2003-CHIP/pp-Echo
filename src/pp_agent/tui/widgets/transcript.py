from __future__ import annotations

from textual.widgets import Static

from pp_agent.tui.state import TuiState


class TranscriptView(Static):
    def update_state(self, state: TuiState) -> None:
        lines: list[str] = []
        for message in state.messages[-40:]:
            lines.append(f"{message.role}> {message.text}")
        if state.active_assistant_message.text:
            lines.append(f"assistant> {state.active_assistant_message.text}")
        self.update("\n\n".join(lines) if lines else "No messages yet.")
