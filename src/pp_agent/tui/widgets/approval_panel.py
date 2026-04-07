from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from pp_agent.tui.state import TuiState


class ApprovalPanel(Vertical):
    def compose(self) -> ComposeResult:
        yield Static(id="approval_title")
        yield Static(id="approval_status")
        yield Static(id="approval_prompt")
        with Horizontal(id="approval_actions"):
            yield Button("Approve", id="approve_button")
            yield Button("Reject", id="reject_button")

    def update_state(self, state: TuiState) -> None:
        title = self.query_one("#approval_title", Static)
        status = self.query_one("#approval_status", Static)
        prompt = self.query_one("#approval_prompt", Static)
        approve = self.query_one("#approve_button", Button)
        reject = self.query_one("#reject_button", Button)

        if state.approval_state.awaiting_approval:
            title.update("Approval required")
            status.update(
                f"status={state.approval_state.status_label} token={state.approval_state.token_preview or 'pending'}"
            )
            prompt.update("Approve or reject to unblock execution. Ctrl+Y approves, Ctrl+N rejects.")
            approve.disabled = False
            reject.disabled = False
            self.set_class(True, "pending")
            self.set_class(False, "idle")
        else:
            title.update("Approval")
            status.update(f"status={state.approval_state.status_label}")
            prompt.update("No planner gate is waiting for action.")
            approve.disabled = True
            reject.disabled = True
            self.set_class(False, "pending")
            self.set_class(True, "idle")
