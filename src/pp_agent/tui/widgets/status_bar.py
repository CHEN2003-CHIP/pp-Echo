from __future__ import annotations

from textual.widgets import Static

from pp_agent.tui.state import TuiState


class StatusBar(Static):
    def update_state(self, state: TuiState) -> None:
        phase = state.runtime_phase
        approval = " pending-approval" if state.approval_state.awaiting_approval else ""
        busy = "busy" if phase.busy else "idle"
        text = (
            f"session={phase.session_id or '-'} "
            f"turn={phase.turn_id} phase={phase.phase} "
            f"queue={phase.queue_count} tools={phase.pending_tool_count} "
            f"mode={busy}{approval}"
        )
        if phase.reason:
            text += f" reason={phase.reason}"
        self.update(text)
