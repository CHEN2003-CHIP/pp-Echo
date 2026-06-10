from __future__ import annotations

from pathlib import Path

from pp_agent.server.routes import qqbot as qqbot_routes
from pp_agent.web.server import create_app
from pp_agent.web.session_manager import WebSessionManager

from tests.web.test_session_manager import _factory


def _app(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return create_app(workspace, manager=WebSessionManager(workspace, runtime_factory=_factory))


def test_qqbot_webhook_disabled_returns_404(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.delenv("PP_ECHO_QQBOT_ENABLED", raising=False)
    client = TestClient(_app(tmp_path))

    response = client.post("/api/integrations/qqbot/webhook", json={"op": 0})

    assert response.status_code == 404


def test_qqbot_webhook_enabled_missing_config_returns_500(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PP_ECHO_QQBOT_ENABLED", "true")
    monkeypatch.delenv("PP_ECHO_QQBOT_APP_ID", raising=False)
    monkeypatch.delenv("PP_ECHO_QQBOT_APP_SECRET", raising=False)
    client = TestClient(_app(tmp_path))

    response = client.post("/api/integrations/qqbot/webhook", json={"op": 0})

    assert response.status_code == 500


def test_qqbot_callback_validation(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PP_ECHO_QQBOT_ENABLED", "true")
    monkeypatch.setenv("PP_ECHO_QQBOT_APP_ID", "app")
    monkeypatch.setenv("PP_ECHO_QQBOT_APP_SECRET", "secret")
    client = TestClient(_app(tmp_path))

    response = client.post("/api/integrations/qqbot/webhook", json={"op": 13, "d": {"plain_token": "plain", "event_ts": "123"}})

    assert response.status_code == 200
    assert response.json()["plain_token"] == "plain"
    assert response.json()["signature"]


def test_qqbot_event_ack_and_status_are_safe(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    called = {}

    class FakeAdapter:
        def __init__(self, **kwargs) -> None:
            called["init"] = kwargs

        async def handle_payload(self, payload):
            called["payload"] = payload

    monkeypatch.setenv("PP_ECHO_QQBOT_ENABLED", "true")
    monkeypatch.setenv("PP_ECHO_QQBOT_APP_ID", "app")
    monkeypatch.setenv("PP_ECHO_QQBOT_APP_SECRET", "secret")
    monkeypatch.setattr(qqbot_routes, "QQBotAdapter", FakeAdapter)
    client = TestClient(_app(tmp_path))

    response = client.post("/api/integrations/qqbot/webhook", json={"op": 0, "id": "e", "t": "OTHER", "d": {}})
    status = client.get("/api/integrations/qqbot/status")

    assert response.status_code == 200
    assert response.json() == {"op": 12}
    assert status.json()["enabled"] is True
    assert "secret" not in str(status.json()).lower()
    assert called["payload"]["id"] == "e"

