from __future__ import annotations

from pp_agent.subagents.scheduler import DeterministicScheduler
from pp_agent.subagents.task_graph import workflow_template


def test_code_change_task_graph_dependencies_are_deterministic():
    scheduler = DeterministicScheduler(workflow_template("code_change", allow_edits=True))
    batches = [[node.id for node in batch] for batch in scheduler.runnable_batches()]

    assert batches == [
        ["memory_lookup", "repo_research", "api_trace"],
        ["implementation_plan"],
        ["code_patch"],
        ["change_review"],
    ]
    assert scheduler.node("code_patch").depends_on == ["implementation_plan"]
    assert scheduler.node("change_review").depends_on == ["code_patch"]
    assert scheduler.node("code_patch").required_capabilities == ["worktree"]
    assert scheduler.node("code_patch").max_retries == 1
    assert scheduler.node("code_patch").timeout_seconds == 600
