from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TaskNode(BaseModel):
    id: str
    title: str
    objective: str
    agent: str
    depends_on: list[str] = Field(default_factory=list)
    allow_edits: bool = False
    required_capabilities: list[str] = Field(default_factory=list)
    status: str = "pending"
    timeout_seconds: int = 300
    max_retries: int = 0
    attempt: int = 0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    skip_reason: str = ""
    patch_artifact_id: Optional[str] = None


class WorkflowTemplate(BaseModel):
    name: str
    nodes: list[TaskNode]


def workflow_template(name: str, *, allow_edits: bool = False) -> WorkflowTemplate:
    if name == "debug":
        return WorkflowTemplate(
            name="debug",
            nodes=[
                TaskNode(id="memory_lookup", title="Memory lookup", objective="Find relevant remembered context.", agent="memory-scout"),
                TaskNode(id="test_investigation", title="Test investigation", objective="Inspect failing tests and likely causes.", agent="test-investigator"),
                TaskNode(id="change_review", title="Change review", objective="Review current diff and risks.", agent="change-reviewer"),
            ],
        )
    if name == "code_change":
        return WorkflowTemplate(
            name="code_change",
            nodes=[
                TaskNode(id="memory_lookup", title="Memory lookup", objective="Find relevant remembered context.", agent="memory-scout"),
                TaskNode(id="repo_research", title="Repository research", objective="Inspect relevant implementation paths.", agent="repo-researcher"),
                TaskNode(id="api_trace", title="API trace", objective="Trace interfaces and call sites.", agent="api-scout"),
                TaskNode(
                    id="implementation_plan",
                    title="Implementation plan",
                    objective="Turn research into a minimal implementation plan.",
                    agent="implementation-planner",
                    depends_on=["memory_lookup", "repo_research", "api_trace"],
                ),
                TaskNode(
                    id="code_patch",
                    title="Code patch",
                    objective="Prepare scoped staged edits from the implementation plan.",
                    agent="code-worker",
                    depends_on=["implementation_plan"],
                    allow_edits=allow_edits,
                    required_capabilities=["worktree"] if allow_edits else [],
                    timeout_seconds=600,
                    max_retries=1 if allow_edits else 0,
                ),
                TaskNode(
                    id="change_review",
                    title="Change review",
                    objective="Review staged changes or failure state and current diff.",
                    agent="change-reviewer",
                    depends_on=["code_patch"],
                ),
            ],
        )
    return WorkflowTemplate(
        name="research",
        nodes=[
            TaskNode(id="memory_lookup", title="Memory lookup", objective="Find relevant remembered context.", agent="memory-scout"),
            TaskNode(id="repo_research", title="Repository research", objective="Inspect relevant implementation paths.", agent="repo-researcher"),
            TaskNode(id="api_trace", title="API trace", objective="Trace interfaces and call sites.", agent="api-scout"),
        ],
    )


__all__ = ["TaskNode", "WorkflowTemplate", "workflow_template"]
