from pathlib import Path

from pp_agent.onboarding.schema import OnboardingCheck
from pp_agent.onboarding.service import OnboardingService


def test_onboarding_service_builds_overall_status(tmp_path: Path) -> None:
    status = OnboardingService().build_status(tmp_path)

    assert status.workspace == str(tmp_path.resolve())
    assert status.overall_status in {"ready", "partial", "blocked"}
    assert {check.id for check in status.checks} >= {"python", "api_key", "workspace", "trace_store", "memory", "eval"}
    assert status.command_hints
    assert status.next_steps


def test_onboarding_overall_status_rules() -> None:
    service = OnboardingService()

    assert service._overall_status([OnboardingCheck(id="python", title="Python", status="error", summary="bad")]) == "blocked"
    assert service._overall_status([OnboardingCheck(id="api_key", title="API Key", status="warning", summary="missing")]) == "partial"
    assert service._overall_status([OnboardingCheck(id="node", title="Node", status="skipped", summary="skip")]) == "ready"


def test_check_model_without_api_key_is_warning(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PP_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    check = OnboardingService().check_model_connectivity(tmp_path)

    assert check.status == "warning"
    assert "API key" in check.summary
