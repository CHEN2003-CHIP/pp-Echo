from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from prompt_toolkit.application import Application
from prompt_toolkit.clipboard import Clipboard, ClipboardData, InMemoryClipboard
from prompt_toolkit.document import Document, PasteMode
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea

from pp_agent.runtime import AgentEvent
from pp_agent.tui.controller import TuiController
from pp_agent.tui.reducer import hydrate_state_from_runtime, reduce_event
from pp_agent.tui.state import TuiMessage, TuiState, append_log


class PromptToolkitTuiApp:
    def __init__(self, workspace: Path, session_id: Optional[str] = None) -> None:
        self.controller = TuiController(workspace, session_id=session_id)
        self.state = hydrate_state_from_runtime(
            TuiState(),
            self.controller.agent,
            session_epoch=self.controller.session_epoch,
            pending_plan_details=self.controller.pending_plan_preview_details(),
        )

        self.transcript_area = TextArea(
            text="",
            focusable=True,
            scrollbar=True,
            wrap_lines=True,
            read_only=True,
            style="class:transcript.text",
        )
        self.approval_area = TextArea(text="", focusable=False, wrap_lines=True, read_only=True, style="class:side.text")
        self.plan_area = TextArea(text="", focusable=False, wrap_lines=True, read_only=True, style="class:side.text")
        self.activity_area = TextArea(text="", focusable=False, wrap_lines=True, read_only=True, style="class:side.text")
        self.input_area = TextArea(
            text="",
            multiline=True,
            wrap_lines=True,
            focus_on_click=True,
            scrollbar=True,
            height=Dimension(min=3, preferred=3, max=4),
            dont_extend_height=True,
            style="class:composer.input",
        )

        self.header_control = FormattedTextControl(self._header_fragments)
        self.helper_control = FormattedTextControl(self._helper_fragments)
        self.prompt_control = FormattedTextControl(self._prompt_fragments)

        self.application = Application(
            layout=Layout(self._build_root(), focused_element=self.input_area),
            key_bindings=self._build_keybindings(),
            style=_build_style(),
            clipboard=_build_clipboard(),
            full_screen=True,
            mouse_support=True,
            refresh_interval=0.1,
            before_render=lambda app: self._before_render(),
        )

    def _build_root(self):
        sidebar = HSplit(
            [
                Frame(self.approval_area, title="approval", style="class:approval.frame", height=Dimension(weight=1)),
                Frame(self.plan_area, title="plan", style="class:side.frame", height=Dimension(weight=1)),
                Frame(self.activity_area, title="activity", style="class:side.frame", height=Dimension(weight=1)),
            ],
            padding=1,
            width=Dimension(weight=1),
            style="class:sidebar.shell",
        )

        transcript = Frame(
            self.transcript_area,
            title="messages",
            style="class:transcript.frame",
            width=Dimension(weight=3),
        )

        composer = Frame(
            VSplit(
                [
                    Window(content=self.prompt_control, width=18, style="class:composer.rail"),
                    self.input_area,
                ]
            ),
            title="composer",
            style="class:composer.frame",
            height=Dimension(min=5, preferred=5, max=6),
        )

        return HSplit(
            [
                Window(content=self.header_control, height=2, style="class:header.box"),
                VSplit([transcript, sidebar], padding=1),
                Window(content=self.helper_control, height=1, style="class:helper.box"),
                composer,
            ],
            padding=1,
        )

    def _build_keybindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("c-q")
        def _(event) -> None:
            event.app.exit()

        @kb.add("c-c")
        def _(event) -> None:
            self._copy_selection(event)

        @kb.add("c-l")
        def _(event) -> None:
            event.app.layout.focus(self.input_area)

        @kb.add("tab")
        def _(event) -> None:
            event.app.layout.focus_next()

        @kb.add("s-tab")
        def _(event) -> None:
            event.app.layout.focus_previous()

        @kb.add("c-s")
        def _(event) -> None:
            if event.app.layout.has_focus(self.input_area):
                self._submit_input()

        @kb.add("escape", "enter")
        def _(event) -> None:
            if event.app.layout.has_focus(self.input_area):
                self._submit_input()

        @kb.add("c-v")
        @kb.add("s-insert")
        def _(event) -> None:
            self._paste_clipboard(event)

        @kb.add("c-insert")
        def _(event) -> None:
            self._copy_selection(event)

        return kb

    def _before_render(self) -> None:
        changed = False
        for agent_event in self.controller.drain_events():
            self.state = reduce_event(self.state, agent_event)
            changed = True
        self._sync_views(update_only=not changed)

    def _copy_selection(self, event) -> None:
        current_buffer = getattr(event.app, "current_buffer", None) or self.input_area.buffer
        if current_buffer is None or current_buffer.selection_state is None:
            return
        event.app.clipboard.set_data(current_buffer.copy_selection())

    def _paste_clipboard(self, event) -> None:
        data = event.app.clipboard.get_data()
        if not getattr(data, "text", ""):
            return
        event.app.layout.focus(self.input_area)
        self.input_area.buffer.paste_clipboard_data(data, paste_mode=PasteMode.EMACS)

    def _submit_input(self) -> None:
        value = self.input_area.text.strip()
        self.input_area.buffer.text = ""
        if not value:
            return

        lowered = value.lower()
        is_manual_approval = lowered in {"approve", "reject"}
        is_command = value.startswith("/")

        if not is_command and not is_manual_approval:
            self.state.messages.append(
                TuiMessage(
                    id=f"local-user-{time.time():.6f}",
                    role="user",
                    text=value,
                    highlight=True,
                )
            )
            if not self.controller.is_busy() and not self.state.approval_state.awaiting_approval:
                self.state = reduce_event(
                    self.state,
                    AgentEvent(
                        type="local_waiting",
                        session_id=self.controller.session_id,
                        message="assistant is thinking ...",
                        details={},
                    ),
                )

        try:
            result = self.controller.submit(value)
            if result in {"new", "resume"}:
                self.state = hydrate_state_from_runtime(
                    TuiState(),
                    self.controller.agent,
                    session_epoch=self.controller.session_epoch,
                    pending_plan_details=self.controller.pending_plan_preview_details(),
                )
        except Exception as exc:  # noqa: BLE001
            append_log(self.state, f"Error: {exc}", level="error", important=True)
            self.state = reduce_event(
                self.state,
                AgentEvent(type="local_warning", session_id=self.controller.session_id, message=str(exc), details={}),
            )
        self._sync_views(update_only=False)

    def _sync_views(self, *, update_only: bool = True) -> None:
        transcript_text = _render_transcript(self.state)
        approval_text = _render_approval(self.state)
        plan_text = _render_plan(self.state)
        activity_text = _render_activity(self.state)

        if not update_only or self.transcript_area.buffer.text != transcript_text:
            self.transcript_area.buffer.set_document(
                Document(transcript_text, cursor_position=len(transcript_text)),
                bypass_readonly=True,
            )
        if not update_only or self.approval_area.buffer.text != approval_text:
            self.approval_area.buffer.set_document(Document(approval_text), bypass_readonly=True)
        if not update_only or self.plan_area.buffer.text != plan_text:
            self.plan_area.buffer.set_document(Document(plan_text), bypass_readonly=True)
        if not update_only or self.activity_area.buffer.text != activity_text:
            self.activity_area.buffer.set_document(Document(activity_text), bypass_readonly=True)

    def _header_fragments(self):
        mood_style, mood_label = _mood(self.state)
        runtime = self.state.runtime_phase
        summary = f"session {runtime.session_id or '-'}  turn {runtime.turn_id}  phase {runtime.phase}"
        queue = f"queue {runtime.queue_count}"
        return [
            ("class:header.brand", "pp-Echo"),
            ("class:header.dim", "  tui  "),
            (mood_style, mood_label),
            ("class:header.dim", "\n" + summary + "  " + queue),
        ]

    def _helper_fragments(self):
        return [
            ("class:helper.mode", self.state.composer.mode_label.lower()),
            ("class:helper.dim", f"  {self.state.composer.helper_text}"),
        ]

    def _prompt_fragments(self):
        style = {
            "READY": "class:prompt.ready",
            "WAITING": "class:prompt.waiting",
            "BUSY": "class:prompt.busy",
            "APPROVAL": "class:prompt.approval",
        }.get(self.state.composer.mode_label, "class:prompt.ready")
        label = self.state.composer.prompt_prefix.rstrip() or ">"
        hint = "approve|reject" if self.state.approval_state.awaiting_approval else label
        return [(style, f" {hint:<14}")]

    def run(self) -> None:
        self._sync_views(update_only=False)
        self.application.run()


