from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from pp_agent.storage.models import StoredModelConfig, StoredProviderConfig


DEFAULT_SYSTEM_PROMPT = """You are a careful personal coding agent running on Windows 10.
Use tools when needed, prefer reading before editing, and explain actions clearly.
For file changes, prefer staging a diff preview first and only applying it after confirmation.
For high-risk plans, pause at the planner layer and wait for approval before executing them."""


class ToolPolicyConfig(BaseModel):
    shell_timeout_seconds: int = 30
    confirm_write_file: bool = True
    confirm_edit_file: bool = True
    confirm_run_shell: bool = True
    confirm_high_risk_plan: bool = True


class BuiltinToolCapabilityConfig(BaseModel):
    enable: bool = True


class SkillCapabilityConfig(BaseModel):
    enable_project: bool = True
    enable_user: bool = True
    enable_builtin: bool = True
    custom_directories: list[str] = Field(default_factory=list)
    ignored: list[str] = Field(default_factory=list)
    include: list[str] = Field(default_factory=list)

    def custom_paths(self) -> list[Path]:
        return [Path(value).expanduser() for value in self.custom_directories]

    def includes_name(self, name: str) -> bool:
        if self.include and not any(fnmatch.fnmatch(name, pattern) for pattern in self.include):
            return False
        if any(fnmatch.fnmatch(name, pattern) for pattern in self.ignored):
            return False
        return True


class MCPCapabilityConfig(BaseModel):
    enable: bool = False
    config_paths: list[str] = Field(default_factory=list)
    server_filters: list[str] = Field(default_factory=list)

    def resolved_config_paths(self, project_dir: Path) -> list[Path]:
        if self.config_paths:
            return [Path(value).expanduser() for value in self.config_paths]
        return [project_dir / "mcp.json"]

    def includes_server(self, name: str) -> bool:
        if not self.server_filters:
            return True
        return any(fnmatch.fnmatch(name, pattern) for pattern in self.server_filters)


class ExtensionCapabilityConfig(BaseModel):
    enable_project: bool = True
    enable_user: bool = True
    enable_builtin: bool = False
    custom_directories: list[str] = Field(default_factory=list)
    ignored: list[str] = Field(default_factory=list)
    include: list[str] = Field(default_factory=list)

    def custom_paths(self) -> list[Path]:
        return [Path(value).expanduser() for value in self.custom_directories]

    def includes_name(self, name: str) -> bool:
        if self.include and not any(fnmatch.fnmatch(name, pattern) for pattern in self.include):
            return False
        if any(fnmatch.fnmatch(name, pattern) for pattern in self.ignored):
            return False
        return True


class CapabilitySettings(BaseModel):
    builtin_tools: BuiltinToolCapabilityConfig = Field(default_factory=BuiltinToolCapabilityConfig)
    skills: SkillCapabilityConfig = Field(default_factory=SkillCapabilityConfig)
    mcp: MCPCapabilityConfig = Field(default_factory=MCPCapabilityConfig)
    extensions: ExtensionCapabilityConfig = Field(default_factory=ExtensionCapabilityConfig)


