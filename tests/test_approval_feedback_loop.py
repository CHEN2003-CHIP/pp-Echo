from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pp_agent.cli.commands.approvals as approvals
from pp_agent.llm import ModelConfig
from pp_agent.cli.commands.approvals import approve_or_execute_pending_action, reject_pending_action
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.runtime import AgentRuntime, ExecutePersistedActionResult, ExecutePersistedActionStatus
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.sessions import SessionEvidenceReference, SessionStore
from pp_agent.tools.registry import ToolRegistry


class NoopLLMClient:
    def __init__(self) -> None:
        self.calls = 0
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        self.calls += 1
        yield {"text": "ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def build_agent(tmp_path: Path) -> AgentRuntime:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentRuntime(
        llm_client=NoopLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
    )
    agent.restore_session_record(record)
    return agent


def stage_tool_result(agent: AgentRuntime, tool_name: str, arguments: dict) -> str:
    agent.state.messages.append(ChatMessage(role="user", content=[TextPart(text=f"stage {tool_name}")], timestamp=0.0))
    result = agent.tool_registry.execute(tool_name, arguments)
    result.tool_call_id = "call-1"
    agent._attach_session_to_pending_action(result)
    agent.state.messages.append(result.as_chat_message())
    return str(result.details["token"])


class FakeApprovalRuntime:
    def __init__(self, session_id: str, result: ExecutePersistedActionResult) -> None:
        self.session_id = session_id
        self.result = result
        self.execute_calls = 0
        self.continue_calls = 0

    def execute_and_persist_approved_action(self, **kwargs) -> ExecutePersistedActionResult:
        self.execute_calls += 1
        assert kwargs["session_id"] == self.session_id
        return self.result

    def continue_(self):
        self.continue_calls += 1
        return [object()]

    def record_external_approval_result(self, _result):
        raise AssertionError("CLI must not call record_external_approval_result")


def stage_fake_pending(workspace: Path, *, session_id: str = "session-1", action_type: str = "write_file") -> str:
    payload = PendingActionStore(workspace / ".pp-agent" / "pending-edits").stage(
        action_type=action_type,
        details={"session_id": session_id, "tool_call_id": "call-1"},
        session_id=session_id,
        tool_call_id="call-1",
    )
    return str(payload["token"])


def fake_evidence(session_id: str, action_id: str) -> SessionEvidenceReference:
    return SessionEvidenceReference(
        session_id=session_id,
        message_id="message-1",
        correlation_kind="external_tool_result",
        correlation_id=action_id,
        action_id=action_id,
        result_digest="digest-1",
        tool_name="write_file",
        completed_at=1.0,
    )


def test_external_approval_result_is_recorded_and_resumed_for_staged_write(tmp_path: Path) -> None:
    agent = build_agent(tmp_path)
    token = stage_tool_result(agent, "write_file", {"path": "a.txt", "content": "hi"})

    assert "approval is still pending" in agent._latest_pending_action_note(agent.state)

    result = approve_or_execute_pending_action(tmp_path, token, render=False, runtime=agent)

    assert result["resumed"] is True
    assert result["session_id"] == agent.session_id
    assert result["event_count"] > 0
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hi"
    assert any(
        message.role == "tool"
        and bool(message.metadata.get("tool_details", {}).get("external_approval_result"))
        for message in agent.state.messages
    )
    assert agent._latest_pending_action_note(agent.state) == ""
    assert agent.llm_client.calls >= 1


def test_shell_failure_details_are_visible_after_external_approval(tmp_path: Path) -> None:
    agent = build_agent(tmp_path)
    token = stage_tool_result(
        agent,
        "run_shell",
        {"command": 'Write-Output "stdout"; Write-Error "stderr"; exit 1'},
    )

    result = approve_or_execute_pending_action(tmp_path, token, render=False, runtime=agent)

    assert result["resumed"] is True
    assert result["success"] is False
    assert result["details"]["command_failed"] is True
    assert result["details"]["exit_code"] == 1
    assert "stdout:" in result["result"]
    assert "stderr:" in result["result"]
    assert any(
        message.role == "tool"
        and bool(message.metadata.get("tool_details", {}).get("external_approval_result"))
        and message.metadata.get("tool_details", {}).get("command_failed") is True
        for message in agent.state.messages
    )


def test_cli_approve_uses_runtime_boundary_without_direct_registry_execution(tmp_path: Path, monkeypatch) -> None:
    token = stage_fake_pending(tmp_path)
    runtime = FakeApprovalRuntime(
        "session-1",
        ExecutePersistedActionResult(
            status=ExecutePersistedActionStatus.PERSISTED,
            evidence=fake_evidence("session-1", token),
            action_id=token,
            session_id="session-1",
            result="ok",
            success=True,
            details={"path": "a.txt"},
            persisted=True,
        ),
    )

    def fail_create_registry(*_args, **_kwargs):
        raise AssertionError("CLI must not directly create a registry to approve actions")

    monkeypatch.setattr(approvals, "create_tool_registry", fail_create_registry)

    result = approve_or_execute_pending_action(tmp_path, token, render=False, runtime=runtime)  # type: ignore[arg-type]

    assert runtime.execute_calls == 1
    assert runtime.continue_calls == 1
    assert result["status"] == ExecutePersistedActionStatus.PERSISTED
    assert result["result"] == "ok"
    assert result["details"] == {"path": "a.txt"}
    assert result["resumed"] is True


