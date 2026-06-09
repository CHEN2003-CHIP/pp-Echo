from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pp_agent.web.server import create_app
from pp_agent.server.error_logging import write_server_error_log


def test_server_error_log_helper_writes_traceback(tmp_path: Path) -> None:
    try:
        raise RuntimeError("attachment upload failed")
    except RuntimeError as exc:
        payload = write_server_error_log(tmp_path, exc)

    log_path = Path(payload["log_path"])
    text = log_path.read_text(encoding="utf-8")
    assert payload["error_id"] in text
    assert "attachment upload failed" in text
    assert "Traceback" in text


def test_unhandled_web_errors_are_written_to_workspace_log(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("multipart")
    app = create_app(tmp_path)

    def boom(_workspace: Path) -> str:
        raise RuntimeError("upload parser exploded")

    monkeypatch.setattr("pp_agent.web.server._git_branch", boom)

    response = TestClient(app, raise_server_exceptions=False).get("/api/workspace/status")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["error_id"].startswith("err_")
    log_path = Path(detail["log_path"])
    assert log_path.exists()
    text = log_path.read_text(encoding="utf-8")
    assert detail["error_id"] in text
    assert "upload parser exploded" in text
    assert "Traceback" in text
