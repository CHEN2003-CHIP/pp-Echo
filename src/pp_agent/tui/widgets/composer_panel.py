from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Static

from pp_agent.tui.state import TuiState


class ComposerPanel(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(id="composer_badges"):
            yield Static("READY", id="composer_mode_badge")
            yield Static("INPUT", id="composer_focus_badge")
            yield Static("", id="composer_pending_badge")
        yield Static(id="composer_helper")
        with Horizontal(id="composer_shell"):
            yield Static(">", id="composer_rail")
            yield Input(id="composer_input", placeholder="Ask pp-Echo what to do next")
        yield Static(id="composer_hint")

    def update_state(self, state: TuiState) -> None:
        mode_badge = self.query_one("#composer_mode_badge", Static)
        focus_badge = self.query_one("#composer_focus_badge", Static)
        pending_badge = self.query_one("#composer_pending_badge", Static)
        helper = self.query_one("#composer_helper", Static)
        hint = self.query_one("#composer_hint", Static)
        shell = self.query_one("#composer_shell", Horizontal)
        rail = self.query_one("#composer_rail", Static)
        input_widget = self.query_one("#composer_input", Input)

        mode_badge.update(state.composer.mode_label)
        focus_badge.update(state.composer.focus_label if input_widget.has_focus else "UNFOCUSED")
        pending_badge.update("PENDING" if state.composer.show_pending_badge else "")
        helper.update(state.composer.helper_text)
        hint.update(state.composer.command_hint)
        rail.update(state.composer.prompt_prefix)
        input_widget.placeholder = state.composer.placeholder

        for class_name in ("mode-ready", "mode-waiting", "mode-busy", "mode-approval"):
            enabled = class_name == f"mode-{state.composer.accent_variant}"
            self.set_class(enabled, class_name)
            shell.set_class(enabled, class_name)
            rail.set_class(enabled, class_name)
            mode_badge.set_class(enabled, class_name)
            pending_badge.set_class(enabled, class_name)

        self._sync_focus_classes()

    def on_descendant_focus(self, _event) -> None:
        self._sync_focus_classes()

    def on_descendant_blur(self, _event) -> None:
        self._sync_focus_classes()

    def _sync_focus_classes(self) -> None:
        input_widget = self.query_one("#composer_input", Input)
        shell = self.query_one("#composer_shell", Horizontal)
        focus_badge = self.query_one("#composer_focus_badge", Static)
        focused = input_widget.has_focus
        self.set_class(focused, "is-focused")
        self.set_class(not focused, "is-unfocused")
        shell.set_class(focused, "is-focused")
        shell.set_class(not focused, "is-unfocused")
        focus_badge.set_class(focused, "is-focused")

    def focus_input(self) -> None:
        self.query_one("#composer_input", Input).focus()
        self._sync_focus_classes()

    def input_widget(self) -> Input:
        return self.query_one("#composer_input", Input)
