from __future__ import annotations

import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, TimeoutError, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Protocol

from pp_agent.runtime.cancellation import CancellationToken, OperationCancelled
from pp_agent.runtime.lifecycle import SUBAGENT_PROGRESS
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.subagents.catalog import SubAgentCatalog
from pp_agent.subagents.manager import SubAgentManager
from pp_agent.subagents.specs import SubAgentRunResult, SubAgentSpec


WorkflowName = str


@dataclass(frozen=True)
class OrchestrationStep:
    agent: str
    task: str
    status: str
    session_id: str = ""
    summary: str = ""
    findings: list[str] = field(default_factory=list)
    inspected_paths: list[str] = field(default_factory=list)
    staged_actions: list[dict[str, str]] = field(default_factory=list)
    confidence: str = "low"
    duration_ms: int | None = None
    error_message: str | None = None
    failure_kind: str | None = None
    parse_error: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "agent": self.agent,
            "task": self.task,
            "status": self.status,
            "session_id": self.session_id,
            "summary": self.summary,
            "findings": list(self.findings),
            "inspected_paths": list(self.inspected_paths),
            "staged_actions": list(self.staged_actions),
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "failure_kind": self.failure_kind,
            "parse_error": self.parse_error,
        }


@dataclass(frozen=True)
class SubAgentOrchestrationResult:
    run_id: str
    goal: str
    workflow: str
    success: bool
    partial_success: bool
    parallel: bool
    steps: list[OrchestrationStep]
    final_summary: str
    recommended_next_action: str
    duration_ms: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "workflow": self.workflow,
            "success": self.success,
            "partial_success": self.partial_success,
            "parallel": self.parallel,
            "steps": [step.to_dict() for step in self.steps],
            "final_summary": self.final_summary,
            "recommended_next_action": self.recommended_next_action,
            "duration_ms": self.duration_ms,
            "warnings": list(self.warnings),
        }


