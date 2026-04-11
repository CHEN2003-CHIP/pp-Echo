from __future__ import annotations

from pp_agent.api import sdk
from pp_agent.cli.render import approvals as approvals_render


class FakeConsole:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *args, **kwargs) -> None:
        self.lines.append(" ".join(str(arg) for arg in args))

    def rendered_text(self) -> str:
        return "\n".join(self.lines)


def test_render_approval_panel_shows_structured_planner_details(monkeypatch, tmp_path) -> None:
    fake_console = FakeConsole()
    monkeypatch.setattr(approvals_render, "console", fake_console)
    monkeypatch.setattr(
        approvals_render,
        "approvals_summary_payload",
        lambda workspace: {
            "count": 1,
            "by_type": {"planner_approval": 1},
            "items": [
                {
                    "token": "tok-12345678",
                    "action_type": "planner_approval",
                    "lifecycle": {"state": "pending"},
                    "details": {
                        "session_id": "session-1",
                        "summary": ["Edit README.md [edit_file]"],
                        "files_touched_guess": ["README.md"],
                        "shell_commands_guess": ["pytest -q"],
                        "high_risk_tools": ["edit_file"],
                    },
                }
            ],
        },
    )

    approvals_render.render_approval_panel(tmp_path)

    text = fake_console.rendered_text()
    assert "== Approvals Queue ==" in text
    assert "token     tok-12345678" in text
    assert "summary" in text
    assert "- Edit README.md [edit_file]" in text
    assert "actions   /approvals show tok-12345678 | /approve tok-12345678 | /reject tok-12345678" in text
