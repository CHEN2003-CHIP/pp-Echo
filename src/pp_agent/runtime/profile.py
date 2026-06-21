from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

RuntimeKind = Literal["native", "external_cli", "remote", "mock"]
IsolationMode = Literal["none", "workspace", "git_checkpoint", "worktree", "container"]


class RuntimeSupports(BaseModel):
    planning: bool = False
    tool_calling: bool = False
    approval: bool = False
    checkpoint: bool = False
    memory: bool = False
    mcp: bool = False
    subagent: bool = False
    streaming: bool = False
    file_edit: bool = False
    shell_exec: bool = False


class RuntimeIsolation(BaseModel):
    mode: IsolationMode = "none"
    description: Optional[str] = None


class RuntimeLimits(BaseModel):
    max_turns: Optional[int] = None
    max_tool_calls: Optional[int] = None
    timeout_seconds: Optional[int] = None


class RuntimeProfile(BaseModel):
    """
    RuntimeProfile describes who executes an Agent turn, not which model is called.

    pp_echo_native is the current in-process runtime. Future external CLI runtimes can
    register profiles here without being wired into execution by this registry alone.
    """

    id: str = "pp_echo_native"
    name: str = "pp-Echo Native Runtime"
    kind: RuntimeKind = "native"
    description: Optional[str] = None
    supports: RuntimeSupports = Field(default_factory=RuntimeSupports)
    isolation: RuntimeIsolation = Field(default_factory=RuntimeIsolation)
    limits: RuntimeLimits = Field(default_factory=RuntimeLimits)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def supports_summary(self) -> dict[str, bool]:
        """Return the compact support subset used by run metadata and trace events."""
        return {
            "planning": self.supports.planning,
            "tool_calling": self.supports.tool_calling,
            "approval": self.supports.approval,
            "checkpoint": self.supports.checkpoint,
            "memory": self.supports.memory,
            "mcp": self.supports.mcp,
            "subagent": self.supports.subagent,
            "streaming": self.supports.streaming,
            "file_edit": self.supports.file_edit,
            "shell_exec": self.supports.shell_exec,
        }


def default_runtime_profile() -> RuntimeProfile:
    """Build the built-in runtime profile from pp-Echo's current native capabilities."""
    return RuntimeProfile(
        id="pp_echo_native",
        name="pp-Echo Native Runtime",
        kind="native",
        description="In-process pp-Echo AgentRuntime using SessionHost, ToolRegistry, approvals, checkpoints, memory, MCP, and subagents.",
        supports=RuntimeSupports(
            planning=True,
            tool_calling=True,
            approval=True,
            checkpoint=True,
            memory=True,
            mcp=True,
            subagent=True,
            streaming=True,
            file_edit=True,
            shell_exec=True,
        ),
        isolation=RuntimeIsolation(
            mode="git_checkpoint",
            description="Workspace-scoped execution with approval gates and git-backed checkpoints when available.",
        ),
        metadata={"source": "configured"},
    )


def external_cli_placeholder_profile() -> RuntimeProfile:
    """Reserve the external CLI runtime shape without wiring any CLI execution."""
    return RuntimeProfile(
        id="external_cli_placeholder",
        name="External CLI Runtime Placeholder",
        kind="external_cli",
        description="Reserved profile for future Codex CLI, Claude Code, or OpenCode integration.",
        isolation=RuntimeIsolation(mode="worktree"),
        metadata={"source": "configured", "experimental": True, "wired": False},
    )
