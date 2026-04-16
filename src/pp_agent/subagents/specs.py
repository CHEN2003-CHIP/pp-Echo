from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SubAgentSpec(BaseModel):
    name: str
    description: str
    system_prompt: str
    tool_allowlist: list[str] = Field(default_factory=list)
    model_override: Optional[str] = None
    require_plan_approval: bool = False
    max_turns: int = 1
    return_format: str = "summary"


class SubAgentRunResult(BaseModel):
    spec_name: str
    session_id: str
    active_head_id: Optional[str]
    final_text: str
    tool_calls_used: list[str] = Field(default_factory=list)
    event_count: int
    success: bool
    error_message: Optional[str] = None


def default_subagent_specs() -> dict[str, SubAgentSpec]:
    return {
        "repo-researcher": SubAgentSpec(
            name="repo-researcher",
            description="Analyze repository structure and related implementation, then return a concise summary.",
            system_prompt=(
                "You are repo-researcher, a focused repository analysis subagent. "
                "Inspect the codebase with read-only tools and return a concise working summary. "
                "Do not edit files, do not ask follow-up questions, and do not expand scope."
            ),
            tool_allowlist=["read_file", "list_files", "search_text", "grep_code"],
            require_plan_approval=False,
            max_turns=1,
            return_format="summary",
        ),
        "change-reviewer": SubAgentSpec(
            name="change-reviewer",
            description="Review current workspace changes, identify risks, and recommend the next action.",
            system_prompt=(
                "You are change-reviewer, a focused change review subagent. "
                "Inspect current repository changes with read-only tools and summarize risk and next steps. "
                "Do not edit files, do not ask follow-up questions, and do not expand scope."
            ),
            tool_allowlist=["read_file", "search_text", "grep_code", "git_status", "git_diff_worktree"],
            require_plan_approval=False,
            max_turns=1,
            return_format="summary",
        ),
    }
