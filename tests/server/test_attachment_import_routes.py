from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pp_agent.web.server import create_app


def test_attachment_import_routes_stage_pending_action(tmp_path: Path) -> None:
    pytest.importorskip("multipart")
    client = TestClient(create_app(tmp_path))
    uploaded = client.post(
        "/api/sessions/s1/attachments",
        files={"file": ("spec.md", b"# Spec\n\napproval import", "text/markdown")},
    )
    attachment_id = uploaded.json()["attachment"]["attachment_id"]

    preview = client.post(
        f"/api/sessions/s1/attachments/{attachment_id}/import/preview",
        json={"target_path": "docs/spec.md"},
    )
    assert preview.status_code == 200
    assert preview.json()["requires_approval"] is True
    assert not (tmp_path / "docs" / "spec.md").exists()

    staged = client.post(
        f"/api/sessions/s1/attachments/{attachment_id}/import",
        json={"target_path": "docs/spec.md"},
    )
    assert staged.status_code == 200
    assert staged.json()["staged"] is True
    assert staged.json()["token"]
    assert not (tmp_path / "docs" / "spec.md").exists()
