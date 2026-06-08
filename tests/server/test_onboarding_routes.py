from fastapi.testclient import TestClient

from pp_agent.web.server import create_app


def test_onboarding_status_route_returns_json(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.get("/api/onboarding/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace"] == str(tmp_path.resolve())
    assert isinstance(payload["checks"], list)
    assert any(item["id"] == "api_key" for item in payload["checks"])


def test_onboarding_check_model_without_api_key_is_structured(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("PP_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(create_app(tmp_path))

    response = client.post("/api/onboarding/check-model")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "model_connectivity"
    assert payload["status"] in {"warning", "error"}
