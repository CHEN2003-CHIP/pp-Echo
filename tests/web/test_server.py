from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_core.types import ModelConfig

from pp_agent.web import server as server_module
from pp_agent.runtime.control_plane import build_runtime_doctor_report
from pp_agent.subagents.worktree import WorktreeManager
from pp_agent.web.server import create_app
from pp_agent.web.session_manager import WebSessionManager
from pp_agent.web.workspaces import WebWorkspaceManager
from pp_agent.tools.registry import ToolRegistry
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.sessions import SessionStore
from pp_agent.storage.models import StoredModelConfig
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.state import AgentEvent

from tests.web.test_session_manager import _factory


def _app(tmp_path: Path, manager: WebSessionManager | None = None):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    active_manager = manager or WebSessionManager(workspace, runtime_factory=_factory)
    workspace_manager = WebWorkspaceManager(
        workspace,
        initial_manager=active_manager,
        session_manager_factory=lambda path: WebSessionManager(path, runtime_factory=_factory),
        state_dir=tmp_path / "state",
    )
    return create_app(workspace, workspace_manager=workspace_manager)


def test_web_api_health_and_session_create(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(_app(tmp_path))

    health = client.get("/api/health")
    created = client.post("/api/sessions")

    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert created.status_code == 200
    assert created.json()["session_id"] == "session-1"


def test_web_api_workspace_status_includes_git_branch(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "-b", "feature/config-ui"], cwd=workspace, check=True)
    client = TestClient(_app(tmp_path))

    response = client.get("/api/workspace/status")

    assert response.status_code == 200
    assert response.json()["name"] == "workspace"
    assert response.json()["git_branch"] == "feature/config-ui"


def test_web_api_prompt_endpoint(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = WebSessionManager(workspace, runtime_factory=_factory)
    client = TestClient(_app(tmp_path, manager))
    session_id = client.post("/api/sessions").json()["session_id"]

    response = client.post(f"/api/sessions/{session_id}/prompt", json={"prompt": "hello"})
    manager.get_handle(session_id)._worker.join(timeout=2)

    assert response.status_code == 200
    assert response.json()["queued"] is False
    assert manager.get_handle(session_id).drain_events()[0]["type"] == "message_delta"


def test_web_api_session_list_uses_lightweight_web_summary(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = SessionStore(workspace / ".pp-agent" / "sessions")
    record = store.create("system prompt", StoredModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="hello")], timestamp=1.0),
        ChatMessage(role="tool", content=[TextPart(text="x" * 500_000)], tool_name="read_file", timestamp=1.5),
    ]
    store.save(record)

    client = TestClient(_app(tmp_path, WebSessionManager(workspace, runtime_factory=_factory)))
    response = client.get("/api/sessions")

    assert response.status_code == 200
    assert response.json()["sessions"][0]["id"] == record.id


