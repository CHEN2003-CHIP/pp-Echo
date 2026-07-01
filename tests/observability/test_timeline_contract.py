from __future__ import annotations

from pathlib import Path

from pp_agent.coding.impact import ChangeImpact
from pp_agent.coding.scope import TaskScope
from pp_agent.coding.enforcement import ScopeEnforcementResult
from pp_agent.coding.testing import ValidationCommand, ValidationPlan
from pp_agent.observability import (
    AgentActionGroup,
    ApprovalCard,
    AgentStep,
    AssistantMessageBlock,
    DiffArtifact,
    FileOperation,
    RunSummary,
    TestRunResult,
    TimelineBlock,
    action_group_to_block,
    approval_card_from_pending_action,
    approval_card_to_block,
    agent_steps_to_action_group,
    assistant_message_to_block,
    change_impact_to_block,
    change_impact_to_timeline_step,
    diff_artifacts_from_structured_changes,
    file_operations_from_structured_changes,
    from_runtime_event,
    run_summary_from_items,
    run_summary_to_block,
    scope_enforcement_to_block,
    scope_enforcement_to_timeline_step,
    repository_analysis_to_block,
    repository_analysis_to_timeline_step,
    task_plan_to_block,
    task_plan_to_timeline_step,
    task_scope_to_block,
    task_scope_to_timeline_step,
    test_result_to_block,
    timeline_to_jsonable,
    validation_plan_to_block,
    validation_plan_to_timeline_step,
)
from pp_agent.runtime.state import AgentEvent


def test_agent_step_serializes_to_json() -> None:
    step = AgentStep(
        id="step-1",
        run_id="run-1",
        parent_id=None,
        type="plan",
        status="running",
        title="Plan work",
        summary="break the task into steps",
        details={"a": 1},
        artifact_ids=["artifact-1"],
    )

    payload = timeline_to_jsonable(step)
    assert payload["id"] == "step-1"
    assert payload["details"]["a"] == 1
    assert payload["artifact_ids"] == ["artifact-1"]


def test_file_operation_serializes_to_json() -> None:
    payload = timeline_to_jsonable(FileOperation(path="docs/a.md", operation="modified", status="succeeded", lines_added=3, lines_deleted=1))

    assert payload == {
        "path": "docs/a.md",
        "operation": "modified",
        "status": "succeeded",
        "lines_added": 3,
        "lines_deleted": 1,
        "summary": None,
    }


def test_diff_artifact_serializes_to_json() -> None:
    artifact = diff_artifacts_from_structured_changes(
        [
            {
                "id": "diff-1",
                "path": "src/app.py",
                "change_type": "modified",
                "content_text": "print('hello')\n",
                "old_digest": "old",
                "new_digest": "new",
            }
        ]
    )[0]

    payload = timeline_to_jsonable(artifact)
    assert payload["file_path"] == "src/app.py"
    assert payload["hunks"][0]["lines"][0]["type"] == "added"


def test_approval_card_serializes_to_json() -> None:
    card = approval_card_from_pending_action(
        {
            "token": "tok-1",
            "action_type": "run_shell",
            "command": "python -m pytest",
            "created_at": 1_700_000_000,
            "details": {"changed_files": ["README.md"], "risk_level": "medium"},
        }
    )

    payload = timeline_to_jsonable(card)
    assert payload["token"] == "tok-1"
    assert payload["command"] == "python -m pytest"
    assert payload["changed_files"] == ["README.md"]


def test_assistant_message_block_serializes_to_json() -> None:
    block = assistant_message_to_block(id="msg-1", run_id="run-1", content="check project context", created_at="2026-06-29T10:00:00")

    payload = timeline_to_jsonable(block)
    assert payload["type"] == "assistant_message"
    assert payload["content"] == "check project context"
    assert payload["related_step_ids"] == []


