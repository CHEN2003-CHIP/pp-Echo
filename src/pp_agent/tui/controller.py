from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Optional

from pp_agent.app.bootstrap import build_agent
from pp_agent.runtime import AgentEvent


class TuiController:
    def __init__(self, workspace: Path, session_id: Optional[str] = None) -> None:
        self.workspace = workspace
        self._event_queue: queue.Queue[AgentEvent] = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.agent = self._build_runtime(session_id=session_id)

    @property
    def session_id(self) -> str:
        return self.agent.session_id

    def is_busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def drain_events(self) -> list[AgentEvent]:
        items: list[AgentEvent] = []
        while True:
            try:
                items.append(self._event_queue.get_nowait())
            except queue.Empty:
                return items

    def submit(self, raw: str) -> Optional[str]:
        raw = raw.strip()
        if not raw:
            return None
        if raw.startswith("/"):
            return self._handle_command(raw)
        if self.is_busy():
            self.agent.enqueue_message(raw, delivery="follow_up")
            return None
        self._start_worker("prompt", lambda value=raw: self.agent.prompt(value))
        return None

    def new_session(self) -> None:
        if self.is_busy():
            raise RuntimeError("Wait for the current task to finish before creating a new session.")
        self.agent = self._build_runtime(session_id=None)

    def resume_session(self, session_id: str) -> None:
        if self.is_busy():
            raise RuntimeError("Wait for the current task to finish before switching sessions.")
        self.agent = self._build_runtime(session_id=session_id)

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
        agent.subscribe(self._event_queue.put)
        return agent

    def _start_worker(self, action: str, fn) -> None:
        with self._lock:
            if self.is_busy():
                raise RuntimeError(f"Agent is busy; cannot start {action}.")

            def runner() -> None:
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001
                    self._event_queue.put(
                        AgentEvent(
                            type="error",
                            session_id=self.agent.session_id,
                            message=str(exc),
                            details={},
                            is_error=True,
                        )
                    )

            self._worker = threading.Thread(target=runner, name=f"pp-agent-tui-{action}", daemon=True)
            self._worker.start()