def test_web_api_events_polling_endpoint(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = WebSessionManager(workspace, runtime_factory=_factory)
    client = TestClient(_app(tmp_path, manager))
    session_id = client.post("/api/sessions").json()["session_id"]
    response = client.post(f"/api/sessions/{session_id}/prompt", json={"prompt": "hello"})
    manager.get_handle(session_id)._worker.join(timeout=2)

    events = client.get(f"/api/sessions/{session_id}/events")

    assert response.status_code == 200
    assert events.status_code == 200
    assert events.json()["events"][0]["type"] == "message_delta"


def test_web_api_session_timeline_endpoint(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    server_module.bootstrap.timeline_store_for(workspace).append(
        "session-1",
        AgentEvent(type="error", session_id="session-1", message="timed out", is_error=True),
    )
    client = TestClient(_app(tmp_path, WebSessionManager(workspace, runtime_factory=_factory)))

    response = client.get("/api/sessions/session-1/timeline")

    assert response.status_code == 200
    assert response.json()["timeline"][0]["event_type"] == "error"
    assert response.json()["timeline"][0]["message"] == "timed out"


def test_web_api_logs_reads_text_and_jsonl_logs(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    logs_dir = workspace / ".pp-agent" / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "server.log").write_text("2026-05-23T10:00:00 [ERROR] failed to start\n", encoding="utf-8")
    (logs_dir / "agent.jsonl").write_text(
        json.dumps({"timestamp": "2026-05-23T10:01:00", "level": "info", "logger": "agent", "session_id": "s1", "message": "ready"}) + "\n",
        encoding="utf-8",
    )
    client = TestClient(_app(tmp_path, WebSessionManager(workspace, runtime_factory=_factory)))

    response = client.get("/api/logs", params={"level": "error", "search": "failed"})

    assert response.status_code == 200
    assert response.json()["logs"][0]["level"] == "error"
    assert response.json()["logs"][0]["source"] == "server.log"


def test_web_api_logs_include_timeline_entries(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    server_module.bootstrap.timeline_store_for(workspace).append(
        "session-1",
        AgentEvent(type="tool_call", session_id="session-1", message="ran memory_search", tool_name="memory_search"),
    )
    client = TestClient(_app(tmp_path, WebSessionManager(workspace, runtime_factory=_factory)))

    response = client.get("/api/logs", params={"source": "timeline", "session_id": "session-1"})

    assert response.status_code == 200
    assert response.json()["logs"][0]["source"] == "timeline"
    assert response.json()["logs"][0]["message"] == "ran memory_search"


def test_web_api_logs_include_session_jsonl_entries(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_store = SessionStore(workspace / ".pp-agent" / "sessions")
    record = session_store.create("system prompt", StoredModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="hello logs")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="ready")], timestamp=2.0),
    ]
    session_store.save(record)
    client = TestClient(_app(tmp_path, WebSessionManager(workspace, runtime_factory=_factory)))

    response = client.get("/api/logs", params={"source": "session-jsonl", "session_id": record.id})

    assert response.status_code == 200
    assert any(item["source"] == "session-jsonl" for item in response.json()["logs"])
    assert any(item["session_id"] == record.id for item in response.json()["logs"])


def test_web_api_memory_status_search_and_read(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "MEMORY.md").write_text("# Memory\n\nUse focused pytest for web changes.\n", encoding="utf-8")
    client = TestClient(_app(tmp_path, WebSessionManager(workspace, runtime_factory=_factory)))

    status = client.get("/api/memory/status")
    search = client.get("/api/memory/search", params={"query": "focused pytest"})
    read = client.get("/api/memory/file", params={"path": "MEMORY.md"})

    assert status.status_code == 200
    assert status.json()["file_count"] == 1
    assert search.status_code == 200
    assert search.json()["results"][0]["path"] == "MEMORY.md"
    assert read.status_code == 200
    assert "focused pytest" in read.json()["content"]


