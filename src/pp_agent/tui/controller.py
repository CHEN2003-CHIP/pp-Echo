from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pp_agent.app.bootstrap import build_agent
from pp_agent.runtime import AgentEvent


@dataclass
class QueuedRuntimeEvent:
    epoch: int
    event: AgentEvent


class TuiController:
    def __init__(self, workspace: Path, session_id: Optional[str] = None) -> None:
        self.workspace = workspace
        self._event_queue: queue.Queue[QueuedRuntimeEvent] = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._session_epoch = 0
        self.agent = self._build_runtime(session_id=session_id)

    @property
    def session_id(self) -> str:
        return self.agent.session_id

    @property
    def session_epoch(self) -> int:
        return self._session_epoch

    def is_busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def drain_events(self) -> list[AgentEvent]:
        items: list[AgentEvent] = []
        while True:
            try:
                queued = self._event_queue.get_nowait()
            except queue.Empty:
                return items
            if queued.epoch == self._session_epoch:
                items.append(queued.event)

    def submit(self, raw: str) -> Optional[str]:
        raw = raw.strip()
        if not raw:
            return None
        normalized = raw.lower()
        if normalized == "approve":
            self.approve()
            return None
        if normalized == "reject":
            self.reject()
            return None
        if self.agent.state.pending_plan_token and not raw.startswith("/"):
            self._emit_local("local_warning", "Approval pending. Type 'approve' or 'reject' to continue.")
            return None
        if raw.startswith("/"):
            return self._handle_command(raw)
        if self.is_busy():
            self.agent.enqueue_message(raw, delivery="follow_up")
            self._emit_local("local_info", "Busy now; queued your message as follow-up.")
            return None
        self._start_worker("prompt", lambda value=raw: self.agent.prompt(value))
        return None

    def new_session(self) -> None:
        if self.is_busy():
            raise RuntimeError("Wait for the current task to finish before creating a new session.")
        self._rebuild_runtime(session_id=None, note="Started a new session.")

    def resume_session(self, session_id: str) -> None:
        if self.is_busy():
            raise RuntimeError("Wait for the current task to finish before switching sessions.")
        self._rebuild_runtime(session_id=session_id, note=f"Resumed session {session_id}.")

    def approve(self) -> None:
        token = self.agent.state.pending_plan_token
        if not token:
            raise RuntimeError("No pending approval.")
        self._start_worker("approve", lambda: self.agent.approve_pending_plan(token))

    def reject(self) -> None:
        token = self.agent.state.pending_plan_token
        if not token:
            raise RuntimeError("No pending approval.")
        self.agent.reject_pending_plan(token)

    def _handle_command(self, raw: str) -> Optional[str]:
        if raw == "/approve":
            self.approve()
            return None
        if raw == "/reject":
            self.reject()
            return None
        if raw == "/new":
            self.new_session()
            return "new"
        if raw.startswith("/resume "):
            session_id = raw.split(" ", 1)[1].strip()
            if not session_id:
                raise RuntimeError("Usage: /resume <session_id>")
            self.resume_session(session_id)
            return "resume"
        raise RuntimeError("Supported commands: /approve, /reject, /new, /resume <session_id>")

    def _build_runtime(self, *, session_id: Optional[str]):
        agent = build_agent(self.workspace, session_id=session_id)
        current_epoch = self._session_epoch
        agent.subscribe(lambda event: self._event_queue.put(QueuedRuntimeEvent(epoch=current_epoch, event=event)))
        return agent

    def _rebuild_runtime(self, *, session_id: Optional[str], note: str) -> None:
        self._session_epoch += 1
        self._clear_event_queue()
        self.agent = self._build_runtime(session_id=session_id)
        self._emit_local("local_info", note)

    def _emit_local(self, event_type: str, message: str) -> None:
        self._event_queue.put(
            QueuedRuntimeEvent(
                epoch=self._session_epoch,
                event=AgentEvent(type=event_type, session_id=self.agent.session_id, message=message, details={}),
            )
        )

    def _clear_event_queue(self) -> None:
        while True:
            try:
                self._event_queue.get_nowait()
            except queue.Empty:
                return

    def _start_worker(self, action: str, fn) -> None:
        with self._lock:
            if self.is_busy():
                raise RuntimeError(f"Agent is busy; cannot start {action}.")

            def runner() -> None:
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001
                    self._event_queue.put(
                        QueuedRuntimeEvent(
                            epoch=self._session_epoch,
                            event=AgentEvent(
                                type="error",
                                session_id=self.agent.session_id,
                                message=str(exc),
                                details={},
                                is_error=True,
                            ),
                        )
                    )

            self._worker = threading.Thread(target=runner, name=f"pp-agent-tui-{action}", daemon=True)
            self._worker.start()
