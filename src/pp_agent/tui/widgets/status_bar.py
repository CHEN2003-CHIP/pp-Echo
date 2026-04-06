from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from pp_agent.tui.state import TuiState


class StatusBar(Static):
    def update_state(self, state: TuiState) -> None:
        text = Text()
        text.append("pp-Echo", style="bold white")
        text.append("  ")
        text.append("tui", style="dim cyan")
        text.append("\n")

        status_line = state.runtime_phase.status_line or "session=- turn=0 phase=idle queue=0 tools=0 mode=idle"
        text.append(status_line, style="dim")
        text.append("\n")

        if state.approval_state.awaiting_approval:
            text.append("approval", style="bold yellow")
            text.append("  ")
            text.append(state.approval_state.token_preview or "pending", style="yellow")
            text.append("  Ctrl+Y approve / Ctrl+N reject", style="dim")
        elif state.runtime_phase.busy:
            text.append("busy", style="bold cyan")
            text.append("  new text will enter the follow-up queue", style="dim")
        elif state.awaiting_assistant:
            text.append("waiting", style="bold bright_cyan")
            text.append("  first tokens have not arrived yet", style="dim")
        else:
            text.append("ready", style="bold green")
            text.append("  ask the next question or resume another session", style="dim")

        self.update(text)