class _ShellClipboard(Clipboard):
    def __init__(self) -> None:
        self._fallback = InMemoryClipboard()

    def set_data(self, data: ClipboardData) -> None:
        self._fallback.set_data(data)
        try:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                input=data.text,
                text=True,
                capture_output=True,
                check=False,
                timeout=1,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def get_data(self) -> ClipboardData:
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                text=True,
                capture_output=True,
                check=False,
                timeout=1,
            )
        except (OSError, subprocess.TimeoutExpired):
            return self._fallback.get_data()
        if result.returncode == 0:
            data = ClipboardData(result.stdout.replace("\r\n", "\n"))
            self._fallback.set_data(data)
            return data
        return self._fallback.get_data()


def _build_clipboard() -> Clipboard:
    try:
        from prompt_toolkit.clipboard.pyperclip import PyperclipClipboard
    except ImportError:
        PyperclipClipboard = None
    if PyperclipClipboard is not None:
        try:
            return PyperclipClipboard()
        except Exception:
            pass
    if os.name == "nt":
        return _ShellClipboard()
    return InMemoryClipboard()


def _mood(state: TuiState) -> tuple[str, str]:
    if state.approval_state.awaiting_approval:
        return "class:header.warning", "approval"
    if state.runtime_phase.busy:
        return "class:header.busy", "busy"
    if state.awaiting_assistant:
        return "class:header.waiting", "waiting"
    return "class:header.ready", "ready"


