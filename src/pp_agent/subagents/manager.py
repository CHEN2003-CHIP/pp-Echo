from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from pp_agent.runtime.lifecycle import SUBAGENT_END, SUBAGENT_FAIL, SUBAGENT_START
from pp_agent.subagents.catalog import SubAgentCatalog
from pp_agent.subagents.runtime_adapter import SubAgentRuntimeAdapter, SubAgentTurnLimitReached
from pp_agent.subagents.specs import (
    SubAgentRunResult,
    SubAgentSpec,
    failure_result,
    parse_subagent_output,
)

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
        catalog: Optional[SubAgentCatalog] = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.session_host = session_host
        self.parent_registry = parent_registry
        self.session_store = session_store
        self.runtime_factory = runtime_factory or self._default_runtime_factory()
        self.catalog = catalog or SubAgentCatalog(specs)

    def list_specs(self) -> list[SubAgentSpec]:
        return self.catalog.list()

    def get_spec(self, name: str) -> Optional[SubAgentSpec]:
        return self.catalog.get(name)

    def run_sync(
        self,
        *,
        parent_session_id: str,
        parent_head_id: Optional[str],
        spec_name: str,
        task: str,
    ) -> SubAgentRunResult:
        started_at = self._now()
        spec = self.get_spec(spec_name)
        if spec is None:
            return failure_result(
                spec_name=spec_name,
                session_id="",
                active_head_id=None,
                message=f"Subagent '{spec_name}' is not available.",
                failure_kind="spec_not_found",
                started_at=started_at,
                finished_at=self._now(),
            )
        if spec.return_format != "summary":
            return failure_result(
                spec_name=spec.name,
                session_id="",
                active_head_id=None,
                message=f"Subagent '{spec.name}' only supports summary output in this MVP.",
                failure_kind="child_runtime_error",
                started_at=started_at,
                finished_at=self._now(),
            )
        validation_error = self._validate_spec(spec)
        if validation_error is not None:
            return failure_result(
                spec_name=spec.name,
                session_id="",
                active_head_id=None,
                message=validation_error,
                failure_kind="tool_validation_failed",
                started_at=started_at,
                finished_at=self._now(),
            )

        forked = self.session_host.fork_session(
            self.workspace,
            parent_session_id,
            head_id=parent_head_id,
        )
        child_session_id = forked.session_id
        child_head_id = forked.active_head_id
        try:
            child_record = self.session_store.load(child_session_id)
            child_runtime = self.runtime_factory(self.workspace, child_record, None)
            child = SubAgentRuntimeAdapter(child_runtime)
            child.restore_session_record(child_record, emit_event=False)
            child.set_system_prompt(spec.system_prompt)
            child.set_require_plan_approval(spec.require_plan_approval)
            child.set_model_override(spec.model_override)
            child.set_tool_registry(
                build_subagent_tool_registry(
                    self.parent_registry,
                    self.workspace,
                    child_session_id,
                    spec.tool_allowlist,
                )
            )
            child.queue_lifecycle_event(
                SUBAGENT_START,
                details={
                    "parent_session_id": parent_session_id,
                    "spec_name": spec.name,
                    "max_turns": spec.max_turns,
                },
            )
            events = child.prompt(self._build_subagent_prompt(spec, task), max_turns=spec.max_turns)
            final_text = child.extract_final_text()
            tool_calls_used = self._tool_calls_used(events)
            active_head_id = child_runtime.session_store.load(child_session_id).active_head_id
            finished_at = self._now()
            if self._used_tool_result_fallback(events):
                message = "Subagent model returned an empty response after tool results, so no reliable summary was produced."
                child.emit_lifecycle_event(
                    SUBAGENT_FAIL,
                    message=message,
                    details={"spec_name": spec.name, "failure_kind": "child_runtime_error"},
                    is_error=True,
                )
                return failure_result(
                    spec_name=spec.name,
                    session_id=child_session_id,
                    active_head_id=active_head_id,
                    message=message,
                    failure_kind="child_runtime_error",
                    tool_calls_used=tool_calls_used,
                    event_count=len(events),
                    started_at=started_at,
                    finished_at=finished_at,
                )
            if not final_text:
                message = "Subagent completed without producing a final summary."
                child.emit_lifecycle_event(
                    SUBAGENT_FAIL,
                    message=message,
                    details={"spec_name": spec.name, "failure_kind": "empty_result"},
                    is_error=True,
                )
                return failure_result(
                    spec_name=spec.name,
                    session_id=child_session_id,
                    active_head_id=active_head_id,
                    message=message,
                    failure_kind="empty_result",
                    tool_calls_used=tool_calls_used,
                    event_count=len(events),
                    started_at=started_at,
                    finished_at=finished_at,
                )
            parsed = parse_subagent_output(final_text)
            result = SubAgentRunResult(
                spec_name=spec.name,
                session_id=child_session_id,
                active_head_id=active_head_id,
                summary=str(parsed["summary"]),
                findings=list(parsed["findings"]),
                recommended_next_action=str(parsed["recommended_next_action"]),
                inspected_paths=list(parsed["inspected_paths"]),
                confidence=str(parsed["confidence"]),
                final_text=final_text,
                tool_calls_used=tool_calls_used,
                event_count=len(events),
                success=True,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=max(int((finished_at - started_at) * 1000), 0),
            )
            child.emit_lifecycle_event(
                SUBAGENT_END,
                details={
                    "spec_name": spec.name,
                    "tool_calls_used": tool_calls_used,
                    "event_count": len(events),
                    "duration_ms": result.duration_ms,
                },
            )
            return result
        except SubAgentTurnLimitReached as exc:
            finished_at = self._now()
            return failure_result(
                spec_name=spec.name,
                session_id=child_session_id,
                active_head_id=child_head_id,
                message=self._safe_error_message(exc),
                failure_kind="turn_limit_reached",
                started_at=started_at,
                finished_at=finished_at,
            )
        except Exception as exc:  # noqa: BLE001
            finished_at = self._now()
            message = self._safe_error_message(exc)
            try:
                child.emit_lifecycle_event(  # type: ignore[name-defined]
                    SUBAGENT_FAIL,
                    message=message,
                    details={"spec_name": spec.name, "failure_kind": "child_runtime_error"},
                    is_error=True,
                )
            except Exception:
                pass
            return failure_result(
                spec_name=spec.name,
                session_id=child_session_id,
                active_head_id=child_head_id,
                message=message,
                failure_kind="child_runtime_error",
                started_at=started_at,
                finished_at=finished_at,
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
            "- Never call `spawn_subagent`.\n"
            "- Return summary output only.\n\n"
            "Output format:\n"
            "0. Summary\n"
            "1. Findings\n"
            "2. Recommended next action\n"
            "3. Files/paths inspected\n"
            "4. Confidence\n"
        )

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
    def _used_tool_result_fallback(events) -> bool:
        for event in events:
            if event.type == "provider_response" and event.details.get("fallback") == "tool_results":
                return True
        return False

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        message = str(exc).strip() or exc.__class__.__name__
        return message.splitlines()[0][:240]

    def _validate_spec(self, spec: SubAgentSpec) -> Optional[str]:
        metadata = self.parent_registry.metadata()
        for name in spec.tool_allowlist:
            if name == "spawn_subagent":
                return f"Subagent '{spec.name}' cannot allow tool 'spawn_subagent'."
            if name not in metadata:
                return f"Subagent '{spec.name}' references unknown tool '{name}'."
        return None

    @staticmethod
    def _now() -> float:
        import time

        return time.time()

    @staticmethod
    def _default_runtime_factory() -> RuntimeFactory:
        bootstrap = import_module("pp_agent.app.bootstrap")
        return bootstrap.create_runtime_from_record
