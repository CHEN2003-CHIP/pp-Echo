from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from pp_agent.web.server import create_app


def test_config_api_get_set_and_conflict(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = TestClient(create_app(workspace))

    initial = client.get("/api/config").json()
    response = client.post(
        "/api/config/set",
        json={"path": "model.model", "value": "api-model", "base_hash": initial["config_hash"]},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["settings"]["model"]["model"] == "api-model"

    conflict = client.post(
        "/api/config/set",
        json={"path": "model.model", "value": "stale-model", "base_hash": initial["config_hash"]},
    )
    assert conflict.status_code == 409


def test_config_api_session_model_and_runtime_debug(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = TestClient(create_app(workspace))

    model_response = client.post("/api/sessions/session-1/model", json={"model": "provider/session-model"})
    debug_response = client.post("/api/debug/set", json={"path": "debug.trace", "value": True, "session_id": "session-1"})

    assert model_response.status_code == 200
    assert model_response.json()["settings"]["model"]["model"] == "provider/session-model"
    assert debug_response.status_code == 200
    assert debug_response.json()["runtime_config"]["debug"]["trace"] is True


def test_config_api_profile_and_session_override(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = TestClient(create_app(workspace))

    initial = client.get("/api/config?session_id=session-1").json()
    profile_response = client.post(
        "/api/config/profile/set",
        json={
            "profile": "fast",
            "path": "model.model",
            "value": "profile-model",
            "base_hash": initial["config_hash"],
            "session_id": "session-1",
        },
    )
    assert profile_response.status_code == 200

    updated_hash = profile_response.json()["config_hash"]
    active_response = client.post(
        "/api/config/profile",
        json={"profile": "fast", "base_hash": updated_hash, "session_id": "session-1"},
    )
    assert active_response.status_code == 200
    assert active_response.json()["settings"]["model"]["model"] == "profile-model"
    assert active_response.json()["active_profile"] == "fast"

    session_response = client.post(
        "/api/sessions/session-1/config/set",
        json={"path": "model.model", "value": "session-model"},
    )
    assert session_response.status_code == 200
    assert session_response.json()["settings"]["model"]["model"] == "session-model"
    assert session_response.json()["source_map"]["model.model"] == "session"


def test_config_api_validation_errors_are_structured(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = TestClient(create_app(workspace))

    response = client.post("/api/config/set", json={"path": "unknown.value", "value": True})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["errors"][0]["path"] == "unknown.value"
