from __future__ import annotations

from pathlib import Path
from typing import Optional

from pp_agent.cli.commands.approvals import approvals_summary_main
from pp_agent.cli.commands.run import run_main
from pp_agent.cli.commands.sessions import sessions_tree_main
from pp_agent.runtime.runtime import AgentRuntime


def run(prompt: str, workspace: Path, session_id: Optional[str] = None, json_mode: bool = False, mode: str = "default"):
    return run_main(prompt, workspace, session_id=session_id, json_mode=json_mode, mode=mode)


def chat(runtime: AgentRuntime) -> AgentRuntime:
    return runtime


def sessions_tree(workspace: Path, session_id: Optional[str] = None, sort_mode: str = "branch"):
    return sessions_tree_main(workspace, session_id=session_id, sort_mode=sort_mode)


def approvals_summary(workspace: Path):
    return approvals_summary_main(workspace)
