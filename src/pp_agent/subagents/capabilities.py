from __future__ import annotations

from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ToolCapabilityPolicy(BaseModel):
    """工具能力策略"""
    allowlist: list[str] = Field(default_factory=list)
    denylist: list[str] = Field(default_factory=list)
    allow_dynamic_tools: bool = False


class MCPPolicy(BaseModel):
    """MCP策略"""
    enabled: bool = False
    allowed_servers: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    allow_dynamic_tools: bool = False
    inject_context: bool = False


class SkillPolicy(BaseModel):
    """技能策略"""
    enabled: bool = False
    allowed_skills: list[str] = Field(default_factory=list)
    allow_auto_activation: bool = False
    inject_context: bool = False
    allow_skill_tools: bool = False
    allow_external_resources: bool = False


class MemoryPolicy(BaseModel):
    """内存策略"""
    allow_memory_search: bool = False
    allow_memory_get: bool = False
    allow_retrieval_hook: bool = False
    allow_project_memory_hook: bool = False


class ContextHookPolicy(BaseModel):
    """上下文钩子策略"""
    allow_mcp_hook: bool = False
    allow_skill_hook: bool = False
    allow_memory_hooks: bool = False
    allow_extension_hooks: bool = False


class WorkspacePolicy(BaseModel):
    mode: Literal["read_only", "staged_edits", "worktree"] = "read_only"
    allow_write_tools: bool = False
    worktree_path: Optional[str] = None
    parent_workspace: Optional[str] = None
    run_id: Optional[str] = None
    node_id: Optional[str] = None
    attempt: int = 1


class SubAgentProfile(BaseModel):
    """子代理配置"""
    name: str
    tool: ToolCapabilityPolicy = Field(default_factory=ToolCapabilityPolicy)
    mcp: MCPPolicy = Field(default_factory=MCPPolicy)
    skill: SkillPolicy = Field(default_factory=SkillPolicy)
    memory: MemoryPolicy = Field(default_factory=MemoryPolicy)
    context_hooks: ContextHookPolicy = Field(default_factory=ContextHookPolicy)
    workspace: WorkspacePolicy = Field(default_factory=WorkspacePolicy)

    @model_validator(mode="after")
    def _normalize_write_policy(self) -> "SubAgentProfile":
        if self.workspace.mode == "read_only":
            self.workspace.allow_write_tools = False
        if self.workspace.mode == "staged_edits":
            self.workspace.allow_write_tools = True
        if self.workspace.mode == "worktree":
            self.workspace.allow_write_tools = True
        return self


class RuntimeCreationOptions(BaseModel):
    """创建运行时选项"""
    mode: Literal["main", "subagent"] = "main"
    subagent_profile: Optional[SubAgentProfile] = None
    enable_mcp: bool = True
    enable_skills: bool = True
    enable_memory_hooks: bool = True
    enable_extension_hooks: bool = True

    @classmethod
    def main(cls) -> "RuntimeCreationOptions":
        return cls()

    @classmethod
    def for_subagent(cls, profile: SubAgentProfile) -> "RuntimeCreationOptions":
        return cls(
            mode="subagent",
            subagent_profile=profile,
            enable_mcp=profile.mcp.enabled and profile.context_hooks.allow_mcp_hook,
            enable_skills=profile.skill.enabled and profile.context_hooks.allow_skill_hook,
            enable_memory_hooks=profile.context_hooks.allow_memory_hooks,
            enable_extension_hooks=profile.context_hooks.allow_extension_hooks,
        )


