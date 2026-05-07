from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from pp_agent.domain import ToolSpec
from pp_agent.subagents.specs import render_subagent_tool_message
from pp_agent.tools.base import BaseTool, ToolExecutionResult
from pp_agent.tools.policy import PermissionDomain

if TYPE_CHECKING:
    from pp_agent.runtime.session_host import SessionHost
    from pp_agent.storage.sessions import SessionStore
    from pp_agent.tools.registry import ToolRegistry

RuntimeFactory = Callable[[Path, Any, Optional[list[Callable]]], Any]


def _get_subagent_manager_class():
    from pp_agent.subagents.manager import SubAgentManager

    return SubAgentManager


class SpawnSubagentTool(BaseTool):
    def __init__(
        self,
        workspace: Path,
        *,
        session_host: SessionHost,
        session_store: SessionStore,
        parent_registry: ToolRegistry,
        current_session_id: str,
        runtime_factory: Optional[RuntimeFactory] = None,
    ) -> None:
        super().__init__(workspace)
        self.session_host = session_host
        self.session_store = session_store
        self.parent_registry = parent_registry
        self.current_session_id = current_session_id
        self.runtime_factory = runtime_factory

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="spawn_subagent",
            description="Delegate a focused subtask to a synchronous child agent and receive only its final summary.",
            parameters={
                "type": "object",
                "properties": {
                    "subagent_type": {"type": "string"},
                    "task": {"type": "string"},
                },
                "required": ["subagent_type", "task"],
            },
            permission_domain=PermissionDomain.READ,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        subagent_type = str(arguments["subagent_type"])
        task = str(arguments["task"])
        try:
            parent_record = self.session_store.load(self.current_session_id)
            manager_cls = _get_subagent_manager_class()
            manager = manager_cls(
                workspace=self.workspace,
                session_host=self.session_host,
                parent_registry=self.parent_registry,
                session_store=self.session_store,
                runtime_factory=self.runtime_factory,
            )
            result = manager.run_sync(
                parent_session_id=self.current_session_id,
                parent_head_id=parent_record.active_head_id,
                spec_name=subagent_type,
                task=task,
            )
            compact_content = render_subagent_tool_message(
                success=result.success,
                summary=result.summary,
                findings=result.findings,
                recommended_next_action=result.recommended_next_action,
                confidence=result.confidence,
                failure_kind=result.failure_kind,
            )
            return ToolExecutionResult(
                tool_call_id="",
                tool_name=self.spec.name,
                content=compact_content,
                is_error=not result.success,
                details={
                    "spec_name": result.spec_name,
                    "session_id": result.session_id,
                    "child_session_id": result.session_id,
                    "success": result.success,
                    "event_count": result.event_count,
                    "tool_calls_used": list(result.tool_calls_used),
                    "error_message": result.error_message,
                    "failure_kind": result.failure_kind,
                    "summary": result.summary,
                    "findings": list(result.findings),
                    "recommended_next_action": result.recommended_next_action,
                    "inspected_paths": list(result.inspected_paths),
                    "confidence": result.confidence,
                    "final_text": result.final_text,
                    "started_at": result.started_at,
                    "finished_at": result.finished_at,
                    "duration_ms": result.duration_ms,
                },
            )
        except Exception as exc:  # noqa: BLE001
            message = (str(exc).strip() or "Subagent execution failed.").splitlines()[0][:240]
            compact_content = render_subagent_tool_message(
                success=False,
                summary=message,
                findings=[f"Subagent run failed: {message}"],
                recommended_next_action="Review the task and retry.",
                confidence="low",
                failure_kind="child_runtime_error",
            )
            return ToolExecutionResult(
                tool_call_id="",
                tool_name=self.spec.name,
                content=compact_content,
                is_error=True,
                details={
                    "spec_name": subagent_type,
                    "session_id": "",
                    "success": False,
                    "event_count": 0,
                    "tool_calls_used": [],
                    "error_message": message,
                    "failure_kind": "child_runtime_error",
                    "summary": message,
                    "findings": [f"Subagent run failed: {message}"],
                    "recommended_next_action": "Review the task and retry.",
                    "inspected_paths": [],
                    "confidence": "low",
                    "final_text": compact_content,
                },
            )
