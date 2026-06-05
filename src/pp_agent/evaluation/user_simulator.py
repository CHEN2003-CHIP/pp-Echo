from __future__ import annotations

from pathlib import Path

from pp_agent.evaluation.adapter import AgentAdapter
from pp_agent.evaluation.models import AgentTrace, EvalTask


class ScriptedUserSimulator:
    def run(self, task: EvalTask, workspace: Path, adapter: AgentAdapter) -> AgentTrace:
        trace = adapter.start(task, workspace)
        for step in task.user_agenda[: task.max_turns]:
            if step.kind == "message":
                trace = adapter.send_message(trace, step.text)
            elif step.kind == "approve_pending":
                trace = adapter.approve_pending(trace, step.tool)
            elif step.kind == "reject_pending":
                trace = adapter.reject_pending(trace, step.tool)
        if trace.pending_actions:
            trace.events.append({"type": "pending_actions_remaining", "tools": list(trace.pending_actions)})
        return trace

