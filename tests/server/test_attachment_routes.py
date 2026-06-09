from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pp_agent.observability import TraceStore
from pp_agent.web.server import create_app


def test_attachment_routes_upload_list_search(tmp_path: Path) -> None:
    pytest.importorskip("multipart")
    app = create_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/sessions/s1/attachments",
        files={
            "file": (
                "note.py",
                b"def run():\n    return 'approval workflow'\n# FULL_ROUTE_CONTENT_SHOULD_NOT_APPEAR",
                "text/x-python",
            )
        },
    )

    assert response.status_code == 200
    attachment_id = response.json()["attachment"]["attachment_id"]
    assert client.get("/api/sessions/s1/attachments").json()["attachments"]
    inspect = client.get(f"/api/sessions/s1/attachments/{attachment_id}").json()
    assert inspect["attachment"]["status"] == "indexed"
    search = client.post("/api/sessions/s1/attachments/search", json={"query": "approval"}).json()
    assert search["results"]
    chunk_id = search["results"][0]["chunk_id"]
    chunk = client.get(f"/api/sessions/s1/attachments/{attachment_id}/chunks/{chunk_id}").json()
    assert "approval" in chunk["text"]
    text = client.post(
        f"/api/sessions/s1/attachments/{attachment_id}/text",
        json={"offset": 0, "max_chars": 1000},
    ).json()
    assert "approval" in text["text"]
    assert text["text_length"] >= text["returned_chars"]
    line_range = client.post(
        f"/api/sessions/s1/attachments/{attachment_id}/range",
        json={"start_line": 1, "end_line": 2},
    ).json()
    assert "def run" in line_range["text"]
    assert client.delete(f"/api/sessions/s1/attachments/{attachment_id}").json()["deleted"] is True
    assert client.get(f"/api/sessions/s1/attachments/{attachment_id}/chunks/{chunk_id}").status_code == 404

    store = TraceStore(tmp_path)
    spans = []
    for summary in store.list_runs(limit=20, session_id="s1"):
        spans.extend(store.read_run(summary.run_id).spans)
    names = {span.name for span in spans}
    assert {"attachment.upload", "attachment.inspect", "attachment.search", "attachment.read_chunk", "attachment.read_text", "attachment.read_range"} <= names
    serialized = "\n".join(span.model_dump_json() for span in spans)
    assert "FULL_ROUTE_CONTENT_SHOULD_NOT_APPEAR" not in serialized