def test_agent_action_group_serializes_to_json() -> None:
    group = agent_steps_to_action_group(
        [
            AgentStep(id="s1", run_id="run-1", parent_id=None, type="tool_call", status="running", title="tool", details={"tool_name": "run_shell", "tool_call_id": "call-1"}),
            AgentStep(id="s2", run_id="run-1", parent_id=None, type="file_edit", status="succeeded", title="edit", details={"change_type": "modified"}),
            AgentStep(id="s3", run_id="run-1", parent_id=None, type="approval_required", status="waiting_approval", title="approve", details={}),
        ],
        id="group-1",
        run_id="run-1",
        message_id="msg-1",
    )

    payload = timeline_to_jsonable(group)
    assert payload["command_count"] == 1
    assert payload["file_edit_count"] == 1
    assert payload["approval_count"] == 1
    assert payload["title"] == "Waiting for approval"


def test_timeline_block_serializes_to_json() -> None:
    group = AgentActionGroup(
        id="group-1",
        run_id="run-1",
        message_id="msg-1",
        title="Ran 3 commands",
        status="running",
    )
    block = action_group_to_block(group)

    payload = timeline_to_jsonable(block)
    assert payload["type"] == "action_group"
    assert payload["title"] == "Ran 3 commands"


def test_agent_steps_to_action_group_counts_commands() -> None:
    group = agent_steps_to_action_group(
        [
            AgentStep(id="s1", run_id="run-1", parent_id=None, type="tool_call", status="running", title="tool", details={"tool_name": "run_shell"}),
            AgentStep(id="s2", run_id="run-1", parent_id=None, type="tool_call", status="running", title="tool", details={"tool_name": "read_file"}),
            AgentStep(id="s3", run_id="run-1", parent_id=None, type="tool_call", status="running", title="tool", details={"tool_name": "write_file", "change_type": "created"}),
        ],
        id="group-2",
        run_id="run-1",
    )

    assert group.command_count == 1
    assert group.file_read_count == 1
    assert group.file_create_count == 1


def test_structured_changes_to_action_group_counts_file_operations() -> None:
    group = agent_steps_to_action_group(
        [
            AgentStep(id="s1", run_id="run-1", parent_id=None, type="file_read", status="succeeded", title="read", details={"tool_name": "read_file"}),
            AgentStep(id="s2", run_id="run-1", parent_id=None, type="file_edit", status="succeeded", title="edit", details={"change_type": "modified"}),
            AgentStep(id="s3", run_id="run-1", parent_id=None, type="file_create", status="succeeded", title="create", details={"change_type": "created"}),
            AgentStep(id="s4", run_id="run-1", parent_id=None, type="file_delete", status="succeeded", title="delete", details={"change_type": "deleted"}),
        ],
        id="group-3",
        run_id="run-1",
    )

    assert group.file_read_count == 1
    assert group.file_edit_count == 1
    assert group.file_create_count == 1
    assert group.file_delete_count == 1


def test_action_group_title_for_commands() -> None:
    group = agent_steps_to_action_group(
        [AgentStep(id="s1", run_id="run-1", parent_id=None, type="tool_call", status="running", title="tool", details={"tool_name": "run_shell"})],
        id="group-4",
        run_id="run-1",
    )

    assert group.title == "Ran 1 command"


def test_action_group_title_for_file_edits() -> None:
    group = agent_steps_to_action_group(
        [AgentStep(id="s1", run_id="run-1", parent_id=None, type="file_edit", status="running", title="edit", details={"change_type": "modified"})],
        id="group-5",
        run_id="run-1",
    )

    assert group.title == "Editing 1 file"


def test_action_group_title_for_waiting_approval() -> None:
    group = agent_steps_to_action_group(
        [AgentStep(id="s1", run_id="run-1", parent_id=None, type="approval_required", status="waiting_approval", title="approve", details={})],
        id="group-6",
        run_id="run-1",
    )

    assert group.title == "Waiting for approval"


def test_assistant_message_and_action_group_can_interleave_as_blocks() -> None:
    message = assistant_message_to_block(id="msg-1", run_id="run-1", content="I will inspect the project context first.", related_step_ids=["s1"])
    group = action_group_to_block(
        agent_steps_to_action_group(
            [AgentStep(id="s1", run_id="run-1", parent_id=None, type="tool_call", status="running", title="tool", details={"tool_name": "run_shell"})],
            id="group-7",
            run_id="run-1",
            message_id="msg-1",
        )
    )

    assert [message.type, group.type] == ["assistant_message", "action_group"]
    assert message.related_step_ids == ["s1"]


