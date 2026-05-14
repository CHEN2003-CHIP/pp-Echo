from __future__ import annotations

from pathlib import Path

from pp_agent.web import server as server_module
from pp_agent.web.server import create_app
from pp_agent.web.session_manager import WebSessionManager
from pp_agent.web.workspaces import WebWorkspaceManager
from pp_agent.tools.registry import ToolRegistry

from tests.web.test_session_manager import _factory


def _app(tmp_path: Path, manager: WebSessionManager | None = None):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    active_manager = manager or WebSessionManager(workspace, runtime_factory=_factory)
    workspace_manager = WebWorkspaceManager(
        workspace,
        initial_manager=active_manager,
        session_manager_factory=lambda path: WebSessionManager(path, runtime_factory=_factory),
        state_dir=tmp_path / "state",
    )
    return create_app(workspace, workspace_manager=workspace_manager)


def test_web_api_health_and_session_create(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(_app(tmp_path))

    health = client.get("/api/health")
    created = client.post("/api/sessions")

    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert created.status_code == 200
    assert created.json()["session_id"] == "session-1"


def test_web_api_prompt_endpoint(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = WebSessionManager(workspace, runtime_factory=_factory)
    client = TestClient(_app(tmp_path, manager))
    session_id = client.post("/api/sessions").json()["session_id"]

    response = client.post(f"/api/sessions/{session_id}/prompt", json={"prompt": "hello"})
    manager.get_handle(session_id)._worker.join(timeout=2)

    assert response.status_code == 200
    assert response.json()["queued"] is False
    assert manager.get_handle(session_id).drain_events()[0]["type"] == "message_delta"


def test_web_api_events_polling_endpoint(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = WebSessionManager(workspace, runtime_factory=_factory)
    client = TestClient(_app(tmp_path, manager))
    session_id = client.post("/api/sessions").json()["session_id"]
    response = client.post(f"/api/sessions/{session_id}/prompt", json={"prompt": "hello"})
    manager.get_handle(session_id)._worker.join(timeout=2)

    events = client.get(f"/api/sessions/{session_id}/events")

    assert response.status_code == 200
    assert events.status_code == 200
    assert events.json()["events"][0]["type"] == "message_delta"


def test_web_api_approves_pending_action_token(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    captured = {}

    def fake_approve(workspace: Path, token: str, render: bool = True) -> dict:
        captured.update({"workspace": workspace, "token": token, "render": render})
        return {"token": token, "result": "approved"}

    manager = WebSessionManager(tmp_path / "workspace", runtime_factory=_factory)
    monkeypatch.setattr(server_module, "approve_or_execute_pending_action", fake_approve)
    client = TestClient(_app(tmp_path, manager))

    response = client.post("/api/approvals/tok-1/approve")

    assert response.status_code == 200
    assert response.json()["result"] == "approved"
    assert captured == {"workspace": (tmp_path / "workspace").resolve(), "token": "tok-1", "render": False}


def test_web_api_approve_pending_action_applies_write_and_removes_token(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    staged = ToolRegistry(workspace).execute("write_file", {"path": "MEMORY.md", "content": "# Memory\n"})
    token = staged.details["token"]
    client = TestClient(_app(tmp_path, WebSessionManager(workspace, runtime_factory=_factory)))

    response = client.post(f"/api/approvals/{token}/approve")
    approvals = client.get("/api/approvals")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["lifecycle"]["state"] == "grant_consumed"
    assert (workspace / "MEMORY.md").read_text(encoding="utf-8") == "# Memory\n"
    assert token not in approvals.json()["tokens"]
    assert all(item["token"] != token for item in approvals.json()["items"])


def test_web_api_rejects_pending_action_token(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    captured = {}

    def fake_reject(workspace: Path, token: str, render: bool = True) -> dict:
        captured.update({"workspace": workspace, "token": token, "render": render})
        return {"token": token, "result": "rejected"}

    manager = WebSessionManager(tmp_path / "workspace", runtime_factory=_factory)
    monkeypatch.setattr(server_module, "reject_pending_action_by_token", fake_reject)
    client = TestClient(_app(tmp_path, manager))

    response = client.post("/api/approvals/tok-1/reject")

    assert response.status_code == 200
    assert response.json()["result"] == "rejected"
    assert captured == {"workspace": (tmp_path / "workspace").resolve(), "token": "tok-1", "render": False}


def test_web_api_workspace_open_requires_confirmation_then_switches(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(_app(tmp_path))
    other = tmp_path / "other"
    other.mkdir()

    preview = client.post("/api/workspaces/open", json={"path": str(other), "confirmed": False})
    switched = client.post("/api/workspaces/open", json={"path": str(other), "confirmed": True})
    workspace = client.get("/api/workspace")

    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True
    assert switched.status_code == 200
    assert switched.json()["requires_confirmation"] is False
    assert workspace.json()["path"] == str(other.resolve())


def test_web_api_workspace_open_rejects_missing_path(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(_app(tmp_path))

    response = client.post("/api/workspaces/open", json={"path": str(tmp_path / "missing"), "confirmed": True})

    assert response.status_code == 400
