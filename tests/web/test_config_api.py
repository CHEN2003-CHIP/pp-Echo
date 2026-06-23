from __future__ import annotations

import json
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


def test_session_tools_api_uses_capability_descriptors(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = TestClient(create_app(workspace))
    session = client.post("/api/sessions").json()

    response = client.get(f"/api/sessions/{session['session_id']}/tools")

    assert response.status_code == 200
    tools = response.json()["tools"]
    run_shell = next(item for item in tools if item["name"] == "run_shell")
    assert run_shell["kind"] == "builtin_tool"
    assert run_shell["risk_level"] == "shell"
    assert run_shell["effects"] == ["shell_command"]


def test_capability_config_includes_catalog_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = TestClient(create_app(workspace))

    response = client.get("/api/capability-config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["capabilities"]["count"] > 0
    assert payload["capabilities"]["by_kind"]["builtin_tool"] > 0
    assert any(item["id"] == "run_shell" for item in payload["capabilities"]["items"])


def test_capability_config_uses_fast_static_mcp_snapshot_by_default(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_dir = workspace / ".pp-agent"
    project_dir.mkdir()
    (project_dir / "config.json").write_text(json.dumps({"capabilities": {"mcp": {"enable": True}}}), encoding="utf-8")
    (project_dir / "mcp.json").write_text(json.dumps({"servers": [{"name": "demo", "transport": "memory"}]}), encoding="utf-8")
    client = TestClient(create_app(workspace))

    response = client.get("/api/capability-config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mcp"]["servers"][0]["name"] == "demo"
    assert payload["capabilities"]["by_kind"].get("mcp_tool", 0) == 0


def test_capability_config_skills_are_metadata_only_and_detail_loads_body(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_path = workspace / "skills" / "repo-helper" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("---\nname: repo-helper\ndescription: Repository helper\n---\nUse rg first.", encoding="utf-8")
    client = TestClient(create_app(workspace))

    inventory = client.get("/api/capability-config").json()
    detail = client.get("/api/skills/repo-helper").json()

    item = next(item for item in inventory["skills"]["items"] if item["name"] == "repo-helper")
    assert item["name"] == "repo-helper"
    assert item["body"] == ""
    assert item["body_materialized"] is False
    assert detail["body"] == "Use rg first."
    assert detail["body_materialized"] is True