def test_web_api_capability_config_inventory_and_project_templates(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = TestClient(_app(tmp_path, WebSessionManager(workspace, runtime_factory=_factory)))

    mcp = client.post(
        "/api/mcp/servers",
        json={"name": "fetch", "transport": "stdio", "command": "node", "args": ["server.js"], "protocol": "standard"},
    )
    skill = client.post("/api/skills", json={"name": "repo-helper", "description": "Repository helper", "body": "Use rg first."})
    plugin = client.post("/api/plugins", json={"name": "audit", "description": "Audit plugin", "provides": ["review"]})
    inventory = client.get("/api/capability-config")

    assert mcp.status_code == 200
    assert skill.status_code == 200
    assert plugin.status_code == 200
    assert any(item["name"] == "fetch" for item in inventory.json()["mcp"]["servers"])
    assert any(item["name"] == "repo-helper" for item in inventory.json()["skills"]["items"])
    assert any(item["name"] == "audit" for item in inventory.json()["plugins"]["items"])
    assert (workspace / ".pp-agent" / "mcp.json").exists()
    assert (workspace / ".pp-agent" / "skills" / "repo-helper" / "SKILL.md").exists()
    assert (workspace / ".pp-agent" / "extensions" / "audit" / "EXTENSION.json").exists()


def test_web_api_mcp_validation_error_is_structured(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(_app(tmp_path))

    response = client.post("/api/mcp/servers", json={"name": "bad", "transport": "stdio"})

    assert response.status_code == 400
    assert response.json()["detail"]["errors"][0]["path"] == "command"


def test_web_api_approves_pending_action_token(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    captured = {}

    class ApprovalAgent:
        def __init__(self, session_id: str, subscribers) -> None:
            self.session_id = session_id
            self._subscribers = subscribers
            self.continue_calls = 0

        def continue_(self):
            self.continue_calls += 1
            return []

    def factory(_workspace: Path, session_id, subscribers):
        return ApprovalAgent(session_id or "session-1", subscribers)

    def fake_load(_workspace: Path, token: str) -> dict:
        return {"token": token, "action_type": "write_file", "session_id": "session-1", "details": {"session_id": "session-1"}}

    def fake_approve(workspace: Path, token: str, render: bool = True, runtime=None) -> dict:
        captured.update({"workspace": workspace, "token": token, "render": render, "runtime": runtime})
        return {"token": token, "action_type": "write_file", "session_id": "session-1", "resumed": True, "success": True, "result": "approved", "details": {}}

    manager = WebSessionManager(tmp_path / "workspace", runtime_factory=factory)
    monkeypatch.setattr(server_module, "load_pending_action_or_user_error", fake_load)
    monkeypatch.setattr(server_module, "approve_or_execute_pending_action", fake_approve)
    client = TestClient(_app(tmp_path, manager))
    assert manager.get_active_handle("session-1") is None

    response = client.post("/api/approvals/tok-1/approve")

    assert response.status_code == 200
    assert response.json()["result"] == "approved"
    assert response.json()["resumed"] is True
    assert captured["workspace"] == (tmp_path / "workspace").resolve()
    assert captured["token"] == "tok-1"
    assert captured["render"] is False
    assert captured["runtime"].session_id == "session-1"
    assert captured["runtime"].continue_calls == 0


def test_web_api_approves_non_active_session_and_resumes_once(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    class ApprovalAgent:
        def __init__(self, session_id: str, subscribers) -> None:
            self.session_id = session_id or "session-1"
            self.state = type(
                "State",
                (),
                {
                    "pending_plan_token": None,
                    "pending_tool_calls": [],
                    "queued_messages": [],
                    "turn": type("Turn", (), {"phase": "idle", "model_dump": lambda self, mode="json": {"phase": "idle", "reason": None}})(),
                    "messages": [],
                },
            )()
            self.subscribers = subscribers
            self.recorded: list[dict] = []
            self.continue_calls = 0

        def subscribe(self, callback):
            self.subscribers.append(callback)

        def record_external_approval_result(self, result: dict) -> None:
            self.recorded.append(result)

        def continue_(self):
            self.continue_calls += 1
            return []

    def approval_factory(_workspace: Path, session_id, subscribers):
        return ApprovalAgent(session_id, subscribers)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = SessionStore(workspace / ".pp-agent" / "sessions")
    record = store.create("system prompt", StoredModelConfig())
    registry = ToolRegistry(workspace)
    staged = registry.execute("write_file", {"path": "docs/approval-web.md", "content": "ok\n"})
    payload = server_module.bootstrap.pending_action_store_for(workspace).load(staged.details["token"])
    payload["session_id"] = record.id
    payload.setdefault("details", {})["session_id"] = record.id
    payload["details"]["turn_id"] = "turn-1"
    payload["details"]["tool_call_id"] = "call-1"
    server_module.bootstrap.pending_action_store_for(workspace).save(staged.details["token"], payload)

    manager = WebSessionManager(workspace, runtime_factory=approval_factory)
    workspace_manager = WebWorkspaceManager(
        workspace,
        initial_manager=manager,
        session_manager_factory=lambda path: WebSessionManager(path, runtime_factory=approval_factory),
        state_dir=tmp_path / "state",
    )
    client = TestClient(create_app(workspace, workspace_manager=workspace_manager))

    assert manager.get_active_handle(record.id) is None

    response = client.post(f"/api/approvals/{staged.details['token']}/approve")
    handle = manager.get_active_handle(record.id)

    assert response.status_code == 200
    assert response.json()["resumed"] is True
    assert response.json()["session_id"] == record.id
    assert (workspace / "docs" / "approval-web.md").read_text(encoding="utf-8") == "ok\n"
    assert handle is not None
    assert handle.agent.continue_calls == 1
    assert handle.agent.recorded and handle.agent.recorded[0]["session_id"] == record.id


def test_web_api_approve_pending_action_applies_write_and_removes_token(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    class ApprovalAgent:
        def __init__(self, session_id: str, subscribers) -> None:
            self.session_id = session_id
            self._subscribers = subscribers
            self.continue_calls = 0

        def continue_(self):
            self.continue_calls += 1
            return [{"type": "tool_end"}]

    def factory(_workspace: Path, session_id, subscribers):
        return ApprovalAgent(session_id or "session-1", subscribers)

    def fake_load(_workspace: Path, token: str) -> dict:
        return {"token": token, "action_type": "write_file", "session_id": "session-1", "details": {"session_id": "session-1"}}

    def fake_approve(workspace: Path, token: str, render: bool = True, runtime=None) -> dict:
        return {"token": token, "action_type": "write_file", "session_id": "session-1", "resumed": False, "success": False, "result": "blocked", "details": {}, "workspace": str(workspace)}

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = WebSessionManager(workspace, runtime_factory=factory)
    monkeypatch.setattr(server_module, "load_pending_action_or_user_error", fake_load)
    monkeypatch.setattr(server_module, "approve_or_execute_pending_action", fake_approve)
    client = TestClient(_app(tmp_path, manager))

    response = client.post("/api/approvals/tok-1/approve")
    handle = manager.get_handle("session-1")

    assert response.status_code == 200
    assert response.json()["resumed"] is False
    assert handle.agent.continue_calls == 0


def test_web_api_lists_patch_artifact_with_session_metadata_and_applies_it(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "pp-agent-test"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.email", "pp-agent-test@example.invalid"], cwd=workspace, check=True)
    (workspace / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=workspace, check=True, capture_output=True, text=True)

    manager = WorktreeManager(workspace)
    handle = manager.create(run_id="run-web", agent="code-worker", node_id="code_patch", attempt=1)
    (Path(handle.worktree_path) / "docs").mkdir(parents=True, exist_ok=True)
    (Path(handle.worktree_path) / "docs" / "worktree-smoke-web.md").write_text(
        "pp-Echo isolated worktree smoke test\n",
        encoding="utf-8",
    )
    artifact = manager.finalize(handle)
    assert artifact is not None
    payload = manager.stage_pending_artifact(
        artifact,
        workspace / ".pp-agent" / "pending-edits",
        session_id="session-1",
        workflow="code_change",
    )

    client = TestClient(_app(tmp_path, WebSessionManager(workspace, runtime_factory=_factory)))
    approvals = client.get("/api/approvals")
    response = client.post(f"/api/approvals/{payload['token']}/approve")
    refreshed = client.get("/api/approvals")

    item = next(item for item in approvals.json()["items"] if item["token"] == payload["token"])
    assert item["details"]["session_id"] == "session-1"
    assert item["details"]["workflow"] == "code_change"
    assert item["details"]["changed_paths"] == ["docs/worktree-smoke-web.md"]
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["details"]["changed_paths"] == ["docs/worktree-smoke-web.md"]
    assert (workspace / "docs" / "worktree-smoke-web.md").read_text(encoding="utf-8") == "pp-Echo isolated worktree smoke test\n"
    assert payload["token"] not in refreshed.json()["tokens"]


def test_web_api_rejects_pending_action_token(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    captured = {}

    def fake_reject(workspace: Path, token: str, render: bool = True) -> dict:
        captured.update({"workspace": workspace, "token": token, "render": render})
        return {"token": token, "result": "rejected"}

    manager = WebSessionManager(tmp_path / "workspace", runtime_factory=_factory)
    monkeypatch.setattr(server_module, "reject_pending_action_by_token", fake_reject)
    client = TestClient(_app(tmp_path, manager))

    response = client.post("/api/approvals/tok-1/reject")

    assert response.status_code == 200
    assert response.json()["result"] == "rejected"
    assert captured == {"workspace": (tmp_path / "workspace").resolve(), "token": "tok-1", "render": False}


def test_web_api_runtime_report_surfaces_patch_artifact_findings(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = server_module.bootstrap.pending_action_store_for(workspace)
    store.stage(
        action_type="apply_patch_artifact",
        target_path=workspace / ".pp-agent" / "artifacts" / "missing.patch",
        details={
            "session_id": "session-1",
            "workflow": "code_change",
            "artifact_id": "artifact-1",
            "changed_paths": ["docs/worktree-smoke-web.md"],
        },
    )
    client = TestClient(_app(tmp_path, WebSessionManager(workspace, runtime_factory=_factory)))

    response = client.get("/api/runtime/report")

    assert response.status_code == 200
    assert response.json()["status"] == "warning"
    assert response.json()["summary"]["pending_artifact_count"] == 1
    assert any(item["kind"] == "missing_artifact_file" for item in response.json()["findings"])


def test_runtime_doctor_report_flags_missing_patch_artifact_file(tmp_path: Path) -> None:
    session_store = SessionStore(tmp_path / "sessions")
    record = session_store.create("system", ModelConfig())
    session_store.save(record)
    pending_store = PendingActionStore(tmp_path / "pending")
    payload = pending_store.stage(
        action_type="apply_patch_artifact",
        target_path=tmp_path / "artifacts" / "missing.patch",
        details={
            "session_id": record.id,
            "workflow": "code_change",
            "artifact_id": "artifact-1",
            "changed_paths": ["docs/worktree-smoke-web.md"],
        },
    )

    report = build_runtime_doctor_report(
        tmp_path,
        session_store=session_store,
        pending_store=pending_store,
    )

    assert report["status"] == "warning"
    assert report["summary"]["pending_artifact_count"] == 1
    assert report["findings"][0]["kind"] == "missing_artifact_file"
    assert report["findings"][0]["token"] == payload["token"]


def test_runtime_doctor_report_flags_orphaned_planner_token(tmp_path: Path) -> None:
    session_store = SessionStore(tmp_path / "sessions")
    pending_store = PendingActionStore(tmp_path / "pending")
    payload = pending_store.stage(
        action_type="planner_approval",
        details={"session_id": "missing-session"},
    )

    report = build_runtime_doctor_report(
        tmp_path,
        session_store=session_store,
        pending_store=pending_store,
    )

    assert report["status"] == "warning"
    assert any(
        finding["kind"] == "orphaned_pending_token" and finding["token"] == payload["token"]
        for finding in report["findings"]
    )


def test_web_api_workspace_open_requires_confirmation_then_switches(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(_app(tmp_path))
    other = tmp_path / "other"
    other.mkdir()

    preview = client.post("/api/workspaces/open", json={"path": str(other), "confirmed": False})
    switched = client.post("/api/workspaces/open", json={"path": str(other), "confirmed": True})
    workspace = client.get("/api/workspace")

    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True
    assert switched.status_code == 200
    assert switched.json()["requires_confirmation"] is False
    assert workspace.json()["path"] == str(other.resolve())


def test_web_api_workspace_open_rejects_missing_path(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(_app(tmp_path))

    response = client.post("/api/workspaces/open", json={"path": str(tmp_path / "missing"), "confirmed": True})

    assert response.status_code == 400
