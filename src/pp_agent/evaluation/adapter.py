from __future__ import annotations

from importlib import import_module
from pathlib import Path
import time
from typing import Any, Optional

from pp_agent.api import sdk
from pp_agent.evaluation.models import AgentTrace, EvalTask


class AgentAdapter:
    def start(self, task: EvalTask, workspace: Path) -> AgentTrace:
        raise NotImplementedError

    def send_message(self, trace: AgentTrace, text: str) -> AgentTrace:
        raise NotImplementedError

    def approve_pending(self, trace: AgentTrace, tool: str) -> AgentTrace:
        raise NotImplementedError

    def reject_pending(self, trace: AgentTrace, tool: str) -> AgentTrace:
        raise NotImplementedError


class ScriptedAgentAdapter(AgentAdapter):
    def __init__(self) -> None:
        self._task: Optional[EvalTask] = None
        self._workspace: Optional[Path] = None
        self._initial_files: dict[str, bytes] = {}

    def start(self, task: EvalTask, workspace: Path) -> AgentTrace:
        self._task = task
        self._workspace = workspace
        self._initial_files = {path.relative_to(workspace).as_posix(): path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
        return AgentTrace(task_id=task.id, mode="deterministic")

    def send_message(self, trace: AgentTrace, text: str) -> AgentTrace:
        task = self._require_task()
        workspace = self._require_workspace()
        trace.turns += 1
        trace.events.append({"type": "user_message", "text": text})
        task_id = _base_task_id(task.id)
        if task_id == "file_edit_basic":
            app = workspace / "app.py"
            app.write_text(app.read_text(encoding="utf-8").replace("return 0", "return a + b"), encoding="utf-8")
            _record_tools(trace, ["read_file", "edit_file"])
            trace.assistant_messages.append("Implemented add() in app.py.")
        elif task_id == "tool_selection":
            _record_tools(trace, ["read_file", "grep_code"])
            trace.assistant_messages.append("add() is implemented in app.py.")
        elif task_id == "protected_path":
            _record_tools(trace, ["read_file"])
            trace.events.append({"type": "protected_path_blocked", "path": ".env"})
            trace.assistant_messages.append("I inspected README.md and avoided .env.")
        elif task_id == "approval_required":
            trace.pending_actions.append("write_file")
            trace.events.append({"type": "approval_required", "tool_name": "write_file"})
            trace.assistant_messages.append("Creating approved.txt requires approval.")
        elif task_id == "checkpoint_rewind":
            _record_tools(trace, ["create_checkpoint"])
            trace.pending_actions.extend(["edit_file", "execute_safe_rewind"])
            trace.events.append({"type": "approval_required", "tool_name": "edit_file"})
            trace.events.append({"type": "approval_required", "tool_name": "execute_safe_rewind"})
            trace.assistant_messages.append("Checkpoint created; edit and rewind require approval.")
        elif task_id == "memory_recall":
            _record_tools(trace, ["memory_search"])
            trace.events.append({"type": "memory_recall", "source": "MEMORY.md"})
            trace.assistant_messages.append("Use small explicit functions in code examples.")
        elif task_id == "subagent_limited_tools":
            _record_tools(trace, ["spawn_subagent", "read_file"])
            trace.assistant_messages.append("The limited subagent inspected app.py without editing files.")
        else:
            trace.assistant_messages.append("No scripted behavior exists for this task.")
            trace.events.append({"type": "adapter_unknown_task", "task_id": task.id})
        return trace

    def approve_pending(self, trace: AgentTrace, tool: str) -> AgentTrace:
        task = self._require_task()
        workspace = self._require_workspace()
        if tool not in trace.pending_actions:
            trace.events.append({"type": "approval_missing", "tool_name": tool})
            return trace
        trace.pending_actions.remove(tool)
        trace.approvals.append(tool)
        trace.events.append({"type": "approval_granted", "tool_name": tool})
        task_id = _base_task_id(task.id)
        if task_id == "approval_required" and tool == "write_file":
            (workspace / "approved.txt").write_text("Approved write from tau-style eval.\n", encoding="utf-8")
            _record_tools(trace, ["write_file"])
            trace.assistant_messages.append("approved.txt was created after approval.")
        elif task_id == "checkpoint_rewind" and tool == "edit_file":
            app = workspace / "app.py"
            app.write_text(app.read_text(encoding="utf-8").replace("return 0", "return a + b"), encoding="utf-8")
            _record_tools(trace, ["edit_file"])
            trace.assistant_messages.append("A temporary bad edit was applied.")
        elif task_id == "checkpoint_rewind" and tool == "execute_safe_rewind":
            app = workspace / "app.py"
            original = self._initial_files.get("app.py")
            if original is not None:
                app.write_bytes(original)
            trace.checkpoint_rewind_restored = True
            _record_tools(trace, ["execute_safe_rewind"])
            trace.assistant_messages.append("The workspace was rewound to the checkpoint.")
        return trace

    def reject_pending(self, trace: AgentTrace, tool: str) -> AgentTrace:
        if tool in trace.pending_actions:
            trace.pending_actions.remove(tool)
        trace.rejected_approvals.append(tool)
        trace.events.append({"type": "approval_rejected", "tool_name": tool})
        trace.assistant_messages.append(f"Rejected pending {tool}.")
        return trace

    def _require_task(self) -> EvalTask:
        if self._task is None:
            raise RuntimeError("Adapter was not started.")
        return self._task

    def _require_workspace(self) -> Path:
        if self._workspace is None:
            raise RuntimeError("Adapter was not started.")
        return self._workspace


class SdkAgentAdapter(AgentAdapter):
    def __init__(self, *, timeout_seconds: int = 120) -> None:
        self.timeout_seconds = timeout_seconds
        self._workspace: Optional[Path] = None

    def start(self, task: EvalTask, workspace: Path) -> AgentTrace:
        self._workspace = workspace
        return AgentTrace(task_id=task.id, mode="live")

    def send_message(self, trace: AgentTrace, text: str) -> AgentTrace:
        workspace = self._require_workspace()
        started = time.perf_counter()
        try:
            payload = sdk.run(text, workspace, session_id=trace.session_id or None, collect_events=True)
        except Exception as exc:  # noqa: BLE001
            trace.infra_failed = True
            trace.failure_kind = "sdk_exception"
            trace.events.append({"type": "adapter_error", "message": str(exc)})
            return trace
        trace.duration_seconds += time.perf_counter() - started
        trace.turns += 1
        trace.session_id = str(payload.get("session_id") or trace.session_id)
        assistant = str(payload.get("assistant") or "")
        if assistant:
            trace.assistant_messages.append(assistant)
        _merge_payload(trace, payload)
        if payload.get("pending_plan_token"):
            trace.pending_actions.append(str(payload["pending_plan_token"]))
        return trace

    def approve_pending(self, trace: AgentTrace, tool: str) -> AgentTrace:
        return self._approval(trace, tool, approve=True)

    def reject_pending(self, trace: AgentTrace, tool: str) -> AgentTrace:
        return self._approval(trace, tool, approve=False)

    def _approval(self, trace: AgentTrace, tool: str, *, approve: bool) -> AgentTrace:
        workspace = self._require_workspace()
        token = trace.pending_actions.pop(0) if trace.pending_actions else ""
        if not token:
            trace.events.append({"type": "approval_missing", "tool_name": tool})
            return trace
        try:
            approvals = import_module("pp_agent.cli.commands.approvals")
            result = (
                approvals.approve_or_execute_pending_action(workspace, token, render=False)
                if approve
                else approvals.reject_pending_action(workspace, token, render=False)
            )
        except Exception as exc:  # noqa: BLE001
            trace.infra_failed = True
            trace.failure_kind = "approval_exception"
            trace.events.append({"type": "adapter_error", "message": str(exc), "tool_name": tool})
            return trace
        target = trace.approvals if approve else trace.rejected_approvals
        target.append(tool)
        trace.events.append({"type": "approval_granted" if approve else "approval_rejected", "tool_name": tool, "result": result})
        return trace

    def _require_workspace(self) -> Path:
        if self._workspace is None:
            raise RuntimeError("Adapter was not started.")
        return self._workspace


def _record_tools(trace: AgentTrace, names: list[str]) -> None:
    for name in names:
        trace.tool_calls.append(name)
        trace.tool_results.append(True)
        trace.events.append({"type": "tool_call", "tool_name": name})
        trace.events.append({"type": "tool_result", "tool_name": name, "is_error": False})


def _base_task_id(task_id: str) -> str:
    return task_id.split("__", 1)[0]


def _merge_payload(trace: AgentTrace, payload: dict[str, Any]) -> None:
    for event in payload.get("events", []) or []:
        if not isinstance(event, dict):
            continue
        trace.events.append(event)
        event_type = str(event.get("type") or "")
        tool_name = str(event.get("tool_name") or event.get("name") or "")
        if event_type in {"tool_call", "tool_start"} and tool_name:
            trace.tool_calls.append(tool_name)
        if event_type in {"tool_result", "tool_end"}:
            trace.tool_results.append(not bool(event.get("is_error", False)))
        if event_type == "tool_error":
            trace.tool_results.append(False)
        if event_type in {"planner_gate_pending", "approval_required"} and tool_name:
            trace.pending_actions.append(tool_name)
