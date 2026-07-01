from __future__ import annotations

import inspect
import json
from pathlib import Path

from fastapi.testclient import TestClient

from pp_agent.web.coding_api import (
    coding_api_error,
    coding_api_state_to_dict,
    create_coding_api_app,
    mount_coding_routes,
    parse_coding_task_request,
)
from pp_agent.web.coding_service import CodingTaskState


class FakeCodingService:
    def __init__(self) -> None:
        self.start_calls: list[dict] = []
        self.approve_calls: list[tuple[str, str]] = []
        self.reject_calls: list[tuple[str, str, str | None]] = []
        self.states: dict[str, CodingTaskState] = {}

    def start_task(
        self,
        task: str,
        workspace: Path | None = None,
        max_turns: int = 3,
        prepare_only: bool = False,
    ) -> CodingTaskState:
        self.start_calls.append(
            {
                "task": task,
                "workspace": workspace,
                "max_turns": max_turns,
                "prepare_only": prepare_only,
            }
        )
        state = _state(task=task)
        self.states[state.task_id] = state
        return state

    def get_task(self, task_id: str) -> CodingTaskState | None:
        return self.states.get(task_id)

    def get_timeline(self, task_id: str) -> list[dict]:
        state = self.states[task_id]
        return state.timeline_blocks

    def get_pending_approvals(self, task_id: str) -> list[dict]:
        state = self.states[task_id]
        return state.pending_approvals

    def get_validation_plan(self, task_id: str) -> list[dict]:
        state = self.states[task_id]
        return state.validation_commands

    def approve_action(self, task_id: str, token: str) -> CodingTaskState:
        self.approve_calls.append((task_id, token))
        state = self.states.get(task_id)
        if state is None:
            from pp_agent.web.coding_service import CodingTaskNotFound

            raise CodingTaskNotFound("coding task not found")
        if not any(item.get("token") == token for item in state.pending_approvals):
            from pp_agent.web.coding_service import CodingApprovalNotFound

            raise CodingApprovalNotFound("pending approval not found")
        updated = CodingTaskState(
            **{
                **state.__dict__,
                "status": "completed",
                "stop_reason": None,
                "pending_approvals": [],
                "timeline_blocks": [*state.timeline_blocks, {"type": "approval_result", "title": "approved", "status": "succeeded", "summary": "approved", "details": {"payload": "hidden"}}],
            }
        )
        self.states[task_id] = updated
        return updated

    def reject_action(self, task_id: str, token: str, reason: str | None = None) -> CodingTaskState:
        self.reject_calls.append((task_id, token, reason))
        state = self.states.get(task_id)
        if state is None:
            from pp_agent.web.coding_service import CodingTaskNotFound

            raise CodingTaskNotFound("coding task not found")
        if not any(item.get("token") == token for item in state.pending_approvals):
            from pp_agent.web.coding_service import CodingApprovalNotFound

            raise CodingApprovalNotFound("pending approval not found")
        updated = CodingTaskState(
            **{
                **state.__dict__,
                "status": "completed",
                "stop_reason": None,
                "pending_approvals": [],
                "timeline_blocks": [*state.timeline_blocks, {"type": "approval_result", "title": "rejected", "status": "succeeded", "summary": "rejected", "details": {"payload": "hidden"}}],
            }
        )
        self.states[task_id] = updated
        return updated


def _state(*, task: str = "fix failing test") -> CodingTaskState:
    return CodingTaskState(
        task_id="task-123",
        task=task,
        status="awaiting_approval",
        stop_reason="approval_required",
        workflow_summary="controlled workflow summary",
        timeline_blocks=[
            {
                "type": "controlled_tool_loop",
                "title": "Paused for approval",
                "status": "waiting_approval",
                "summary": "Approval required",
                "details": {
                    "stop_reason": "approval_required",
                    "pending_approvals_count": 1,
                    "payload": {"secret": "hidden"},
                    "content_text": "file contents must not leak",
                    "diff": "full diff must not leak",
                },
            }
        ],
        pending_approvals=[
            {
                "token": "tok-1",
                "action_type": "run_shell",
                "tool_name": "run_shell",
                "summary": "Run validation",
                "changed_files": ["tests/web/test_coding_api.py"],
                "command": "python -m pytest tests/web/test_coding_api.py -q",
                "scope_check": {"allowed": True, "reason": "inside validation plan"},
                "payload": {"secret": "hidden"},
                "details": {"content_text": "file contents must not leak"},
            }
        ],
        validation_commands=[
            {
                "command": "python -m pytest tests/web/test_coding_api.py -q",
                "reason": "Focused API validation",
                "priority": "focused",
                "related_paths": ["tests/web/test_coding_api.py"],
                "payload": {"secret": "hidden"},
            }
        ],
        runtime_counters={"tool_calls": 0, "shell_commands": 0, "patch_candidates": 0},
        warnings=["fake service"],
    )


def _client(service: FakeCodingService | None = None, workspace: Path | None = None) -> tuple[TestClient, FakeCodingService]:
    fake = service or FakeCodingService()
    app = create_coding_api_app(fake, workspace=workspace)
    return TestClient(app), fake


