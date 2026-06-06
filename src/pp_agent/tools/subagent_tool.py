from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from pp_agent.domain import TextPart, ToolSpec
from pp_agent.subagents.contract import canonicalize_orchestration_arguments
from pp_agent.subagents.orchestrator import SubAgentOrchestrator, default_manager_factory
from pp_agent.subagents.specs import SubAgentSpec, render_subagent_tool_message
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
    """
    主 Agent 用来启动受控子 Agent 的工具。

    SpawnSubagentTool 会把一个明确的子任务交给新的 AgentRuntime 执行。
    子 Agent 拥有独立上下文和会话状态，通常受 capability profile 限制，
    只能使用指定工具或在隔离 worktree 中操作。

    执行流程：
    1. 父 Agent 调用 spawn_subagent，传入 task / label / profile 等参数；
    2. 工具通过 SessionHost 创建子会话和子 AgentRuntime；
    3. 子 Agent 独立运行自己的 prompt 和 _run_loop；
    4. 子 Agent 完成后返回摘要、状态、工具使用情况或 artifact 信息；
    5. SpawnSubagentTool 将结果包装成 ToolExecutionResult；
    6. 父 Agent 把该结果作为 observation 写回 messages 并继续推理。

    它不是普通的一步工具，而是“子 Agent 会话启动器”。
    主要用于上下文隔离、任务委托、权限收敛和风险隔离。
    """
    def __init__(
        self,
        workspace: Path,
        *,
        session_host: SessionHost,
        session_store: SessionStore,
        parent_registry: ToolRegistry,
        current_session_id: str,
        runtime_factory: Optional[RuntimeFactory] = None,
        subagent_specs: Optional[dict[str, SubAgentSpec]] = None,
    ) -> None:
        super().__init__(workspace)
        self.session_host = session_host
        self.session_store = session_store
        self.parent_registry = parent_registry
        self.current_session_id = current_session_id
        self.runtime_factory = runtime_factory
        self.subagent_specs = subagent_specs

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
                specs=self.subagent_specs,
                event_sink=getattr(self.parent_registry, "emit_runtime_event", None),
                cancellation_token=getattr(self.parent_registry, "cancellation_token", None),
            )
            result = manager.run_sync(
                parent_session_id=self.current_session_id,
                parent_head_id=parent_record.active_head_id,
                spec_name=subagent_type,
                task=task,
                cancellation_token=getattr(self.parent_registry, "cancellation_token", None),
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


class OrchestrateAgentsTool(BaseTool):
    def __init__(
        self,
        workspace: Path,
        *,
        session_host: SessionHost,
        session_store: SessionStore,
        parent_registry: ToolRegistry,
        current_session_id: str,
        runtime_factory: Optional[RuntimeFactory] = None,
        subagent_specs: Optional[dict[str, SubAgentSpec]] = None,
    ) -> None:
        super().__init__(workspace)
        self.session_host = session_host
        self.session_store = session_store
        self.parent_registry = parent_registry
        self.current_session_id = current_session_id
        self.runtime_factory = runtime_factory
        self.subagent_specs = subagent_specs

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="orchestrate_agents",
            description=(
                "Run an OpenClaw-style parallel subagent workflow. Use for complex repository research, "
                "debugging, or implementation planning. Set allow_edits=true only when the user explicitly "
                "allows subagents to stage file edits."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "workflow": {"type": "string", "enum": ["auto", "research", "debug", "code_change"]},
                    "max_agents": {"type": "integer", "default": 4},
                    "allow_edits": {"type": "boolean", "default": False},
                    "run_timeout_seconds": {"type": "integer", "default": 900},
                },
                "required": ["goal"],
            },
            permission_domain=PermissionDomain.READ,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        parent_record = self.session_store.load(self.current_session_id)
        latest_user_text = _latest_user_text_from_record(self.session_store, parent_record)
        canonical_arguments, contract_metadata = canonicalize_orchestration_arguments(
            arguments,
            latest_user_text=latest_user_text,
        )
        arguments = canonical_arguments
        goal = str(arguments["goal"]).strip()
        if not goal:
            raise ValueError("goal is required")
        workflow = str(arguments.get("workflow") or "auto")
        max_agents = int(arguments.get("max_agents") or 4)
        max_agents_explicit = "max_agents" in arguments
        allow_edits = bool(arguments.get("allow_edits", False))
        run_timeout_seconds = int(arguments.get("run_timeout_seconds") or 900)
        orchestrator = SubAgentOrchestrator(
            workspace=self.workspace,
            manager_factory=default_manager_factory(
                workspace=self.workspace,
                session_host=self.session_host,
                parent_registry=self.parent_registry,
                session_store=self.session_store,
                runtime_factory=self.runtime_factory,
                event_sink=getattr(self.parent_registry, "emit_runtime_event", None),
                cancellation_token=getattr(self.parent_registry, "cancellation_token", None),
            ),
            parent_session_id=self.current_session_id,
            parent_head_id=parent_record.active_head_id,
            event_sink=getattr(self.parent_registry, "emit_runtime_event", None),
            cancellation_token=getattr(self.parent_registry, "cancellation_token", None),
            specs=self.subagent_specs,
        )
        result = orchestrator.run(
            goal=goal,
            workflow=workflow,
            max_agents=max_agents,
            allow_edits=allow_edits,
            run_timeout_seconds=run_timeout_seconds,
            max_agents_explicit=max_agents_explicit,
        )
        payload = result.to_dict()
        if contract_metadata.get("orchestrated_edit_contract"):
            payload["orchestrated_edit_contract"] = contract_metadata
        content = _render_orchestration_content(payload)
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=content,
            is_error=not (result.success or result.partial_success),
            details=payload,
        )


