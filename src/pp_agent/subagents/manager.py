from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from pp_agent.subagents.specs import SubAgentRunResult, SubAgentSpec, default_subagent_specs

if TYPE_CHECKING:
    from pp_agent.runtime.runtime import AgentRuntime
    from pp_agent.runtime.session_host import SessionHost
    from pp_agent.storage.sessions import SessionStore
    from pp_agent.tools.registry import ToolRegistry

RuntimeFactory = Callable[[Path, Any, Optional[list[Callable]]], Any]


def build_subagent_tool_registry(
    parent_registry: ToolRegistry,
    workspace: Path,
    current_session_id: str,
    allowlist: list[str],
) -> ToolRegistry:
    _ = workspace
    metadata = parent_registry.metadata()
    allowed_names = [
        name
        for name in allowlist
        if name in metadata
        and metadata[name].model_callable
        and name != "spawn_subagent"
    ]
    return parent_registry.clone_selected(allowed_names, current_session_id=current_session_id)


class SubAgentManager:
    def __init__(
        self,
        *,
        workspace: Path,
        session_host: SessionHost,
        parent_registry: ToolRegistry,
        session_store: SessionStore,
        runtime_factory: Optional[RuntimeFactory] = None,
        specs: Optional[dict[str, SubAgentSpec]] = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.session_host = session_host
        self.parent_registry = parent_registry
        self.session_store = session_store
        self.runtime_factory = runtime_factory or self._default_runtime_factory()
        self._specs = specs or default_subagent_specs()

    def list_specs(self) -> list[SubAgentSpec]:
        return [spec.model_copy(deep=True) for spec in self._specs.values()]

    def get_spec(self, name: str) -> Optional[SubAgentSpec]:
        spec = self._specs.get(name)
        return spec.model_copy(deep=True) if spec is not None else None

    def run_sync(
        self,
        *,
        parent_session_id: str,
        parent_head_id: Optional[str],
        spec_name: str,
        task: str,
    ) -> SubAgentRunResult:
        spec = self.get_spec(spec_name)
        if spec is None:
            return self._failure_result(
                spec_name=spec_name,
                session_id="",
                active_head_id=None,
                message=f"Subagent '{spec_name}' is not available.",
            )
        if spec.return_format != "summary":
            return self._failure_result(
                spec_name=spec.name,
                session_id="",
                active_head_id=None,
                message=f"Subagent '{spec.name}' only supports summary output in this MVP.",
            )

        forked = self.session_host.fork_session(
            self.workspace,
            parent_session_id,
            head_id=parent_head_id,
        )
        child_session_id = forked.session_id
        child_head_id = forked.active_head_id
        try:
            # Keep the child execution path intentionally narrow for the MVP:
            # fork, restore, inject child constraints, run one prompt, extract
            # only the final assistant summary.
            child_record = self.session_store.load(child_session_id)
            child_runtime = self.runtime_factory(self.workspace, child_record, None)
            child_runtime.restore_session_record(child_record, emit_event=False)
            child_runtime.state.system_prompt = spec.system_prompt
            child_runtime.require_plan_approval = spec.require_plan_approval
            child_runtime.tool_registry = build_subagent_tool_registry(
                self.parent_registry,
                self.workspace,
                child_session_id,
                spec.tool_allowlist,
            )
            events = child_runtime.prompt(self._build_subagent_prompt(spec, task))
            final_text = self._extract_final_text(child_runtime)
            tool_calls_used = self._tool_calls_used(events)
            active_head_id = child_runtime.session_store.load(child_session_id).active_head_id
            if not final_text:
                message = "Subagent completed without producing a final summary."
                return SubAgentRunResult(
                    spec_name=spec.name,
                    session_id=child_session_id,
                    active_head_id=active_head_id,
                    final_text=self._failure_summary(message),
                    tool_calls_used=tool_calls_used,
                    event_count=len(events),
                    success=False,
                    error_message=message,
                )
            return SubAgentRunResult(
                spec_name=spec.name,
                session_id=child_session_id,
                active_head_id=active_head_id,
                final_text=final_text,
                tool_calls_used=tool_calls_used,
                event_count=len(events),
                success=True,
            )
        except Exception as exc:  # noqa: BLE001
            return self._failure_result(
                spec_name=spec.name,
                session_id=child_session_id,
                active_head_id=child_head_id,
                message=self._safe_error_message(exc),
            )

    @staticmethod
    def _build_subagent_prompt(spec: SubAgentSpec, task: str) -> str:
        return (
            f"You are subagent '{spec.name}'.\n\n"
            f"Task:\n{task.strip()}\n\n"
            "Constraints:\n"
            "- Use only the tools already available to you.\n"
            "- Do not ask follow-up questions.\n"
            "- Do not expand the requested scope.\n"
            "- Return summary output only.\n\n"
            "Output format:\n"
            "1. Findings\n"
            "2. Recommended next action\n"
            "3. Files/paths inspected\n"
            "4. Confidence\n"
        )

    @staticmethod
    def _extract_final_text(runtime: AgentRuntime) -> str:
        for message in reversed(runtime.state.messages):
            if message.role != "assistant":
                continue
            parts = [part.text.strip() for part in message.content if getattr(part, "text", "").strip()]
            text = "\n".join(parts).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _tool_calls_used(events) -> list[str]:
        used: list[str] = []
        for event in events:
            if event.type != "tool_call" or not event.tool_name:
                continue
            if event.tool_name not in used:
                used.append(event.tool_name)
        return used

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        message = str(exc).strip() or exc.__class__.__name__
        return message.splitlines()[0][:240]

    @classmethod
    def _failure_result(
        cls,
        *,
        spec_name: str,
        session_id: str,
        active_head_id: Optional[str],
        message: str,
    ) -> SubAgentRunResult:
        return SubAgentRunResult(
            spec_name=spec_name,
            session_id=session_id,
            active_head_id=active_head_id,
            final_text=cls._failure_summary(message),
            tool_calls_used=[],
            event_count=0,
            success=False,
            error_message=message,
        )

    @staticmethod
    def _failure_summary(message: str) -> str:
        return (
            "Findings\n"
            f"- Subagent run failed: {message}\n\n"
            "Recommended next action\n"
            "- Review the request or child tool access and try again.\n\n"
            "Files/paths inspected\n"
            "- None\n\n"
            "Confidence\n"
            "- low\n"
        )

    @staticmethod
    def _default_runtime_factory() -> RuntimeFactory:
        bootstrap = import_module("pp_agent.app.bootstrap")
        return bootstrap.create_runtime_from_record
