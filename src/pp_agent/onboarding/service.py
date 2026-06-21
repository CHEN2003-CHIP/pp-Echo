from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pp_agent.llm.connectivity import ModelConnectivityService
from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.onboarding import checks
from pp_agent.onboarding.schema import OnboardingCheck, OnboardingCommandHint, OnboardingNextStep, OnboardingStatus
from pp_agent.storage.settings import Settings


class OnboardingService:
    """Builds Startup Guide and CLI onboarding checks from one shared implementation."""

    def build_status(self, workspace: Path, *, include_model_check: bool = False) -> OnboardingStatus:
        root = workspace.resolve()
        check_fns: list[tuple[str, Callable[[], OnboardingCheck]]] = [
            ("python", checks.check_python_version),
            ("node", checks.check_node_version),
            ("npm", checks.check_npm_available),
            ("api_key", checks.check_api_key),
            ("project_import", checks.check_project_import),
            ("workspace", lambda: checks.check_workspace(root)),
            ("git_available", checks.check_git_available),
            ("git_repo", lambda: checks.check_git_repo(root)),
            ("trace_store", lambda: checks.check_trace_store(root)),
            ("memory", lambda: checks.check_memory_status(root)),
            ("eval", lambda: checks.check_eval_assets(root)),
            ("web_build", lambda: checks.check_web_build_hint(root)),
        ]
        items = [self._safe_check(check_id, fn) for check_id, fn in check_fns]
        if include_model_check:
            items.append(self.check_model_connectivity(root))
        return OnboardingStatus(
            workspace=str(root),
            overall_status=self._overall_status(items),
            checks=items,
            command_hints=self._command_hints(),
            next_steps=self._next_steps(),
        )

    def check_model_connectivity(self, workspace: Path) -> OnboardingCheck:
        """Run the explicit, low-token model connection probe used by Web and CLI."""

        settings = Settings.load(workspace)
        result = ModelConnectivityService().test(
            ProviderConfig(**settings.provider.model_dump(mode="python")),
            ModelConfig(**settings.model.model_dump(mode="python")),
        )
        if result.status == "ok":
            return OnboardingCheck(
                id="model_connectivity",
                title="Model connection",
                status="ok",
                summary=result.message,
                detail=result.safe_detail,
            )
        return OnboardingCheck(
            id="model_connectivity",
            title="Model connection",
            status="warning" if result.status == "warning" else "error",
            summary=result.message,
            detail=result.safe_detail or f"{result.provider} / {result.model} / env: {result.api_key_env}",
        )

    def _safe_check(self, check_id: str, fn: Callable[[], OnboardingCheck]) -> OnboardingCheck:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            return OnboardingCheck(id=check_id, title=check_id.replace("_", " ").title(), status="warning", summary="Check failed", detail=str(exc))

    @staticmethod
    def _overall_status(items: list[OnboardingCheck]) -> str:
        critical_errors = {"python", "project_import", "workspace"}
        if any(item.status == "error" and item.id in critical_errors for item in items):
            return "blocked"
        if any(item.status in {"warning", "error"} for item in items):
            return "partial"
        return "ready"

    @staticmethod
    def _command_hints() -> list[OnboardingCommandHint]:
        return [
            OnboardingCommandHint(title="Set API key", command='setx PP_AGENT_API_KEY "your_api_key"', description="On Windows, setx persists the key for new terminals."),
            OnboardingCommandHint(title="Start CLI", command="python -m pp_agent.cli.main chat", description="Open an interactive terminal session."),
            OnboardingCommandHint(title="Start Web", command=".\\start-web.bat", description="Start Web and open the pp-Echo Startup Guide from the top-left icon."),
            OnboardingCommandHint(title="Run doctor", command="python -m pp_agent.cli.main workflow doctor --json", description="Inspect deeper runtime readiness diagnostics."),
        ]

    @staticmethod
    def _next_steps() -> list[OnboardingNextStep]:
        return [
            OnboardingNextStep(title="Run a safe first task", description="Ask the Agent to read README and summarize modules without editing files or running shell.", action_label="Back to chat", target_view="chat"),
            OnboardingNextStep(title="Inspect Agent Trace", description="After a task, open TraceInspect to review tokens, tools, approvals, memory, checkpoints, and errors.", action_label="Open TraceInspect", target_view="traceInspect"),
            OnboardingNextStep(title="Run deterministic eval", description="Use the default eval suite to verify key capabilities without depending on a live LLM.", action_label="View command"),
            OnboardingNextStep(title="Read the source roadmap", description="Start from docs/source-reading-roadmap.md to understand runtime, tools, memory, and observability.", action_label="View docs"),
        ]