def _latest_user_text_from_record(session_store: SessionStore, record: Any) -> str:
    try:
        messages = session_store.branch_messages(record, record.active_head_id)
    except Exception:  # noqa: BLE001
        messages = list(getattr(record, "messages", []) or [])
    for message in reversed(messages):
        if getattr(message, "role", None) != "user":
            continue
        parts = [
            part.text.strip()
            for part in getattr(message, "content", []) or []
            if isinstance(part, TextPart) and part.text.strip()
        ]
        if parts:
            return "\n".join(parts).strip()
    return ""


def _render_orchestration_content(payload: dict[str, object]) -> str:
    lines = [
        f"Multi-agent orchestration {('succeeded' if payload.get('success') else 'completed')}",
        f"Workflow: {payload.get('workflow')}",
        f"Summary: {payload.get('final_summary')}",
    ]
    steps = payload.get("steps")
    if isinstance(steps, list):
        for index, raw_step in enumerate(steps, start=1):
            if not isinstance(raw_step, dict):
                continue
            status = str(raw_step.get("status") or "").strip()
            failure_kind = str(raw_step.get("failure_kind") or "").strip()
            status_label = f"{status}/{failure_kind}" if failure_kind and status != "success" else status
            lines.append(
                f"{index}. {raw_step.get('agent')} [{status_label}]: "
                f"{str(raw_step.get('summary') or raw_step.get('error_message') or '').strip()}"
            )
            session_id = str(raw_step.get("session_id") or "").strip()
            if session_id:
                lines.append(f"   child session: {session_id}")
            if raw_step.get("parse_error"):
                lines.append("   parse_error: child output did not match the summary contract")
            staged = raw_step.get("staged_actions")
            if isinstance(staged, list) and staged:
                tokens = ", ".join(str(item.get("token")) for item in staged if isinstance(item, dict))
                action_types = ", ".join(str(item.get("action_type")) for item in staged if isinstance(item, dict))
                label = "staged patch artifacts" if "apply_patch_artifact" in action_types else "staged edits"
                lines.append(f"   {label}: {tokens}")
                if "apply_patch_artifact" in action_types:
                    changed_paths = sorted(
                        {
                            str(path)
                            for item in staged
                            if isinstance(item, dict)
                            for path in (item.get("changed_paths") or [])
                            if str(path).strip()
                        }
                        | {
                            str(path)
                            for path in (raw_step.get("inspected_paths") or [])
                            if str(path).strip() and not str(path).strip().endswith(".patch")
                        }
                    )
                    if changed_paths:
                        lines.append(f"   pending changed paths: {', '.join(changed_paths)}")
                    lines.append("   status: staged only, not applied to the main workspace")
                    lines.append("   next: use the Approval panel or approve_pending_action to apply the patch artifact before reading the changed path from the main workspace")
    lines.append(f"Next: {payload.get('recommended_next_action')}")
    return "\n".join(line for line in lines if line.strip())
