from __future__ import annotations

from textual.widgets import Static

from pp_agent.tui.state import TuiState


class LogPanel(Static):
    def update_state(self, state: TuiState) -> None:
        lines = state.ephemeral_logs[-12:]
        self.update("\n".join(lines) if lines else "No logs yet.")