class Settings(BaseModel):
    workspace: Path
    global_dir: Path
    project_dir: Path
    provider: StoredProviderConfig = Field(default_factory=StoredProviderConfig)
    model: StoredModelConfig = Field(default_factory=StoredModelConfig)
    tool_policy: ToolPolicyConfig = Field(default_factory=ToolPolicyConfig)
    capabilities: CapabilitySettings = Field(default_factory=CapabilitySettings)
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    @classmethod
    def load(cls, workspace: Path) -> "Settings":
        workspace = workspace.resolve()
        project_dir = workspace / ".pp-agent"
        project_dir.mkdir(parents=True, exist_ok=True)
        global_dir = cls._resolve_global_dir(project_dir)

        settings = cls(workspace=workspace, global_dir=global_dir, project_dir=project_dir)
        settings._apply_environment_overrides()
        settings._apply_project_config()

        agents_md = workspace / "AGENTS.md"
        system_md = project_dir / "SYSTEM.md"
        if agents_md.exists():
            settings.system_prompt += "\n\nWorkspace instructions:\n" + agents_md.read_text(encoding="utf-8")
        if system_md.exists():
            settings.system_prompt = system_md.read_text(encoding="utf-8")
        return settings

    @staticmethod
    def _resolve_global_dir(project_dir: Path) -> Path:
        local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        candidates = []
        if os.getenv("PP_AGENT_HOME"):
            candidates.append(Path(os.environ["PP_AGENT_HOME"]))
        candidates.extend([
            local_app_data / "pp-agent",
            project_dir / "global",
        ])

        for candidate in candidates:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except PermissionError:
                continue
        raise PermissionError("Unable to create a writable pp-agent state directory")

    def _apply_environment_overrides(self) -> None:
        if os.getenv("PP_AGENT_BASE_URL"):
            self.provider.base_url = os.environ["PP_AGENT_BASE_URL"]
        if os.getenv("PP_AGENT_MODEL"):
            self.model.model = os.environ["PP_AGENT_MODEL"]
        if os.getenv("PP_AGENT_ENABLE_THINKING"):
            self.model.enable_thinking = os.environ["PP_AGENT_ENABLE_THINKING"].strip().lower() in {"1", "true", "yes", "on"}

    def _apply_project_config(self) -> None:
        config_path = self.project_dir / "config.json"
        if not config_path.exists():
            return

        data = json.loads(config_path.read_text(encoding="utf-8"))
        if "model" in data:
            self.model.model = data["model"]
        if "base_url" in data:
            self.provider.base_url = data["base_url"]
        if "enable_thinking" in data:
            self.model.enable_thinking = bool(data["enable_thinking"])
        if "shell_timeout_seconds" in data:
            self.tool_policy.shell_timeout_seconds = int(data["shell_timeout_seconds"])
        tool_confirm = data.get("tool_confirmation", {})
        if "write_file" in tool_confirm:
            self.tool_policy.confirm_write_file = bool(tool_confirm["write_file"])
        if "edit_file" in tool_confirm:
            self.tool_policy.confirm_edit_file = bool(tool_confirm["edit_file"])
        if "run_shell" in tool_confirm:
            self.tool_policy.confirm_run_shell = bool(tool_confirm["run_shell"])
        if "high_risk_plan" in tool_confirm:
            self.tool_policy.confirm_high_risk_plan = bool(tool_confirm["high_risk_plan"])

        capability_config = data.get("capabilities", {})
        if capability_config:
            self._apply_capability_config(capability_config)

    def _apply_capability_config(self, capability_config: dict) -> None:
        builtin_tools = capability_config.get("builtin_tools", {})
        if "enable" in builtin_tools:
            self.capabilities.builtin_tools.enable = bool(builtin_tools["enable"])

        skill_config = capability_config.get("skills", {})
        if "enable_project" in skill_config:
            self.capabilities.skills.enable_project = bool(skill_config["enable_project"])
        if "enable_user" in skill_config:
            self.capabilities.skills.enable_user = bool(skill_config["enable_user"])
        if "enable_builtin" in skill_config:
            self.capabilities.skills.enable_builtin = bool(skill_config["enable_builtin"])
        if "custom_directories" in skill_config:
            self.capabilities.skills.custom_directories = [str(value) for value in skill_config["custom_directories"]]
        if "ignored" in skill_config:
            self.capabilities.skills.ignored = [str(value) for value in skill_config["ignored"]]
        if "include" in skill_config:
            self.capabilities.skills.include = [str(value) for value in skill_config["include"]]

        mcp_config = capability_config.get("mcp", {})
        if "enable" in mcp_config:
            self.capabilities.mcp.enable = bool(mcp_config["enable"])
        if "config_paths" in mcp_config:
            self.capabilities.mcp.config_paths = [str(value) for value in mcp_config["config_paths"]]
        if "server_filters" in mcp_config:
            self.capabilities.mcp.server_filters = [str(value) for value in mcp_config["server_filters"]]

        extension_config = capability_config.get("extensions", {})
        if "enable_project" in extension_config:
            self.capabilities.extensions.enable_project = bool(extension_config["enable_project"])
        if "enable_user" in extension_config:
            self.capabilities.extensions.enable_user = bool(extension_config["enable_user"])
        if "enable_builtin" in extension_config:
            self.capabilities.extensions.enable_builtin = bool(extension_config["enable_builtin"])
        if "custom_directories" in extension_config:
            self.capabilities.extensions.custom_directories = [str(value) for value in extension_config["custom_directories"]]
        if "ignored" in extension_config:
            self.capabilities.extensions.ignored = [str(value) for value in extension_config["ignored"]]
        if "include" in extension_config:
            self.capabilities.extensions.include = [str(value) for value in extension_config["include"]]
