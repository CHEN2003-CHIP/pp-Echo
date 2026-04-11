from __future__ import annotations

from pp_agent.cli.render import sessions as sessions_render
from pp_agent.storage.sessions import SessionTreeEntry


class FakeConsole:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *args, **kwargs) -> None:
        self.lines.append(" ".join(str(arg) for arg in args))

    def rendered_text(self) -> str:
        return "\n".join(self.lines)


class FakeStore:
    def __init__(self, entries, description) -> None:
        self._entries = entries
        self._description = description

    def tree(self):
        return list(self._entries)

    def describe(self, session_id: str):
        return self._description


def _entry(session_id: str, parent_id: str | None, updated_at: float) -> SessionTreeEntry:
    return SessionTreeEntry(
        id=session_id,
        parent_id=parent_id,
        updated_at=updated_at,
        model="demo-model",
        message_count=2,
        turn_count=1,
        pending_plan_token=None,
        active_head_id=None,
        summary_preview="",
        last_user_preview="",
        last_assistant_preview="",
    )


def test_render_session_tree_defaults_to_active_lineage_and_recent(monkeypatch, tmp_path) -> None:
    fake_console = FakeConsole()
    entries = [
        _entry("root-1234", None, 10),
        _entry("active-1", "root-1234", 20),
        _entry("old-branch", "root-1234", 15),
    ]
    description = {
        "current": entries[1].model_dump(mode="json"),
        "parent": entries[0].model_dump(mode="json"),
        "children": [],
        "turns": [],
        "turn_focus": None,
    }
    monkeypatch.setattr(sessions_render, "console", fake_console)
    monkeypatch.setattr(sessions_render, "session_store_for", lambda workspace: FakeStore(entries, description))

    sessions_render.render_session_tree(tmp_path, current_session_id="active-1", focus_session_id="active-1", view_mode="default")

    text = fake_console.rendered_text()
    assert "Active Lineage" in text
    assert "Recent Sessions" in text
    assert "older branch session(s) folded" in text
    assert "/tree full" in text


def test_render_session_tree_full_view_expands_all_branches(monkeypatch, tmp_path) -> None:
    fake_console = FakeConsole()
    entries = [
        _entry("root-1234", None, 10),
        _entry("active-1", "root-1234", 20),
        _entry("old-branch", "root-1234", 15),
    ]
    description = {
        "current": entries[1].model_dump(mode="json"),
        "parent": entries[0].model_dump(mode="json"),
        "children": [],
        "turns": [],
        "turn_focus": None,
    }
    monkeypatch.setattr(sessions_render, "console", fake_console)
    monkeypatch.setattr(sessions_render, "session_store_for", lambda workspace: FakeStore(entries, description))

    sessions_render.render_session_tree(tmp_path, current_session_id="active-1", focus_session_id="active-1", view_mode="full")

    text = fake_console.rendered_text()
    assert "older branch session(s) folded" not in text
    assert "old-bran" in text
