from __future__ import annotations

from pathlib import Path

from pp_agent.web.session_manager import WebSessionManager
from pp_agent.web.workspaces import WebWorkspaceManager

from tests.web.test_session_manager import _factory


def _manager(root: Path) -> WebWorkspaceManager:
    workspace = root / "one"
    workspace.mkdir()
    return WebWorkspaceManager(
        workspace,
        session_manager_factory=lambda path: WebSessionManager(path, runtime_factory=_factory),
        state_dir=root / "state",
    )


def test_workspace_manager_previews_unknown_workspace_before_switch(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    other = tmp_path / "two"
    other.mkdir()

    result = manager.open_workspace(str(other), confirmed=False)

    assert result["requires_confirmation"] is True
    assert result["candidate"]["path"] == str(other.resolve())
    assert manager.active_workspace == (tmp_path / "one").resolve()


def test_workspace_manager_switches_and_uses_isolated_session_managers(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    first_session = manager.active_session_manager()
    other = tmp_path / "two"
    other.mkdir()

    result = manager.open_workspace(str(other), confirmed=True)
    second_session = manager.active_session_manager()

    assert result["requires_confirmation"] is False
    assert manager.active_workspace == other.resolve()
    assert first_session is not second_session
    assert second_session.workspace == other.resolve()


def test_workspace_manager_persists_recent_workspaces(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    other = tmp_path / "two"
    other.mkdir()
    manager.open_workspace(str(other), confirmed=True)

    restored = WebWorkspaceManager(
        tmp_path / "one",
        session_manager_factory=lambda path: WebSessionManager(path, runtime_factory=_factory),
        state_dir=tmp_path / "state",
    )

    assert restored.summary()["recent"][1]["path"] == str(other.resolve())


def test_workspace_manager_rejects_empty_and_missing_paths(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    try:
        manager.open_workspace("", confirmed=True)
    except ValueError as exc:
        assert "cannot be empty" in str(exc)
    else:
        raise AssertionError("Expected empty workspace path to fail")

    try:
        manager.open_workspace(str(tmp_path / "missing"), confirmed=True)
    except FileNotFoundError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("Expected missing workspace path to fail")
