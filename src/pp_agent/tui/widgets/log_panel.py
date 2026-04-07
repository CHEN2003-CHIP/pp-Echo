from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from pp_agent.tui.state import TuiState


class LogPanel(Static):
    def update_state(self, state: TuiState) -> None:
        text = Text()
        text.append("Activity\n", style="bold")
        entries = state.ephemeral_logs[-8:]
        if not entries:
            text.append("  no recent activity", style="dim")
            self.update(text)
            return

        for entry in entries:
            prefix_style = {
                "info": "dim cyan",
                "warning": "yellow",
                "error": "red",
                "success": "green",
            }.get(entry.level, "white")
            prefix = entry.level.upper()
            if entry.important:
                prefix += " *"
            text.append("  ")
            text.append(prefix, style=prefix_style)
            text.append("  ", style="dim")
            text.append(entry.message, style="white" if entry.important else "dim")
            text.append("\n")
        self.update(text)