def test_post_coding_task_starts_task(tmp_path: Path) -> None:
    client, service = _client(workspace=tmp_path)

    response = client.post(
        "/api/coding/tasks",
        json={"task": "fix failing test", "workspace": str(tmp_path), "max_turns": 5, "prepare_only": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == "task-123"
    assert payload["task"] == "fix failing test"
    assert service.start_calls == [
        {
            "task": "fix failing test",
            "workspace": tmp_path,
            "max_turns": 5,
            "prepare_only": True,
        }
    ]


def test_post_coding_task_defaults(tmp_path: Path) -> None:
    client, service = _client(workspace=tmp_path)

    response = client.post("/api/coding/tasks", json={"task": "inspect repo"})

    assert response.status_code == 200
    assert service.start_calls[0]["workspace"] == tmp_path
    assert service.start_calls[0]["max_turns"] == 3
    assert service.start_calls[0]["prepare_only"] is False


def test_post_coding_task_rejects_empty_task(tmp_path: Path) -> None:
    client, _service = _client(workspace=tmp_path)

    response = client.post("/api/coding/tasks", json={"task": "   "})

    assert response.status_code == 400
    assert response.json() == {"error": "bad_request", "message": "task is required"}


def test_get_coding_task_returns_state() -> None:
    client, service = _client()
    state = _state()
    service.states[state.task_id] = state

    response = client.get(f"/api/coding/tasks/{state.task_id}")

    assert response.status_code == 200
    assert response.json()["workflow_summary"] == "controlled workflow summary"


def test_get_coding_task_404() -> None:
    client, _service = _client()

    response = client.get("/api/coding/tasks/missing")

    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "message": "coding task not found"}


def test_get_timeline_returns_blocks() -> None:
    client, service = _client()
    state = _state()
    service.states[state.task_id] = state

    response = client.get(f"/api/coding/tasks/{state.task_id}/timeline")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == state.task_id
    assert payload["timeline_blocks"][0]["type"] == "controlled_tool_loop"


def test_get_pending_approvals_returns_sanitized_items() -> None:
    client, service = _client()
    state = _state()
    service.states[state.task_id] = state

    response = client.get(f"/api/coding/tasks/{state.task_id}/pending-approvals")

    assert response.status_code == 200
    approval = response.json()["pending_approvals"][0]
    assert approval["token"] == "tok-1"
    assert approval["command"] == "python -m pytest tests/web/test_coding_api.py -q"
    assert "payload" not in approval


def test_get_validation_plan_returns_commands() -> None:
    client, service = _client()
    state = _state()
    service.states[state.task_id] = state

    response = client.get(f"/api/coding/tasks/{state.task_id}/validation-plan")

    assert response.status_code == 200
    command = response.json()["validation_commands"][0]
    assert command["command"] == "python -m pytest tests/web/test_coding_api.py -q"
    assert command["priority"] == "focused"


def test_api_errors_are_json(tmp_path: Path) -> None:
    client, _service = _client(workspace=tmp_path)

    response = client.post("/api/coding/tasks", json={"task": ""})

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert set(response.json()) == {"error", "message"}


def test_api_does_not_return_payload_or_file_content() -> None:
    client, service = _client()
    state = _state()
    service.states[state.task_id] = state

    endpoints = [
        f"/api/coding/tasks/{state.task_id}",
        f"/api/coding/tasks/{state.task_id}/timeline",
        f"/api/coding/tasks/{state.task_id}/pending-approvals",
        f"/api/coding/tasks/{state.task_id}/validation-plan",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        encoded = json.dumps(response.json())
        assert "hidden" not in encoded
        assert "file contents must not leak" not in encoded
        assert "full diff must not leak" not in encoded


def test_api_factory_allows_service_injection() -> None:
    service = FakeCodingService()
    client, injected = _client(service=service)

    response = client.post("/api/coding/tasks", json={"task": "inspect repo"})

    assert response.status_code == 200
    assert injected is service
    assert service.start_calls[0]["task"] == "inspect repo"


def test_api_public_helpers_have_docstrings() -> None:
    for obj in [create_coding_api_app, mount_coding_routes, parse_coding_task_request, coding_api_error, coding_api_state_to_dict]:
        assert inspect.getdoc(obj)


def test_approve_endpoint_returns_updated_state() -> None:
    client, service = _client()
    state = _state()
    service.states[state.task_id] = state

    response = client.post(f"/api/coding/tasks/{state.task_id}/approvals/tok-1/approve", json={"confirm": True})

    assert response.status_code == 200
    assert response.json()["pending_approvals"] == []
    assert service.approve_calls == [(state.task_id, "tok-1")]


def test_reject_endpoint_returns_updated_state() -> None:
    client, service = _client()
    state = _state()
    service.states[state.task_id] = state

    response = client.post(f"/api/coding/tasks/{state.task_id}/approvals/tok-1/reject", json={"reason": "Not needed"})

    assert response.status_code == 200
    assert response.json()["pending_approvals"] == []
    assert service.reject_calls == [(state.task_id, "tok-1", "Not needed")]


def test_approve_endpoint_404_task() -> None:
    client, _service = _client()

    response = client.post("/api/coding/tasks/missing/approvals/tok-1/approve", json={"confirm": True})

    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "message": "coding task not found"}


def test_reject_endpoint_404_token() -> None:
    client, service = _client()
    state = _state()
    service.states[state.task_id] = state

    response = client.post(f"/api/coding/tasks/{state.task_id}/approvals/missing/reject", json={"reason": "No"})

    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "message": "pending approval not found"}


def test_approval_endpoint_errors_are_json() -> None:
    client, service = _client()
    state = _state()
    service.states[state.task_id] = state

    response = client.post(f"/api/coding/tasks/{state.task_id}/approvals/tok-1/approve", json={"confirm": False})

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"error": "bad_request", "message": "confirm must be true to approve action"}


def test_approval_endpoint_does_not_return_payload() -> None:
    client, service = _client()
    state = _state()
    service.states[state.task_id] = state

    response = client.post(f"/api/coding/tasks/{state.task_id}/approvals/tok-1/approve", json={"confirm": True})

    encoded = json.dumps(response.json())
    assert "hidden" not in encoded
    assert "payload" not in encoded
