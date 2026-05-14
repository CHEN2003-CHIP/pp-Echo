from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pp_agent.app import bootstrap
from pp_agent.runtime import AgentEvent


RuntimeFactory = Callable[[Path, Optional[str], list[Callable[[AgentEvent], None]]], object]


@dataclass
class QueuedWebEvent:
    session_id: str
    event: AgentEvent


class WebSessionHandle:
    def __init__(
        self,
        workspace: Path,
        session_id: Optional[str],
        *,
        runtime_factory: RuntimeFactory,
    ) -> None:
        self.workspace = workspace
        self._event_queue: queue.Queue[QueuedWebEvent] = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._runtime_factory = runtime_factory
        self.agent = self._build_runtime(session_id)

    @property
    def session_id(self) -> str:
        return str(self.agent.session_id)

    def is_busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def snapshot(self) -> dict:
        return {
            "session_id": self.session_id,
            "busy": self.is_busy(),
            "cancel_requested": self.cancel_requested(),
            "pending_plan_token": self.agent.state.pending_plan_token,
            "pending_tool_call_count": len(self.agent.state.pending_tool_calls),
            "queued_message_count": len(self.agent.state.queued_messages),
            "turn": self.agent.state.turn.model_dump(mode="json"),
            "messages": [message.model_dump(mode="json") for message in self.agent.state.messages],
        }

    def drain_events(self) -> list[dict]:
        items: list[dict] = []
        while True:
            try:
                queued = self._event_queue.get_nowait()
            except queue.Empty:
                return items
            items.append(queued.event.model_dump(mode="json"))

    def prompt(self, text: str) -> dict:
        if not text.strip():
            raise ValueError("Prompt cannot be empty.")
        if self.agent.state.pending_plan_token:
            raise RuntimeError("Approval pending. Approve or reject before sending a new prompt.")
        if self.is_busy():
            item = self.agent.enqueue_message(text, delivery="follow_up")
            self._emit_local("queue_update", "Queued follow-up prompt.", {"queued_id": item.id, "delivery": item.delivery})
            return {"session_id": self.session_id, "queued": True, "queued_message_id": item.id}
        self._start_worker("prompt", lambda value=text: self.agent.prompt(value))
        return {"session_id": self.session_id, "queued": False}

    def continue_(self) -> dict:
        self._start_worker("continue", lambda: self.agent.continue_())
        return {"session_id": self.session_id}

    def approve(self) -> dict:
        token = self.agent.state.pending_plan_token
        if not token:
            raise RuntimeError("No pending approval.")
        self._start_worker("approve", lambda: self.agent.approve_pending_plan(token))
        return {"session_id": self.session_id, "token": token}

    def reject(self) -> dict:
        token = self.agent.state.pending_plan_token
        if not token:
            raise RuntimeError("No pending approval.")
        self.agent.reject_pending_plan(token)
        self._emit_local("planner_gate_rejected", f"Rejected planner gate {token}.", {"token": token})
        return {"session_id": self.session_id, "token": token}

    def cancel(self) -> dict:
        if not self.is_busy():
            return {"session_id": self.session_id, "cancel_requested": False, "busy": False}
        request_cancel = getattr(self.agent, "request_cancel", None)
        if callable(request_cancel):
            request_cancel("cancel_requested")
        self._emit_local(
            "cancel_requested",
            "Cancel requested for the running turn.",
            {"cancel_requested": True},
        )
        return {"session_id": self.session_id, "cancel_requested": True, "busy": self.is_busy()}

    def cancel_requested(self) -> bool:
        checker = getattr(self.agent, "cancellation_requested", None)
        return bool(callable(checker) and checker())

    def _build_runtime(self, session_id: Optional[str]):
        return self._runtime_factory(
            self.workspace,
            session_id,
            [lambda event: self._event_queue.put(QueuedWebEvent(session_id=self.session_id, event=event))],
        )

    def _emit_local(self, event_type: str, message: str, details: Optional[dict] = None) -> None:
        self._event_queue.put(
            QueuedWebEvent(
                session_id=self.session_id,
                event=AgentEvent(
                    type=event_type,
                    session_id=self.session_id,
                    message=message,
                    details=details or {},
                ),
            )
        )

    def _start_worker(self, action: str, fn) -> None:
        with self._lock:
            if self.is_busy():
                raise RuntimeError(f"Agent is busy; cannot start {action}.")

            def runner() -> None:
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001
                    self._event_queue.put(
                        QueuedWebEvent(
                            session_id=self.session_id,
                            event=AgentEvent(
                                type="error",
                                session_id=self.session_id,
                                message=str(exc),
                                details={"source": "web_session_manager", "action": action},
                                is_error=True,
                            ),
                        )
                    )

            self._worker = threading.Thread(target=runner, name=f"pp-agent-web-{action}", daemon=True)
            self._worker.start()


class WebSessionManager:
    def __init__(
        self,
        workspace: Path,
        *,
        runtime_factory: Optional[RuntimeFactory] = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self._runtime_factory = runtime_factory or self._default_runtime_factory
        self._handles: dict[str, WebSessionHandle] = {}
        self._lock = threading.Lock()

    def create_session(self) -> dict:
        handle = WebSessionHandle(self.workspace, None, runtime_factory=self._runtime_factory)
        with self._lock:
            self._handles[handle.session_id] = handle
        return handle.snapshot()

    def get_handle(self, session_id: str) -> WebSessionHandle:
        with self._lock:
            handle = self._handles.get(session_id)
        if handle is not None:
            return handle
        handle = WebSessionHandle(self.workspace, session_id, runtime_factory=self._runtime_factory)
        with self._lock:
            self._handles[handle.session_id] = handle
        return handle

    def list_active(self) -> list[dict]:
        with self._lock:
            handles = list(self._handles.values())
        return [handle.snapshot() for handle in handles]

    @staticmethod
    def _default_runtime_factory(workspace: Path, session_id: Optional[str], subscribers: list[Callable[[AgentEvent], None]]):
        return bootstrap.build_agent(workspace, session_id=session_id, lifecycle_subscribers=subscribers)
