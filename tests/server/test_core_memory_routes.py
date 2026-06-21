from __future__ import annotations

from fastapi.testclient import TestClient

from pp_agent.web.server import create_app


def test_core_memory_routes_lifecycle_and_audit(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))

    proposed = client.post(
        "/api/memory/core/propose",
        json={"content": "Use pytest for focused tests.", "type": "workflow", "reason": "test"},
    )
    assert proposed.status_code == 200
    memory = proposed.json()["memory"]
    assert memory["status"] == "pending"

    pending = client.get("/api/memory/core/pending")
    assert pending.status_code == 200
    assert [item["id"] for item in pending.json()["pending"]] == [memory["id"]]

    approved = client.post(f"/api/memory/core/{memory['id']}/approve", json={"actor": "tester", "reason": "verified"})
    assert approved.status_code == 200
    assert approved.json()["memory"]["status"] == "active"

    snapshot = client.get("/api/memory/core/snapshot")
    assert snapshot.status_code == 200
    assert "Use pytest for focused tests." in snapshot.json()["snapshot"]

    audit = client.get("/api/memory/core/audit", params={"memory_id": memory["id"]})
    assert audit.status_code == 200
    assert [entry["action"] for entry in audit.json()["audit"]][:2] == ["approve", "propose"]


def test_core_memory_reject_route_keeps_memory_out_of_snapshot(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    memory = client.post("/api/memory/core/propose", json={"content": "Temporary note."}).json()["memory"]

    rejected = client.post(f"/api/memory/core/{memory['id']}/reject", json={"actor": "tester", "reason": "not durable"})

    assert rejected.status_code == 200
    assert rejected.json()["memory"]["status"] == "rejected"
    assert "Temporary note." not in client.get("/api/memory/core/snapshot").json()["snapshot"]


def test_core_memory_merge_and_provider_routes(tmp_path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir()
    (project_dir / "config.json").write_text(
        '{"memory":{"core_memory":{"require_approval":false,"dedupe":{"enabled":false}}}}',
        encoding="utf-8",
    )
    client = TestClient(create_app(tmp_path))
    first = client.post("/api/memory/core/propose", json={"content": "Use pytest for focused tests.", "type": "workflow"}).json()["memory"]
    second = client.post("/api/memory/core/propose", json={"content": "Use pytest for focused tests.", "type": "workflow"}).json()["memory"]

    preview = client.get("/api/memory/core/merge-preview")
    applied = client.post("/api/memory/core/merge-apply", json={"actor": "tester", "reason": "dedupe"})
    provider = client.get("/api/memory/core/provider/status")

    assert preview.status_code == 200
    assert preview.json()["mergeable_group_count"] == 1
    assert applied.status_code == 200
    assert len(applied.json()["generated"]) == 1
    assert applied.json()["generated"][0]["memory"]["status"] == "pending"
    assert set(applied.json()["generated"][0]["memory"]["metadata"]["auto_archive_on_approve_ids"]) == {first["id"], second["id"]}
    assert provider.status_code == 200
    assert provider.json()["provider"] == "local"
