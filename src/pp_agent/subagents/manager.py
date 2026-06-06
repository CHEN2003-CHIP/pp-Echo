from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from pp_agent.runtime.cancellation import CancellationToken, OperationCancelled
from pp_agent.runtime.lifecycle import SUBAGENT_END, SUBAGENT_FAIL, SUBAGENT_PROGRESS, SUBAGENT_START
from pp_agent.subagents.capabilities import RuntimeCreationOptions, SubAgentProfile
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

RuntimeFactory = Callable[..., Any]


def build_subagent_tool_registry(
    parent_registry: ToolRegistry,
    workspace: Path,
    current_session_id: str,
    allowlist: list[str],
    profile: SubAgentProfile | None = None,
    tool_workspace: Path | None = None,
) -> ToolRegistry:
    _ = workspace
    metadata = parent_registry.metadata()
    allowed_names = [
        name
        for name in allowlist
        if name in metadata
        and metadata[name].model_callable
        and name != "spawn_subagent"
        and name != "orchestrate_agents"
    ]
    if profile is not None:
        if profile.workspace.mode == "read_only":
            allowed_names = [name for name in allowed_names if name not in {"write_file", "edit_file", "run_shell", "approve_pending_action", "reject_pending_action"}]
        elif profile.workspace.mode == "staged_edits":
            allowed_names = [name for name in allowed_names if name not in {"approve_pending_action", "reject_pending_action"}]
        if not profile.tool.allow_dynamic_tools:
            allowed_names = [
                name
                for name in allowed_names
                if metadata[name].tool_family not in {"extension", "mcp"} or name in {"memory_search", "memory_get"}
            ]
    cloned = parent_registry.clone_selected(
        allowed_names,
        current_session_id=current_session_id,
        workspace_override=tool_workspace,
    )
    if profile is not None and hasattr(cloned, "set_capability_profile"):
        cloned.set_capability_profile(profile)
    return cloned


