from pathlib import Path

from pp_agent.onboarding.checks import check_api_key, check_python_version, check_trace_store, check_workspace


def test_api_key_missing_is_warning_without_leaking_value(monkeypatch) -> None:
    monkeypatch.delenv("PP_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    check = check_api_key()

    assert check.status == "warning"
    assert "your_api_key" in (check.action_command or "")


def test_api_key_present_reports_length_only(monkeypatch) -> None:
    monkeypatch.setenv("PP_AGENT_API_KEY", "secret-value")

    check = check_api_key()

    assert check.status == "ok"
    assert "长度 12" in check.detail
    assert "secret-value" not in check.model_dump_json()


def test_python_version_check_returns_status() -> None:
    check = check_python_version()

    assert check.status in {"ok", "error"}


def test_workspace_check_uses_temporary_probe_only(tmp_path: Path) -> None:
    existing = tmp_path / "keep.txt"
    existing.write_text("keep", encoding="utf-8")

    check = check_workspace(tmp_path)

    assert check.status == "ok"
    assert existing.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / ".pp-agent" / "onboarding.tmp").exists()


def test_trace_store_probe_is_deleted(tmp_path: Path) -> None:
    check = check_trace_store(tmp_path)

    assert check.status == "ok"
    assert not (tmp_path / ".pp-agent" / "traces" / "onboarding-check.tmp.jsonl").exists()
