from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pp_agent.web.server import create_app


def test_attachment_memory_ingest_routes(tmp_path: Path) -> None:
    pytest.importorskip("multipart")
    client = TestClient(create_app(tmp_path))
    uploaded = client.post(
        "/api/sessions/s1/attachments",
        files={"file": ("guide.md", b"# Guide\n\napproval memory", "text/markdown")},
    )
    attachment_id = uploaded.json()["attachment"]["attachment_id"]

    preview = client.post(f"/api/sessions/s1/attachments/{attachment_id}/ingest-memory/preview")
    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True
    assert not (tmp_path / ".pp-agent" / "learning" / "attachment-memory.jsonl").exists()

    chunk_id = client.post("/api/sessions/s1/attachments/search", json={"query": "approval"}).json()["results"][0]["chunk_id"]
    ingest = client.post(
        f"/api/sessions/s1/attachments/{attachment_id}/ingest-memory",
        json={"mode": "selected_chunks", "chunk_ids": [chunk_id], "tags": ["attachment"], "scope": "workspace"},
    )
    assert ingest.status_code == 200
    assert ingest.json()["memory_items_created"] == 1
    assert (tmp_path / ".pp-agent" / "learning" / "attachment-memory.jsonl").exists()
