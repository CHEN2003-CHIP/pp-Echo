from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from pp_agent.llm.models import ModelConfig, ProviderConfig


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


class Settings(BaseModel):
    workspace: Path
    global_dir: Path
    project_dir: Path
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    tool_policy: ToolPolicyConfig = Field(default_factory=ToolPolicyConfig)
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

