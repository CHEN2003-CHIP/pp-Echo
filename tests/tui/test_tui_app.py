from __future__ import annotations

from pathlib import Path

from prompt_toolkit.clipboard import ClipboardData

from pp_agent.tui.app import PromptToolkitTuiApp, _render_plan
from pp_agent.tui.state import TuiState


class FakeState:
    def __init__(self) -> None:
        self.pending_plan_token = None
        self.pending_tool_calls = []
        self.queued_messages = []
        self.turn = type("Turn", (), {"turn_id": 0, "phase": "idle", "reason": ""})()
        self.is_streaming = False
        self.messages = []
        self.system_prompt = ""
        self.compaction = type("Compaction", (), {"summary": "", "summarized_message_count": 0})()


class FakeRuntime:
    def __init__(self) -> None:
        self.session_id = "session-1"
        self.state = FakeState()

    def subscribe(self, callback) -> None:
        self.subscriber = callback


def test_render_plan_shows_summary_files_shell_and_token() -> None:
    state = TuiState()
    state.plan_summary = ["Read README.md [read_file]", "Edit README.md [edit_file]"]
    state.plan_files = ["README.md"]
    state.plan_shell_commands = ["pytest -q"]
    state.plan_high_risk_tools = ["edit_file"]
    state.plan_token_preview = "tok-1234"

    rendered = _render_plan(state)

    assert "summary" in rendered
    assert "Read README.md [read_file]" in rendered
    assert "files" in rendered
    assert "README.md" in rendered
    assert "shell" in rendered
    assert "pytest -q" in rendered
    assert "high-risk  edit_file" in rendered
    assert "token      tok-1234" in rendered


def test_tui_copy_and_paste_helpers() -> None:
    class FakeBuffer:
        def __init__(self) -> None:
            self.selection_state = object()
            self.pasted: list[str] = []

        def copy_selection(self):
            return ClipboardData("hello")

        def paste_clipboard_data(self, data, paste_mode=None, count=1):
            self.pasted.append(data.text)

    class FakeClipboard:
        def __init__(self) -> None:
            self.data = ClipboardData("")

        def set_data(self, data):
            self.data = data

        def get_data(self):
            return self.data

    buffer = FakeBuffer()
    clipboard = FakeClipboard()

    class FakeLayout:
        def __init__(self) -> None:
            self.focused = None

        def focus(self, target) -> None:
            self.focused = target

    app = object.__new__(PromptToolkitTuiApp)
    app.input_area = type("InputArea", (), {"buffer": buffer})()
    layout = FakeLayout()
    event = type("Event", (), {"app": type("App", (), {"current_buffer": None, "clipboard": clipboard, "layout": layout})()})()

    app._copy_selection(event)
    assert clipboard.get_data().text == "hello"

    clipboard.set_data(ClipboardData("pasted text"))
    app._paste_clipboard(event)
    assert layout.focused is app.input_area
    assert buffer.pasted == ["pasted text"]