class CapabilityAdmissionGate:
    """能力准入门槛"""
    WRITE_TOOLS = {"write_file", "edit_file", "run_shell", "execute_safe_rewind"}
    APPROVAL_EXECUTE_TOOLS = {"approve_pending_action", "reject_pending_action"}

    @staticmethod
    def allow_mcp_server(policy: MCPPolicy | None, server_name: str) -> bool:
        if policy is None:
            return True
        if not policy.enabled:
            return False
        return not policy.allowed_servers or server_name in policy.allowed_servers

    @staticmethod
    def allow_mcp_tool(policy: MCPPolicy | None, server_name: str, tool_name: str) -> bool:
        if policy is None:
            return True
        if not CapabilityAdmissionGate.allow_mcp_server(policy, server_name):
            return False
        qualified = f"{server_name}.{tool_name}" if "." not in tool_name else tool_name
        return not policy.allowed_tools or qualified in policy.allowed_tools

    @staticmethod
    def should_inject_mcp_context(policy: MCPPolicy | None) -> bool:
        return True if policy is None else bool(policy.enabled and policy.inject_context)

    @staticmethod
    def allow_skill(policy: SkillPolicy | None, skill_name: str) -> bool:
        if policy is None:
            return True
        if not policy.enabled:
            return False
        return not policy.allowed_skills or skill_name in policy.allowed_skills

    @staticmethod
    def allow_tool(profile: SubAgentProfile | None, tool_name: str, *, tool_family: str | None = None, category: str | None = None) -> bool:
        if profile is None:
            return True
        if tool_name in profile.tool.denylist:
            return False
        if profile.tool.allowlist and tool_name not in profile.tool.allowlist:
            return False
        if profile.workspace.mode == "read_only" and tool_name in CapabilityAdmissionGate.WRITE_TOOLS:
            return False
        if profile.workspace.mode == "read_only" and tool_name in CapabilityAdmissionGate.APPROVAL_EXECUTE_TOOLS:
            return False
        if profile.workspace.mode == "staged_edits" and tool_name in CapabilityAdmissionGate.APPROVAL_EXECUTE_TOOLS:
            return False
        if profile.workspace.mode == "worktree":
            if tool_name in CapabilityAdmissionGate.APPROVAL_EXECUTE_TOOLS:
                return False
            if tool_name in CapabilityAdmissionGate.WRITE_TOOLS and not profile.workspace.allow_write_tools:
                return False
        if tool_family == "mcp" or category == "mcp":
            if "." not in tool_name:
                return False
            server_name, mcp_tool = tool_name.split(".", 1)
            return CapabilityAdmissionGate.allow_mcp_tool(profile.mcp, server_name, mcp_tool)
        return True

    @staticmethod
    def allow_dynamic_registration(profile: SubAgentProfile | None, *, name: str, tool_family: str | None, category: str | None) -> bool:
        if profile is None:
            return True
        family = tool_family or ("mcp" if category == "mcp" else "extension" if category == "extension" else category)
        if family == "mcp" or category == "mcp":
            if not profile.mcp.allow_dynamic_tools:
                return False
            if "." not in name:
                return False
            server_name, tool_name = name.split(".", 1)
            return CapabilityAdmissionGate.allow_mcp_tool(profile.mcp, server_name, tool_name)
        if family == "extension" or category == "extension":
            return profile.tool.allow_dynamic_tools and CapabilityAdmissionGate.allow_tool(
                profile,
                name,
                tool_family=family,
                category=category,
            )
        return CapabilityAdmissionGate.allow_tool(profile, name, tool_family=family, category=category)


def profile_from_tool_allowlist(name: str, allowlist: list[str], *, allow_edits: bool = False) -> SubAgentProfile:
    write_allowed = bool(allow_edits and any(tool in allowlist for tool in ("write_file", "edit_file")))
    return SubAgentProfile(
        name=name,
        tool=ToolCapabilityPolicy(allowlist=list(allowlist), allow_dynamic_tools=False),
        workspace=WorkspacePolicy(mode="staged_edits" if write_allowed else "read_only", allow_write_tools=write_allowed),
    )


TraceSink = Callable[[str, dict[str, object]], None]


__all__ = [
    "CapabilityAdmissionGate",
    "ContextHookPolicy",
    "MCPPolicy",
    "MemoryPolicy",
    "RuntimeCreationOptions",
    "SkillPolicy",
    "SubAgentProfile",
    "ToolCapabilityPolicy",
    "TraceSink",
    "WorkspacePolicy",
    "profile_from_tool_allowlist",
]