def _render_transcript(state: TuiState) -> str:
    chunks: list[str] = []
    previous_role: str | None = None
    for message in state.messages:
        if message.kind == "status":
            chunks.append(f"- {message.text}")
            previous_role = "status"
            continue
        label = "you" if message.role == "user" else "assistant" if message.role == "assistant" else message.role
        body = "\n".join(f"  {line}" for line in (message.text.strip() or "(empty)").splitlines())
        if previous_role and previous_role != message.role and chunks:
            chunks.append("")
        chunks.append(f"{label}\n{body}")
        previous_role = message.role
    if state.awaiting_assistant and not state.active_assistant_message.text:
        if chunks:
            chunks.append("")
        chunks.append("- assistant is thinking ...")
    elif state.active_assistant_message.text:
        if chunks:
            chunks.append("")
        body = "\n".join(f"  {line}" for line in state.active_assistant_message.text.splitlines())
        tail = "\n  ..." if state.active_assistant_message.streaming else ""
        chunks.append(f"assistant\n{body}{tail}")
    return "\n".join(chunks) if chunks else "Conversation will appear here."


def _render_approval(state: TuiState) -> str:
    if state.approval_state.awaiting_approval:
        token = state.approval_state.token_preview or "pending"
        return (
            "pending\n"
            f"token   {token}\n\n"
            "approve\n"
            "reject"
        )
    return "clear"


def _render_plan(state: TuiState) -> str:
    lines: list[str] = []
    if state.plan_summary:
        lines.append("summary")
        for item in state.plan_summary[:4]:
            lines.append(f"- {item}")
    elif state.plan_steps:
        lines.append("steps")
        for step in state.plan_steps:
            tool = f" [{step.tool_name}]" if step.tool_name else ""
            lines.append(f"{step.status.lower():<10} {step.title}{tool}")
    elif state.approval_state.awaiting_approval:
        lines.append("awaiting approval")
    else:
        lines.append("idle")

    if state.plan_files:
        lines.extend(["", "files"])
        for item in state.plan_files[:4]:
            lines.append(f"- {item}")

    if state.plan_shell_commands:
        lines.extend(["", "shell"])
        for item in state.plan_shell_commands[:3]:
            lines.append(f"- {item}")

    if state.plan_high_risk_tools:
        lines.extend(["", f"high-risk  {', '.join(state.plan_high_risk_tools[:4])}"])

    if state.plan_token_preview:
        lines.extend(["", f"token      {state.plan_token_preview}"])

    lines.extend(
        [
            "",
            f"queue      {state.queue_summary.queue_count}",
            f"steering   {state.queue_summary.steering_count}",
            f"follow-up  {state.queue_summary.follow_up_count}",
        ]
    )
    if state.queue_summary.latest_action:
        lines.extend(["", state.queue_summary.latest_action])
    return "\n".join(lines)


def _render_activity(state: TuiState) -> str:
    entries = state.ephemeral_logs[-8:]
    if not entries:
        return "no recent activity"
    lines = []
    for entry in entries:
        prefix = entry.level.lower()
        if entry.important:
            prefix += "*"
        lines.append(f"{prefix:<8} {entry.message}")
    return "\n".join(lines)


def _build_style() -> Style:
    return Style.from_dict(
        {
            "header.box": "bg:#0f1317 #e6edf3",
            "header.brand": "bold #ffffff",
            "header.dim": "#7f8b96",
            "header.ready": "bold #6fd58c",
            "header.waiting": "bold #8cd9ff",
            "header.busy": "bold #63baff",
            "header.warning": "bold #f0c75e",
            "transcript.frame": "bg:#0d1117 #d6dde5",
            "transcript.text": "bg:#0d1117 #d6dde5",
            "sidebar.shell": "bg:#101418 #c8d1d9",
            "side.frame": "bg:#101418 #c8d1d9",
            "approval.frame": "bg:#17140f #f0c75e",
            "side.text": "bg:#101418 #c8d1d9",
            "helper.box": "bg:#0d1117 #7f8b96",
            "helper.mode": "bold #e6edf3",
            "helper.dim": "#7f8b96",
            "composer.frame": "bg:#101418 #e6edf3",
            "composer.rail": "bg:#0b0f13 #7f8b96",
            "composer.input": "bg:#0b0f13 #e6edf3",
            "prompt.ready": "bold #6fd58c",
            "prompt.waiting": "bold #8cd9ff",
            "prompt.busy": "bold #63baff",
            "prompt.approval": "bold #f0c75e",
        }
    )


def run_tui_app(workspace: Path, session_id: Optional[str] = None) -> None:
    PromptToolkitTuiApp(workspace, session_id=session_id).run()
