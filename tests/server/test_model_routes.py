from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from pp_agent.web.server import create_app


def test_model_provider_routes_list_presets(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.get("/api/models/providers")

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["providers"]}
    assert "deepseek" in ids
    assert "anthropic" in ids


def test_model_test_route_returns_warning_without_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ROUTE_MODEL_KEY", raising=False)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/models/test",
        json={
            "provider": {"name": "openai", "base_url": "https://example.test/v1", "api_key_env": "ROUTE_MODEL_KEY"},
            "model": {"provider": "openai", "model": "gpt-test", "temperature": 0.2, "enable_thinking": False},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "warning"


def test_apply_model_preset_updates_config(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    initial = client.get("/api/config").json()

    response = client.post(
        "/api/models/apply-preset",
        json={"provider_id": "deepseek", "model": "deepseek-chat", "base_hash": initial["config_hash"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["settings"]["provider"]["name"] == "deepseek"
    assert payload["settings"]["model"]["model"] == "deepseek-chat"


def test_session_model_switch_can_sync_provider_preset(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/sessions/session-1/model",
        json={"provider_id": "xiaomi", "model": "mimo-v2.5-pro"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["settings"]["provider"]["name"] == "xiaomi"
    assert payload["settings"]["provider"]["base_url"] == "https://api.xiaomimimo.com/v1"
    assert payload["settings"]["provider"]["api_key_env"] == "MIMO_API_KEY"
    assert payload["settings"]["model"]["provider"] == "xiaomi"
    assert payload["settings"]["model"]["model"] == "mimo-v2.5-pro"


def test_model_usage_lists_configured_provider_models(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.get("/api/models/usage")

    assert response.status_code == 200
    models = response.json()["models"]
    mimo = next(item for item in models if item["provider_id"] == "xiaomi" and item["model"] == "mimo-v2.5-pro")
    assert mimo["api_key_env"] == "MIMO_API_KEY"
    assert "api_key_configured" in mimo