def test_public_timeline_models_have_docstrings() -> None:
    assert AgentStep.__doc__
    assert FileOperation.__doc__
    assert DiffArtifact.__doc__
    assert ApprovalCard.__doc__
    assert TestRunResult.__doc__
    assert RunSummary.__doc__
    assert AssistantMessageBlock.__doc__
    assert AgentActionGroup.__doc__
    assert TimelineBlock.__doc__


def test_public_timeline_helpers_have_docstrings() -> None:
    assert from_runtime_event.__doc__
    assert file_operations_from_structured_changes.__doc__
    assert diff_artifacts_from_structured_changes.__doc__
    assert approval_card_from_pending_action.__doc__
    assert assistant_message_to_block.__doc__
    assert agent_steps_to_action_group.__doc__
    assert action_group_to_block.__doc__
    assert approval_card_to_block.__doc__
    assert test_result_to_block.__doc__
    assert run_summary_from_items.__doc__
    assert run_summary_to_block.__doc__
    assert repository_analysis_to_timeline_step.__doc__
    assert repository_analysis_to_block.__doc__
    assert task_plan_to_timeline_step.__doc__
    assert task_plan_to_block.__doc__
    assert task_scope_to_timeline_step.__doc__
    assert task_scope_to_block.__doc__
    assert change_impact_to_timeline_step.__doc__
    assert change_impact_to_block.__doc__
    assert validation_plan_to_timeline_step.__doc__
    assert validation_plan_to_block.__doc__
    assert scope_enforcement_to_timeline_step.__doc__
    assert scope_enforcement_to_block.__doc__


def test_tool_call_event_to_timeline_step() -> None:
    step = from_runtime_event(
        AgentEvent(
            type="tool_call",
            event_id="evt-1",
            run_id="run-1",
            tool_name="read_file",
            message="Reading README",
            details={"summary": "Read README", "artifact_ids": ["artifact-1"]},
        )
    )

    assert step.type == "tool_call"
    assert step.title == "Tool call: read_file"
    assert step.artifact_ids == ["artifact-1"]


def test_policy_decision_event_to_timeline_step() -> None:
    step = from_runtime_event(
        AgentEvent(
            type="tool_policy_decision",
            event_id="evt-2",
            run_id="run-1",
            details={"tool_name": "run_shell", "decision": "ask", "summary": "Needs approval"},
        )
    )

    assert step.type == "tool_policy_decision"
    assert step.status == "waiting_approval"
    assert step.title == "Policy decision run_shell ask"


def test_structured_changes_to_file_operations_added_modified_deleted() -> None:
    ops = file_operations_from_structured_changes(
        [
            {"path": "a.txt", "change_type": "created", "lines_added": 2},
            {"path": "b.txt", "change_type": "modified", "lines_added": 1, "lines_deleted": 1},
            {"path": "c.txt", "change_type": "deleted", "lines_deleted": 4},
        ]
    )

    assert [op.operation for op in ops] == ["created", "modified", "deleted"]
    assert ops[2].status == "deleted"


def test_pending_patch_candidate_to_approval_card() -> None:
    card = approval_card_from_pending_action(
        {
            "token": "tok-2",
            "action_type": "apply_patch_candidate",
            "details": {
                "changed_files": ["src/app.py"],
                "diff_artifact_ids": ["diff-1"],
                "summary": "Apply patch",
            },
        }
    )

    assert card.action_type == "apply_patch_candidate"
    assert card.changed_files == ["src/app.py"]
    assert card.diff_artifact_ids == ["diff-1"]


def test_approval_card_preserves_scope_check_details() -> None:
    card = approval_card_from_pending_action(
        {
            "token": "tok-scope",
            "action_type": "apply_patch_candidate",
            "details": {
                "scope_check": {
                    "allowed": False,
                    "action": "apply_patch",
                    "failed_path": ".env",
                }
            },
        }
    )

    assert card.details["scope_check"]["allowed"] is False
    assert card.details["scope_check"]["failed_path"] == ".env"


