from fastapi.testclient import TestClient

from pp_agent.observability.schema import TraceRun, TraceRunSummary
from pp_agent.observability.store import TraceStore
from pp_agent.web.server import create_app


def test_trace_routes_list_latest_detail(tmp_path):
    store = TraceStore(tmp_path)
    run = TraceRun(run_id="run-1", session_id="s1", workspace=str(tmp_path), started_at=1.0, status="ok")
    store.append_record("run-1", {"record_type": "run_start", "data": run.model_dump(mode="json")})
    store.append_index(TraceRunSummary(run_id="run-1", session_id="s1", workspace=str(tmp_path), started_at=1.0, status="ok"))
    client = TestClient(create_app(tmp_path))
    assert client.get("/api/traces").json()["runs"][0]["run_id"] == "run-1"
    assert client.get("/api/traces/latest?session_id=s1").json()["run_id"] == "run-1"
    assert client.get("/api/traces/run-1").json()["run"]["run_id"] == "run-1"
    assert client.get("/api/sessions/s1/traces").json()["runs"][0]["run_id"] == "run-1"
