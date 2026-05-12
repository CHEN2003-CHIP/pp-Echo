from __future__ import annotations

from pathlib import Path

from pp_agent.web import server as server_module
from pp_agent.web.server import create_app
from pp_agent.web.session_manager import WebSessionManager

from tests.web.test_session_manager import _factory


def test_web_api_health_and_session_create(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    client = TestClient(create_app(tmp_path, manager=manager))

    health = client.get("/api/health")
    created = client.post("/api/sessions")

    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert created.status_code == 200
    assert created.json()["session_id"] == "session-1"


def test_web_api_prompt_endpoint(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    client = TestClient(create_app(tmp_path, manager=manager))
    session_id = client.post("/api/sessions").json()["session_id"]

    response = client.post(f"/api/sessions/{session_id}/prompt", json={"prompt": "hello"})
    manager.get_handle(session_id)._worker.join(timeout=2)

    assert response.status_code == 200
    assert response.json()["queued"] is False
    assert manager.get_handle(session_id).drain_events()[0]["type"] == "message_delta"


def test_web_api_events_polling_endpoint(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    client = TestClient(create_app(tmp_path, manager=manager))
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

    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    monkeypatch.setattr(server_module, "approve_or_execute_pending_action", fake_approve)
    client = TestClient(create_app(tmp_path, manager=manager))

    response = client.post("/api/approvals/tok-1/approve")

    assert response.status_code == 200
    assert response.json()["result"] == "approved"
    assert captured == {"workspace": tmp_path.resolve(), "token": "tok-1", "render": False}


def test_web_api_rejects_pending_action_token(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    captured = {}

    def fake_reject(workspace: Path, token: str, render: bool = True) -> dict:
        captured.update({"workspace": workspace, "token": token, "render": render})
        return {"token": token, "result": "rejected"}

    manager = WebSessionManager(tmp_path, runtime_factory=_factory)
    monkeypatch.setattr(server_module, "reject_pending_action_by_token", fake_reject)
    client = TestClient(create_app(tmp_path, manager=manager))

    response = client.post("/api/approvals/tok-1/reject")

    assert response.status_code == 200
    assert response.json()["result"] == "rejected"
    assert captured == {"workspace": tmp_path.resolve(), "token": "tok-1", "render": False}
