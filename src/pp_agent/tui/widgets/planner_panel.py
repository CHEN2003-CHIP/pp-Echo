from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from pp_agent.tui.state import TuiState


class PlannerPanel(Static):
    def update_state(self, state: TuiState) -> None:
        text = Text()
        text.append("Plan\n", style="bold")
        if state.plan_steps:
            for step in state.plan_steps:
                status_style = {
                    "done": "green",
                    "completed": "green",
                    "in_progress": "cyan",
                    "running": "cyan",
                    "failed": "red",
                    "error": "red",
                }.get(step.status, "yellow")
                text.append("  ")
                text.append(step.status.upper(), style=status_style)
                text.append("  ", style="dim")
                text.append(step.title, style="white")
                if step.tool_name:
                    text.append(f"  [{step.tool_name}]", style="dim")
                text.append("\n")
        else:
            text.append("  idle\n", style="dim")

        text.append("\nQueue\n", style="bold")
        text.append(f"  total     {state.queue_summary.queue_count}\n", style="white")
        text.append(f"  steering  {state.queue_summary.steering_count}\n", style="white")
        text.append(f"  follow-up {state.queue_summary.follow_up_count}", style="white")
        if state.queue_summary.latest_action:
            text.append("\n\n")
            text.append("  last ", style="dim")
            text.append(state.queue_summary.latest_action, style="dim cyan")

        self.update(text)