def test_cli_approve_repeated_already_persisted_is_noop_resume(tmp_path: Path) -> None:
    token = stage_fake_pending(tmp_path)
    runtime = FakeApprovalRuntime(
        "session-1",
        ExecutePersistedActionResult(
            status=ExecutePersistedActionStatus.ALREADY_PERSISTED,
            evidence=fake_evidence("session-1", token),
            action_id=token,
            session_id="session-1",
            result="already persisted",
            success=True,
            persisted=True,
        ),
    )

    result = approve_or_execute_pending_action(tmp_path, token, render=False, runtime=runtime)  # type: ignore[arg-type]

    assert runtime.execute_calls == 1
    assert runtime.continue_calls == 1
    assert result["status"] == ExecutePersistedActionStatus.ALREADY_PERSISTED
    assert result["resumed"] is True


def test_cli_approve_uncertain_and_persistence_failed_do_not_resume(tmp_path: Path) -> None:
    for status in [ExecutePersistedActionStatus.EXECUTION_UNCERTAIN, ExecutePersistedActionStatus.PERSISTENCE_FAILED]:
        workspace = tmp_path / status
        token = stage_fake_pending(workspace)
        runtime = FakeApprovalRuntime(
            "session-1",
            ExecutePersistedActionResult(
                status=status,
                action_id=token,
                session_id="session-1",
                reason="fail_closed",
                success=False,
            ),
        )

        result = approve_or_execute_pending_action(workspace, token, render=False, runtime=runtime)  # type: ignore[arg-type]

        assert runtime.execute_calls == 1
        assert runtime.continue_calls == 0
        assert result["status"] == status
        assert result["result"] == "fail_closed"
        assert result["resumed"] is False


def test_cli_approve_terminal_statuses_do_not_resume(tmp_path: Path) -> None:
    statuses = [
        ExecutePersistedActionStatus.APPROVAL_STILL_PENDING,
        ExecutePersistedActionStatus.REJECTED,
        ExecutePersistedActionStatus.EXPIRED,
        ExecutePersistedActionStatus.IDENTITY_MISMATCH,
        ExecutePersistedActionStatus.AMBIGUOUS_CORRUPT,
    ]
    for status in statuses:
        workspace = tmp_path / status
        token = stage_fake_pending(workspace)
        runtime = FakeApprovalRuntime(
            "session-1",
            ExecutePersistedActionResult(status=status, action_id=token, session_id="session-1", reason=status),
        )

        result = approve_or_execute_pending_action(workspace, token, render=False, runtime=runtime)  # type: ignore[arg-type]

        assert runtime.execute_calls == 1
        assert runtime.continue_calls == 0
        assert result["status"] == status
        assert result["resumed"] is False


def test_cli_approve_failed_persisted_result_resumes_once(tmp_path: Path) -> None:
    token = stage_fake_pending(tmp_path)
    runtime = FakeApprovalRuntime(
        "session-1",
        ExecutePersistedActionResult(
            status=ExecutePersistedActionStatus.FAILED,
            evidence=fake_evidence("session-1", token),
            action_id=token,
            session_id="session-1",
            result="tool failed",
            success=False,
            details={"exit_code": 1, "command_failed": True},
            persisted=True,
        ),
    )

    result = approve_or_execute_pending_action(tmp_path, token, render=False, runtime=runtime)  # type: ignore[arg-type]

    assert runtime.execute_calls == 1
    assert runtime.continue_calls == 1
    assert result["status"] == ExecutePersistedActionStatus.FAILED
    assert result["success"] is False
    assert result["details"]["exit_code"] == 1


def test_cli_approve_output_does_not_expose_token_or_raw_metadata(tmp_path: Path, monkeypatch) -> None:
    token = stage_fake_pending(tmp_path)
    runtime = FakeApprovalRuntime(
        "session-1",
        ExecutePersistedActionResult(
            status=ExecutePersistedActionStatus.PERSISTED,
            evidence=fake_evidence("session-1", token),
            action_id=token,
            session_id="session-1",
            result="bounded result",
            success=True,
            details={"path": "a.txt"},
            persisted=True,
        ),
    )
    lines: list[str] = []
    monkeypatch.setattr(approvals.console, "print", lambda *args, **_kwargs: lines.append(" ".join(str(arg) for arg in args)))

    result = approve_or_execute_pending_action(tmp_path, token, render=True, runtime=runtime)  # type: ignore[arg-type]
    rendered = "\n".join(lines)

    assert token not in rendered
    assert "metadata" not in rendered
    assert "nonce" not in rendered
    assert token not in json.dumps(result, ensure_ascii=False)


def test_rejected_staged_action_consumes_pending_note(tmp_path: Path) -> None:
    agent = build_agent(tmp_path)
    token = stage_tool_result(agent, "write_file", {"path": "a.txt", "content": "hi"})

    assert "approval is still pending" in agent._latest_pending_action_note(agent.state)

    result = reject_pending_action(tmp_path, token, render=False, runtime=agent)

    assert result["resumed"] is True
    assert result["session_id"] == agent.session_id
    assert any(
        message.role == "tool"
        and message.metadata.get("tool_details", {}).get("approval_status") == "rejected"
        for message in agent.state.messages
    )
    assert agent._latest_pending_action_note(agent.state) == ""
