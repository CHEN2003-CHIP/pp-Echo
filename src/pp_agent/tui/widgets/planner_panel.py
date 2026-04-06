from __future__ import annotations

from textual.widgets import Static

from pp_agent.tui.state import TuiState


class PlannerPanel(Static):
    def update_state(self, state: TuiState) -> None:
        lines = [
            "Planner",
            f"Queue: {state.queue_summary.queue_count} "
            f"(steering={state.queue_summary.steering_count}, follow_up={state.queue_summary.follow_up_count})",
        ]
        if state.approval_state.prompt:
            lines.append(state.approval_state.prompt)
        if state.queue_summary.latest_action:
            lines.append(state.queue_summary.latest_action)
        if state.plan_steps:
            lines.append("")
            lines.extend(
                f"[{step.status}] {step.title}" + (f" [{step.tool_name}]" if step.tool_name else "")
                for step in state.plan_steps
            )
        else:
            lines.append("")
            lines.append("No active plan.")
        self.update("\n".join(lines))