class SubAgentManager:
    """
    受控子 Agent 的生命周期管理器。

    SubAgentManager 不直接作为模型工具暴露；
    SpawnSubagentTool 会调用它来真正运行子 Agent。

    它负责：
    - 根据 spec_name 从 SubAgentCatalog 查找子 Agent 规格；
    - 校验子 Agent 的工具 allowlist、workspace mode 和输出格式；
    - 通过 SessionHost.fork_session(...) 从父会话分叉子会话；
    - 通过 runtime_factory 创建子 AgentRuntime；
    - 克隆父 ToolRegistry 的允许工具子集，形成受限工具面；
    - 设置子 Agent 的 system prompt、模型、审批策略和 capability profile；
    - 同步运行子 Agent，并限制 max_turns；
    - 解析子 Agent 的 summary 输出，生成 SubAgentRunResult；
    - 向父 Agent 发出 SUBAGENT_START / PROGRESS / END / FAIL 事件；
    - 统一处理取消、超轮数、空结果、格式错误和子 Runtime 异常。

    简单说：
    它把“父 Agent 的委托任务”转换成
    “一个独立子会话中的受限 AgentRuntime 执行”，
    并把最终摘要作为结构化结果返回。
    """
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
        event_sink: Optional[Callable[..., None]] = None,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.session_host = session_host
        self.parent_registry = parent_registry
        self.session_store = session_store
        self.runtime_factory = runtime_factory or self._default_runtime_factory()
        self.catalog = catalog or SubAgentCatalog(specs)
        self.event_sink = event_sink
        self.cancellation_token = cancellation_token

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
        tool_workspace: Path | None = None,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> SubAgentRunResult:
        started_at = self._now()
        token = cancellation_token or self.cancellation_token
        if token is not None and token.cancelled:
            return failure_result(
                spec_name=spec_name,
                session_id="",
                active_head_id=None,
                message=token.reason,
                failure_kind="canceled",
                started_at=started_at,
                finished_at=self._now(),
            )
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
        self._emit_parent_event(
            SUBAGENT_START,
            message=f"Subagent {spec.name} started.",
            details={
                "parent_session_id": parent_session_id,
                "spec_name": spec.name,
                "child_session_id": child_session_id,
                "session_id": child_session_id,
                "max_turns": spec.max_turns,
            },
        )
        try:
            if token is not None:
                token.raise_if_cancelled()
            child_record = self.session_store.load(child_session_id)
            profile = spec.resolved_profile()
            if tool_workspace is not None:
                profile.workspace.worktree_path = str(tool_workspace.resolve())
                profile.workspace.parent_workspace = str(self.workspace)
            child_runtime = self._create_child_runtime(child_record, profile)
            child = SubAgentRuntimeAdapter(child_runtime)
            if token is not None:
                child.set_cancellation_token(token)
            child.restore_session_record(child_record, emit_event=False)
            child.set_system_prompt(spec.system_prompt)
            child.set_require_plan_approval(spec.require_plan_approval)
            child.set_model_override(spec.model_override)
            child.set_tool_registry(
                build_subagent_tool_registry(
                    self.parent_registry,
                    self.workspace,
                    child_session_id,
                    profile.tool.allowlist or spec.tool_allowlist,
                    profile=profile,
                    tool_workspace=tool_workspace,
                )
            )
            child.apply_profile(profile)
            child.queue_lifecycle_event(
                SUBAGENT_START,
                details={
                    "parent_session_id": parent_session_id,
                    "spec_name": spec.name,
                    "max_turns": spec.max_turns,
                },
            )
            self._emit_parent_event(
                SUBAGENT_PROGRESS,
                message=f"Subagent {spec.name} is running.",
                details={
                    "parent_session_id": parent_session_id,
                    "spec_name": spec.name,
                    "child_session_id": child_session_id,
                    "session_id": child_session_id,
                    "status": "running",
                },
            )
            events = child.prompt(self._build_subagent_prompt(spec, task), max_turns=spec.max_turns)
            if token is not None:
                token.raise_if_cancelled()
            final_text = child.extract_final_text()
            tool_calls_used = self._tool_calls_used(events)
            active_head_id = child_runtime.session_store.load(child_session_id).active_head_id
            finished_at = self._now()
            if self._used_tool_result_fallback(events):
                message = "Subagent model returned an empty response after tool results, so no reliable summary was produced."
                child.emit_lifecycle_event(
                    SUBAGENT_FAIL,
                    message=message,
                    details={"spec_name": spec.name, "failure_kind": "invalid_summary"},
                    is_error=self._failure_event_is_error("invalid_summary"),
                )
                self._emit_parent_event(
                    SUBAGENT_FAIL,
                    message=message,
                    details={"spec_name": spec.name, "child_session_id": child_session_id, "session_id": child_session_id, "failure_kind": "invalid_summary", "parse_error": True},
                    is_error=self._failure_event_is_error("invalid_summary"),
                )
                return failure_result(
                    spec_name=spec.name,
                    session_id=child_session_id,
                    active_head_id=active_head_id,
                    message=message,
                    failure_kind="invalid_summary",
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
                self._emit_parent_event(
                    SUBAGENT_FAIL,
                    message=message,
                    details={"spec_name": spec.name, "child_session_id": child_session_id, "session_id": child_session_id, "failure_kind": "empty_result"},
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
            validation_error = self._validate_summary_text(final_text, parsed)
            if validation_error is not None:
                child.emit_lifecycle_event(
                    SUBAGENT_FAIL,
                    message=validation_error,
                    details={"spec_name": spec.name, "failure_kind": "invalid_summary"},
                    is_error=self._failure_event_is_error("invalid_summary"),
                )
                self._emit_parent_event(
                    SUBAGENT_FAIL,
                    message=validation_error,
                    details={"spec_name": spec.name, "child_session_id": child_session_id, "session_id": child_session_id, "failure_kind": "invalid_summary", "parse_error": True},
                    is_error=self._failure_event_is_error("invalid_summary"),
                )
                return failure_result(
                    spec_name=spec.name,
                    session_id=child_session_id,
                    active_head_id=active_head_id,
                    message=validation_error,
                    failure_kind="invalid_summary",
                    tool_calls_used=tool_calls_used,
                    event_count=len(events),
                    started_at=started_at,
                    finished_at=finished_at,
                )
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
            self._emit_parent_event(
                SUBAGENT_END,
                message=f"Subagent {spec.name} completed.",
                details={
                    "spec_name": spec.name,
                    "child_session_id": child_session_id,
                    "session_id": child_session_id,
                    "tool_calls_used": tool_calls_used,
                    "event_count": len(events),
                    "duration_ms": result.duration_ms,
                    "summary": result.summary,
                },
            )
            return result
        except OperationCancelled as exc:
            finished_at = self._now()
            message = str(exc) or "cancel_requested"
            self._emit_parent_event(
                SUBAGENT_FAIL,
                message=message,
                details={"spec_name": spec.name, "child_session_id": child_session_id, "session_id": child_session_id, "failure_kind": "canceled"},
                is_error=True,
            )
            return failure_result(
                spec_name=spec.name,
                session_id=child_session_id,
                active_head_id=child_head_id,
                message=message,
                failure_kind="canceled",
                started_at=started_at,
                finished_at=finished_at,
            )
        except SubAgentTurnLimitReached as exc:
            finished_at = self._now()
            self._emit_parent_event(
                SUBAGENT_FAIL,
                message=self._safe_error_message(exc),
                details={"spec_name": spec.name, "child_session_id": child_session_id, "session_id": child_session_id, "failure_kind": "turn_limit_reached"},
                is_error=True,
            )
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
            self._emit_parent_event(
                SUBAGENT_FAIL,
                message=message,
                details={"spec_name": spec.name, "child_session_id": child_session_id, "session_id": child_session_id, "failure_kind": "child_runtime_error"},
                is_error=True,
            )
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
            "Use plain section headings exactly as shown; do not use Markdown heading markers, code fences, or raw file dumps.\n"
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

    @staticmethod
    def _failure_event_is_error(failure_kind: str) -> bool:
        return failure_kind not in {"invalid_summary"}

    def _validate_spec(self, spec: SubAgentSpec) -> Optional[str]:
        metadata = self.parent_registry.metadata()
        profile = spec.resolved_profile()
        for name in profile.tool.allowlist or spec.tool_allowlist:
            if name in {"spawn_subagent", "orchestrate_agents"}:
                return f"Subagent '{spec.name}' cannot allow tool 'spawn_subagent'."
            if name not in metadata:
                return f"Subagent '{spec.name}' references unknown tool '{name}'."
            if profile.workspace.mode == "read_only" and name in {"write_file", "edit_file", "run_shell"}:
                return f"Subagent '{spec.name}' is read-only but allows write tool '{name}'."
        return None

    def _create_child_runtime(self, child_record, profile: SubAgentProfile):
        options = RuntimeCreationOptions.for_subagent(profile)
        try:
            return self.runtime_factory(self.workspace, child_record, None, options=options)
        except TypeError:
            return self.runtime_factory(self.workspace, child_record, None)

    @staticmethod
    def _validate_summary_text(final_text: str, parsed: dict[str, object]) -> Optional[str]:
        if len(final_text) > 2500:
            return "Subagent summary was too large and looked more like raw content than a concise summary."
        summary = str(parsed.get("summary") or "").strip()
        findings = [str(item).strip() for item in parsed.get("findings", []) if str(item).strip()]
        next_action = str(parsed.get("recommended_next_action") or "").strip()
        confidence = str(parsed.get("confidence") or "").strip()
        if not summary:
            return "Subagent summary did not include a usable summary section."
        if not findings:
            return "Subagent summary did not include any findings."
        if not next_action:
            return "Subagent summary did not include a recommended next action."
        if not confidence:
            return "Subagent summary did not include a confidence rating."
        return None

    def _emit_parent_event(
        self,
        event_type: str,
        *,
        message: Optional[str] = None,
        details: Optional[dict[str, object]] = None,
        is_error: bool = False,
    ) -> None:
        if self.event_sink is None:
            return
        self.event_sink(event_type, message=message, details=details or {}, is_error=is_error)

    @staticmethod
    def _now() -> float:
        import time

        return time.time()

    @staticmethod
    def _default_runtime_factory() -> RuntimeFactory:
        bootstrap = import_module("pp_agent.app.bootstrap")
        return bootstrap.create_runtime_from_record
