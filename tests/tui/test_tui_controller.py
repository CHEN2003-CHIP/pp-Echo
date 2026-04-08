from __future__ import annotations

from pathlib import Path

from pp_agent.runtime import AgentEvent
from pp_agent.tui.controller import TuiController


class FakeState:
    def __init__(self) -> None:
        self.pending_plan_token = None
        self.pending_tool_calls = []
        self.queued_messages = []
        self.turn = type("Turn", (), {"turn_id": 0, "phase": "idle", "reason": ""})()
        self.is_streaming = False


class FakeRuntime:
    counter = 0
    instances: list["FakeRuntime"] = []

    def __init__(self) -> None:
        FakeRuntime.counter += 1
        self.session_id = f"session-{FakeRuntime.counter}"
        self.state = FakeState()
        self.subscriber = None
        self.enqueued: list[tuple[str, str]] = []
        self.prompted: list[str] = []
        self.approved: list[str] = []
        self.rejected: list[str] = []
        FakeRuntime.instances.append(self)

    def subscribe(self, callback) -> None:
        self.subscriber = callback

    def prompt(self, text: str):
        self.prompted.append(text)
        if self.subscriber is not None:
            self.subscriber(AgentEvent(type="message_delta", session_id=self.session_id, delta=text, details={}))
        return []

    def enqueue_message(self, text: str, delivery: str = "follow_up") -> None:
        self.enqueued.append((text, delivery))

    def approve_pending_plan(self, token: str):
        self.approved.append(token)
        self.state.pending_plan_token = None
        return []

    def reject_pending_plan(self, token: str) -> None:
        self.rejected.append(token)
        self.state.pending_plan_token = None



def test_controller_submits_prompt_and_drains_events(monkeypatch, tmp_path: Path) -> None:
    FakeRuntime.instances = []
    monkeypatch.setattr("pp_agent.tui.controller.build_agent", lambda workspace, session_id=None: FakeRuntime())

    controller = TuiController(tmp_path)
    controller.submit("hello")
    if controller._worker is not None:
        controller._worker.join(timeout=2)
    events = controller.drain_events()

    assert events
    assert events[0].delta == "hello"



def test_controller_supports_new_and_resume(monkeypatch, tmp_path: Path) -> None:
    FakeRuntime.instances = []
    monkeypatch.setattr("pp_agent.tui.controller.build_agent", lambda workspace, session_id=None: FakeRuntime())

    controller = TuiController(tmp_path)
    first_session = controller.session_id
    first_epoch = controller.session_epoch
    controller.submit("/new")
    assert controller.session_id != first_session
    assert controller.session_epoch == first_epoch + 1

    controller.submit("/resume custom-session")
    assert controller.session_epoch == first_epoch + 2



def test_controller_ignores_late_events_from_old_session(monkeypatch, tmp_path: Path) -> None:
    FakeRuntime.instances = []
    monkeypatch.setattr("pp_agent.tui.controller.build_agent", lambda workspace, session_id=None: FakeRuntime())

    controller = TuiController(tmp_path)
    old_runtime = controller.agent
    controller.submit("/new")
    old_runtime.subscriber(AgentEvent(type="message_delta", session_id=old_runtime.session_id, delta="stale", details={}))

    drained = controller.drain_events()
    assert all(event.delta != "stale" for event in drained)



def test_controller_queues_follow_up_when_busy(monkeypatch, tmp_path: Path) -> None:
    FakeRuntime.instances = []
    monkeypatch.setattr("pp_agent.tui.controller.build_agent", lambda workspace, session_id=None: FakeRuntime())

    controller = TuiController(tmp_path)
    controller._worker = type("Worker", (), {"is_alive": lambda self: True})()
    controller.submit("later")

    assert controller.agent.enqueued == [("later", "follow_up")]
    drained = controller.drain_events()
    assert any(event.type == "local_info" for event in drained)



def test_controller_accepts_plain_approve_and_reject(monkeypatch, tmp_path: Path) -> None:
    FakeRuntime.instances = []
    monkeypatch.setattr("pp_agent.tui.controller.build_agent", lambda workspace, session_id=None: FakeRuntime())

    controller = TuiController(tmp_path)
    controller.agent.state.pending_plan_token = "tok-1"
    controller.submit("approve")
    if controller._worker is not None:
        controller._worker.join(timeout=2)
    assert controller.agent.approved == ["tok-1"]

    controller.agent.state.pending_plan_token = "tok-2"
    controller.submit("reject")
    assert controller.agent.rejected == ["tok-2"]



def test_controller_blocks_free_text_while_approval_pending(monkeypatch, tmp_path: Path) -> None:
    FakeRuntime.instances = []
    monkeypatch.setattr("pp_agent.tui.controller.build_agent", lambda workspace, session_id=None: FakeRuntime())

    controller = TuiController(tmp_path)
    controller.agent.state.pending_plan_token = "tok-1"
    controller.submit("tell me more")

    assert controller.agent.prompted == []
    drained = controller.drain_events()
    assert any(event.type == "local_warning" for event in drained)


def test_controller_loads_pending_plan_preview_details(monkeypatch, tmp_path: Path) -> None:
    FakeRuntime.instances = []
    monkeypatch.setattr("pp_agent.tui.controller.build_agent", lambda workspace, session_id=None: FakeRuntime())

    class FakeStore:
        def load(self, token: str) -> dict:
            assert token == "tok-1"
            return {
                "action_type": "planner_approval",
                "details": {"summary": ["Edit README.md [edit_file]"], "files_touched_guess": ["README.md"]},
            }

    monkeypatch.setattr("pp_agent.tui.controller.pending_action_store_for", lambda workspace: FakeStore())

    controller = TuiController(tmp_path)
    controller.agent.state.pending_plan_token = "tok-1"

    assert controller.pending_plan_preview_details() == {
        "summary": ["Edit README.md [edit_file]"],
        "files_touched_guess": ["README.md"],
    }