def test_pending_shell_action_to_approval_card() -> None:
    card = approval_card_from_pending_action(
        {
            "token": "tok-3",
            "action_type": "run_shell",
            "details": {"command": "pytest -q", "risk_level": "high"},
        }
    )

    assert card.title == "Run shell command"
    assert card.command == "pytest -q"
    assert card.risk_level == "high"


def test_task_scope_to_timeline_step_contract() -> None:
    scope = TaskScope(task="fix", allowed_paths=["src/**"], disallowed_paths=[".env"], summary_text="Task Scope:\n- Task: fix")

    payload = timeline_to_jsonable(task_scope_to_timeline_step(scope))

    assert payload["type"] == "task_scope"
    assert payload["details"]["allowed_paths"] == ["src/**"]


def test_task_scope_to_block_contract() -> None:
    scope = TaskScope(task="fix", allowed_paths=["src/**"], disallowed_paths=[".env"], summary_text="Task Scope:\n- Task: fix")

    payload = timeline_to_jsonable(task_scope_to_block(scope))

    assert payload["type"] == "task_scope"
    assert payload["title"] == "Generated task scope"


def test_change_impact_to_timeline_contract() -> None:
    impact = ChangeImpact(
        changed_paths=["src/pp_agent/coding/impact.py"],
        impacted_modules=["coding"],
        impacted_tests=["tests/coding"],
        risk_level="medium",
        summary_text="Change Impact:\n- Risk: medium",
    )

    step_payload = timeline_to_jsonable(change_impact_to_timeline_step(impact))
    block_payload = timeline_to_jsonable(change_impact_to_block(impact))

    assert step_payload["type"] == "change_impact"
    assert step_payload["details"]["impacted_tests"] == ["tests/coding"]
    assert block_payload["title"] == "Analyzed change impact"


def test_validation_plan_to_timeline_contract() -> None:
    plan = ValidationPlan(
        commands=[ValidationCommand(command="python -m pytest tests/coding -q", priority="focused")],
        risk_level="medium",
        summary_text="Validation Plan:\n- Risk: medium",
    )

    step_payload = timeline_to_jsonable(validation_plan_to_timeline_step(plan))
    block_payload = timeline_to_jsonable(validation_plan_to_block(plan))

    assert step_payload["type"] == "validation_plan"
    assert step_payload["details"]["commands"][0]["command"] == "python -m pytest tests/coding -q"
    assert block_payload["title"] == "Generated validation plan"


def test_scope_enforcement_to_timeline_contract() -> None:
    result = ScopeEnforcementResult(
        allowed=False,
        action="apply_patch",
        reason="Path is explicitly disallowed by task scope.",
        risk_level="high",
        failed_path=".env",
        matched_rule=".env",
        checked_paths=[".env"],
        summary_text="Scope Enforcement:\n- Result: blocked",
    )

    payload = timeline_to_jsonable(scope_enforcement_to_timeline_step(result))

    assert payload["type"] == "scope_enforcement"
    assert payload["status"] == "failed"
    assert payload["details"]["failed_path"] == ".env"


def test_scope_enforcement_to_block_contract() -> None:
    result = ScopeEnforcementResult(
        allowed=None,
        action="apply_patch",
        reason="No task scope was provided; scope enforcement was not applied.",
        warnings=["Scope enforcement skipped."],
        summary_text="Scope Enforcement:\n- Result: skipped",
    )

    payload = timeline_to_jsonable(scope_enforcement_to_block(result))

    assert payload["type"] == "scope_enforcement"
    assert payload["status"] == "skipped"
    assert payload["title"] == "Task scope check not applied"


def test_timeline_docs_exist_and_explain_frontend_contract() -> None:
    text = (Path(__file__).resolve().parents[2] / "docs" / "timeline.md").read_text(encoding="utf-8")

    assert "JSON-friendly contract" in text
    assert "Frontend consumers" in text
    assert "Conversational Timeline Blocks" in text