class RunsSubagents(Protocol):
    def run_sync(
        self,
        *,
        parent_session_id: str,
        parent_head_id: Optional[str],
        spec_name: str,
        task: str,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> SubAgentRunResult:
        ...


ManagerFactory = Callable[[dict[str, SubAgentSpec]], RunsSubagents]


class SubAgentOrchestrator:
    def __init__(
        self,
        *,
        workspace: Path,
        manager_factory: ManagerFactory,
        parent_session_id: str,
        parent_head_id: Optional[str],
        pending_store: PendingActionStore | None = None,
        event_sink: Optional[Callable[..., None]] = None,
        cancellation_token: Optional[CancellationToken] = None,
        specs: Optional[dict[str, SubAgentSpec]] = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.manager_factory = manager_factory
        self.parent_session_id = parent_session_id
        self.parent_head_id = parent_head_id
        self.pending_store = pending_store or PendingActionStore(self.workspace / ".pp-agent" / "pending-edits")
        self.event_sink = event_sink
        self.cancellation_token = cancellation_token
        self.specs = specs

    def run(
        self,
        *,
        goal: str,
        workflow: str = "auto",
        max_agents: int = 4,
        allow_edits: bool = False,
        run_timeout_seconds: int = 900,
    ) -> SubAgentOrchestrationResult:
        started = time.time()
        run_id = uuid.uuid4().hex[:12]
        resolved_workflow = resolve_workflow(goal, workflow)
        specs = orchestration_specs(allow_edits=allow_edits, base_specs=self.specs)
        manager = self.manager_factory(specs)
        warnings: list[str] = []
        steps: list[OrchestrationStep] = []
        agent_budget = max(1, min(int(max_agents or 1), 8))
        timeout = max(1, int(run_timeout_seconds or 1))
        self._emit_progress(
            run_id=run_id,
            status="started",
            completed=0,
            total=0,
            started_at=started,
            details={"goal": goal, "workflow": resolved_workflow},
        )

        if resolved_workflow == "code_change":
            research_agents = workflow_agents("code_change_research")[:agent_budget]
            research_steps = self._run_parallel(
                manager=manager,
                agents=research_agents,
                goal=goal,
                timeout_seconds=timeout,
                run_id=run_id,
                run_started_at=started,
            )
            steps.extend(research_steps)
            remaining = max(agent_budget - len(research_steps), 0)
            if remaining:
                planner = self._run_one(
                    manager=manager,
                    agent="implementation-planner",
                    task=build_task("implementation-planner", goal, prior_steps=steps, allow_edits=allow_edits),
                    timeout_seconds=timeout,
                    run_id=run_id,
                    run_started_at=started,
                )
                steps.append(planner)
                remaining -= 1
            if allow_edits and remaining:
                before_tokens = self._pending_tokens()
                worker = self._run_one(
                    manager=manager,
                    agent="code-worker",
                    task=build_task("code-worker", goal, prior_steps=steps, allow_edits=True),
                    timeout_seconds=timeout,
                    run_id=run_id,
                    run_started_at=started,
                )
                worker = self._with_staged_actions(worker, before_tokens)
                steps.append(worker)
                remaining -= 1
            elif not allow_edits:
                warnings.append("allow_edits=false; code-worker did not receive edit tools.")
            if remaining:
                reviewer = self._run_one(
                    manager=manager,
                    agent="change-reviewer",
                    task=build_task("change-reviewer", goal, prior_steps=steps, allow_edits=allow_edits),
                    timeout_seconds=timeout,
                    run_id=run_id,
                    run_started_at=started,
                )
                steps.append(reviewer)
        else:
            agents = workflow_agents(resolved_workflow)[:agent_budget]
            steps.extend(
                self._run_parallel(
                    manager=manager,
                    agents=agents,
                    goal=goal,
                    timeout_seconds=timeout,
                    run_id=run_id,
                    run_started_at=started,
                )
            )

        success_count = sum(1 for step in steps if step.status == "success")
        failed_count = sum(1 for step in steps if step.status != "success")
        final_summary = synthesize_summary(goal, steps)
        next_action = recommended_next_action(steps, allow_edits=allow_edits)
        finished = time.time()
        final_status = "canceled" if self._cancel_requested() else "completed"
        self._emit_progress(
            run_id=run_id,
            status=final_status,
            completed=len(steps),
            total=len(steps),
            started_at=started,
            details={"success": bool(steps) and failed_count == 0, "partial_success": success_count > 0 and failed_count > 0},
        )
        return SubAgentOrchestrationResult(
            run_id=run_id,
            goal=goal,
            workflow=resolved_workflow,
            success=bool(steps) and failed_count == 0,
            partial_success=success_count > 0 and failed_count > 0,
            parallel=resolved_workflow != "code_change" or len([step for step in steps if step.agent in workflow_agents("code_change_research")]) > 1,
            steps=steps,
            final_summary=final_summary,
            recommended_next_action=next_action,
            duration_ms=max(int((finished - started) * 1000), 0),
            warnings=warnings,
        )

    def _run_parallel(
        self,
        *,
        manager: RunsSubagents,
        agents: list[str],
        goal: str,
        timeout_seconds: int,
        run_id: str,
        run_started_at: float,
    ) -> list[OrchestrationStep]:
        if not agents:
            return []
        executor = ThreadPoolExecutor(max_workers=len(agents))
        future_map = {
            executor.submit(
                self._run_sync_step,
                manager,
                agent,
                build_task(agent, goal, prior_steps=[], allow_edits=False),
            ): agent
            for agent in agents
        }
        steps: list[OrchestrationStep] = []
        pending = set(future_map)
        deadline = time.time() + timeout_seconds
        last_progress = 0.0
        try:
            while pending:
                if self._cancel_requested():
                    for future in pending:
                        future.cancel()
                        agent = future_map[future]
                        steps.append(
                            OrchestrationStep(
                                agent=agent,
                                task="",
                                status="canceled",
                                error_message=self._cancel_reason(),
                                failure_kind="canceled",
                            )
                        )
                    self._emit_progress(
                        run_id=run_id,
                        status="canceled",
                        completed=len(steps),
                        total=len(agents),
                        started_at=run_started_at,
                    )
                    break
                remaining = deadline - time.time()
                if remaining <= 0:
                    for future in pending:
                        agent = future_map[future]
                        future.cancel()
                        steps.append(
                            OrchestrationStep(
                                agent=agent,
                                task="",
                                status="timeout",
                                error_message="Subagent timed out.",
                                failure_kind="timeout",
                            )
                        )
                    self._emit_progress(
                        run_id=run_id,
                        status="timeout",
                        completed=len(steps),
                        total=len(agents),
                        started_at=run_started_at,
                    )
                    break
                done, pending = wait(pending, timeout=min(0.5, remaining), return_when=FIRST_COMPLETED)
                for future in done:
                    agent = future_map[future]
                    try:
                        steps.append(future.result())
                    except OperationCancelled as exc:
                        steps.append(
                            OrchestrationStep(
                                agent=agent,
                                task="",
                                status="canceled",
                                error_message=str(exc) or "cancel_requested",
                                failure_kind="canceled",
                            )
                        )
                    except Exception as exc:  # noqa: BLE001
                        steps.append(
                            OrchestrationStep(
                                agent=agent,
                                task="",
                                status="failed",
                                error_message=str(exc),
                                failure_kind="child_runtime_error",
                            )
                        )
                    self._emit_progress(
                        run_id=run_id,
                        status="running",
                        completed=len(steps),
                        total=len(agents),
                        started_at=run_started_at,
                        details={"last_completed_agent": agent},
                    )
                now = time.time()
                if pending and now - last_progress >= 5:
                    last_progress = now
                    self._emit_progress(
                        run_id=run_id,
                        status="running",
                        completed=len(steps),
                        total=len(agents),
                        started_at=run_started_at,
                        details={"running_agents": [future_map[future] for future in pending]},
                    )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        order = {agent: index for index, agent in enumerate(agents)}
        return sorted(steps, key=lambda step: order.get(step.agent, 999))

    def _run_one(
        self,
        *,
        manager: RunsSubagents,
        agent: str,
        task: str,
        timeout_seconds: int,
        run_id: str,
        run_started_at: float,
    ) -> OrchestrationStep:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._run_sync_step, manager, agent, task)
        deadline = time.time() + timeout_seconds
        last_progress = 0.0
        try:
            while True:
                if self._cancel_requested():
                    future.cancel()
                    self._emit_progress(
                        run_id=run_id,
                        status="canceled",
                        completed=0,
                        total=1,
                        started_at=run_started_at,
                        details={"running_agents": [agent]},
                    )
                    return OrchestrationStep(
                        agent=agent,
                        task=task,
                        status="canceled",
                        error_message=self._cancel_reason(),
                        failure_kind="canceled",
                    )
                remaining = deadline - time.time()
                if remaining <= 0:
                    future.cancel()
                    return OrchestrationStep(
                        agent=agent,
                        task=task,
                        status="timeout",
                        error_message="Subagent timed out.",
                        failure_kind="timeout",
                    )
                done, _pending = wait({future}, timeout=min(0.5, remaining), return_when=FIRST_COMPLETED)
                if done:
                    return future.result()
                now = time.time()
                if now - last_progress >= 5:
                    last_progress = now
                    self._emit_progress(
                        run_id=run_id,
                        status="running",
                        completed=0,
                        total=1,
                        started_at=run_started_at,
                        details={"running_agents": [agent]},
                    )
        except OperationCancelled as exc:
            return OrchestrationStep(
                agent=agent,
                task=task,
                status="canceled",
                error_message=str(exc) or "cancel_requested",
                failure_kind="canceled",
            )
        except TimeoutError:
            future.cancel()
            return OrchestrationStep(
                agent=agent,
                task=task,
                status="timeout",
                error_message="Subagent timed out.",
                failure_kind="timeout",
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _run_sync_step(self, manager: RunsSubagents, agent: str, task: str) -> OrchestrationStep:
        result = manager.run_sync(
            parent_session_id=self.parent_session_id,
            parent_head_id=self.parent_head_id,
            spec_name=agent,
            task=task,
            cancellation_token=self.cancellation_token,
        )
        return step_from_result(task=task, result=result)

    def _cancel_requested(self) -> bool:
        return bool(self.cancellation_token is not None and self.cancellation_token.cancelled)

    def _cancel_reason(self) -> str:
        if self.cancellation_token is None:
            return "cancel_requested"
        return self.cancellation_token.reason

    def _emit_progress(
        self,
        *,
        run_id: str,
        status: str,
        completed: int,
        total: int,
        started_at: float,
        details: Optional[dict[str, object]] = None,
    ) -> None:
        if self.event_sink is None:
            return
        payload = {
            "run_id": run_id,
            "status": status,
            "completed": completed,
            "total": total,
            "elapsed_ms": max(int((time.time() - started_at) * 1000), 0),
            **(details or {}),
        }
        self.event_sink(
            SUBAGENT_PROGRESS,
            message=f"Subagent orchestration {status}: {completed}/{total}",
            details=payload,
            is_error=status in {"canceled", "timeout"},
        )

    def _pending_tokens(self) -> set[str]:
        return {str(item.get("token")) for item in self.pending_store.list() if item.get("token")}

    def _with_staged_actions(self, step: OrchestrationStep, before_tokens: set[str]) -> OrchestrationStep:
        actions: list[dict[str, str]] = []
        for item in self.pending_store.list():
            token = str(item.get("token") or "")
            if not token or token in before_tokens:
                continue
            action_type = str(item.get("action_type") or "")
            if action_type not in {"write_file", "edit_file"}:
                continue
            actions.append(
                {
                    "token": token,
                    "path": str(item.get("target_path") or ""),
                    "action_type": action_type,
                }
            )
        return OrchestrationStep(
            agent=step.agent,
            task=step.task,
            status=step.status,
            session_id=step.session_id,
            summary=step.summary,
            findings=step.findings,
            inspected_paths=step.inspected_paths,
            staged_actions=actions,
            confidence=step.confidence,
            duration_ms=step.duration_ms,
            error_message=step.error_message,
            failure_kind=step.failure_kind,
            parse_error=step.parse_error,
        )


def step_from_result(*, task: str, result: SubAgentRunResult) -> OrchestrationStep:
    return OrchestrationStep(
        agent=result.spec_name,
        task=task,
        status="success" if result.success else "failed",
        session_id=result.session_id,
        summary=result.summary,
        findings=list(result.findings),
        inspected_paths=list(result.inspected_paths),
        staged_actions=[],
        confidence=result.confidence,
        duration_ms=result.duration_ms,
        error_message=result.error_message,
        failure_kind=result.failure_kind,
        parse_error=result.failure_kind == "invalid_summary",
    )


def resolve_workflow(goal: str, workflow: str) -> str:
    requested = (workflow or "auto").strip().lower()
    if requested in {"research", "debug", "code_change"}:
        return requested
    text = goal.lower()
    if any(marker in text for marker in ("fix", "implement", "change", "edit", "修改", "实现", "修复")):
        return "code_change"
    if any(marker in text for marker in ("test", "pytest", "fail", "error", "bug", "失败", "错误")):
        return "debug"
    return "research"


def workflow_agents(workflow: str) -> list[str]:
    if workflow == "debug":
        return ["memory-scout", "test-investigator", "change-reviewer"]
    if workflow == "code_change_research":
        return ["memory-scout", "repo-researcher", "api-scout"]
    if workflow == "code_change":
        return ["memory-scout", "repo-researcher", "api-scout", "implementation-planner"]
    return ["memory-scout", "repo-researcher", "api-scout"]


def orchestration_specs(
    *,
    allow_edits: bool,
    base_specs: Optional[dict[str, SubAgentSpec]] = None,
) -> dict[str, SubAgentSpec]:
    source = base_specs or {spec.name: spec for spec in SubAgentCatalog().list()}
    copied = {name: spec.model_copy(deep=True) for name, spec in source.items()}
    if allow_edits and "code-worker" in copied:
        copied["code-worker"].tool_allowlist = [
            "read_file",
            "list_files",
            "grep_code",
            "search_text",
            "edit_file",
            "write_file",
            "git_diff_worktree",
        ]
    return copied


def build_task(agent: str, goal: str, *, prior_steps: list[OrchestrationStep], allow_edits: bool) -> str:
    prior = ""
    if prior_steps:
        lines = []
        for step in prior_steps:
            summary = step.summary or step.error_message or step.status
            lines.append(f"- {step.agent} ({step.status}): {summary}")
        prior = "Prior subagent announces:\n" + "\n".join(lines) + "\n\n"
    if agent == "code-worker":
        edit_instruction = (
            "Edits are allowed. Stage changes only with edit_file/write_file and report pending action tokens."
            if allow_edits
            else "Edits are not allowed. Produce an implementation note only."
        )
        return (
            f"{prior}Goal:\n{goal}\n\n"
            "write_scope: choose the smallest relevant files from the prior plan; do not touch unrelated paths.\n"
            f"{edit_instruction}\n"
            "Return concise summary output with findings, inspected paths, confidence, and any staged tokens."
        )
    return (
        f"{prior}Goal:\n{goal}\n\n"
        f"Role: {agent}. Work independently in your own subagent session. "
        "Return concise announce-style summary only."
    )


def synthesize_summary(goal: str, steps: list[OrchestrationStep]) -> str:
    if not steps:
        return f"No subagents ran for: {goal}"
    successful = [step for step in steps if step.status == "success"]
    failed = [step for step in steps if step.status != "success"]
    parts = [f"Ran {len(steps)} subagent step(s) for: {goal}."]
    if successful:
        parts.append("Key findings: " + " | ".join((step.summary or step.agent) for step in successful[:3]))
    if failed:
        parts.append("Failures: " + " | ".join(f"{step.agent}:{step.status}" for step in failed[:3]))
    return " ".join(parts)


def recommended_next_action(steps: list[OrchestrationStep], *, allow_edits: bool) -> str:
    staged = [action for step in steps for action in step.staged_actions]
    if staged:
        return "Review staged edits with preview_pending_action, then approve selected tokens if they look correct."
    if steps and all(step.status != "success" for step in steps):
        return "Subagents did not produce reliable summaries. Use grep_code or list_files to locate real files, then read_file the confirmed paths before retrying orchestration."
    if allow_edits:
        return "Review the subagent findings; no staged edits were produced."
    return "Review the subagent findings and decide whether to run again with allow_edits=true for staged changes."


def default_manager_factory(
    *,
    workspace: Path,
    session_host,
    parent_registry,
    session_store,
    runtime_factory=None,
    event_sink: Optional[Callable[..., None]] = None,
    cancellation_token: Optional[CancellationToken] = None,
) -> ManagerFactory:
    def _factory(specs: dict[str, SubAgentSpec]) -> SubAgentManager:
        return SubAgentManager(
            workspace=workspace,
            session_host=session_host,
            parent_registry=parent_registry,
            session_store=session_store,
            runtime_factory=runtime_factory,
            specs=specs,
            event_sink=event_sink,
            cancellation_token=cancellation_token,
        )

    return _factory


__all__ = [
    "OrchestrationStep",
    "SubAgentOrchestrationResult",
    "SubAgentOrchestrator",
    "build_task",
    "default_manager_factory",
    "orchestration_specs",
    "resolve_workflow",
    "workflow_agents",
]
