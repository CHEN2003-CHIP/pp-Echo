from __future__ import annotations

from pathlib import Path

import pytest

from pp_agent.coding import (
    CodingExecutionEvent,
    CodingExecutionSession,
    ExecutionGuardrails,
    attach_write_scope_to_patch_candidate_args,
    coding_execution_session_to_context_item,
    coding_session_to_runtime_execution_context,
    default_execution_guardrails,
    execution_guardrails_to_block,
    execution_guardrails_to_context_item,
    execution_session_to_block,
    prepare_coding_workflow,
    start_coding_execution_session,
)
from pp_agent.runtime.scope_contract import WriteScope, write_scope_to_dict
from pp_agent.observability import timeline_to_jsonable


def _workflow(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src" / "pp_agent" / "coding").mkdir(parents=True)
    (tmp_path / "tests" / "coding").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    return prepare_coding_workflow("extend coding intelligence planner", workspace=tmp_path)


def test_default_execution_guardrails() -> None:
    guardrails = default_execution_guardrails()

    assert guardrails.max_tool_calls == 20
    assert guardrails.max_shell_commands == 5
    assert guardrails.max_patch_candidates == 3
    assert guardrails.stop_on_approval is True
    assert guardrails.stop_on_scope_block is True
    assert guardrails.stop_on_test_failure is True


def test_start_coding_execution_session_prepares_session(tmp_path: Path) -> None:
    session = start_coding_execution_session(_workflow(tmp_path), session_id="exec-1")

    assert session.id == "exec-1"
    assert session.status == "prepared"
    assert session.phase == "prepared"
    assert session.summary_text.startswith("Coding Execution Session:")


def test_start_coding_execution_session_uses_passed_session_id(tmp_path: Path) -> None:
    session = start_coding_execution_session(_workflow(tmp_path), session_id="stable-id")

    assert session.id == "stable-id"


def test_start_coding_execution_session_derives_write_scope(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)
    session = start_coding_execution_session(workflow, session_id="exec-1")

    assert session.write_scope is not None
    assert session.write_scope.allowed_paths == workflow.task_scope.allowed_paths
    assert session.write_scope.source == "task_scope"


def test_start_coding_execution_session_includes_workflow_timeline_blocks(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)
    session = start_coding_execution_session(workflow, session_id="exec-1")

    assert session.timeline_blocks[: len(workflow.timeline_blocks)] == workflow.timeline_blocks
    assert [block.type for block in session.timeline_blocks[-2:]] == ["execution_session", "execution_guardrails"]


def test_start_coding_execution_session_includes_context_items(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)
    session = start_coding_execution_session(workflow, session_id="exec-1")

    assert session.context_items[: len(workflow.context_items)] == workflow.context_items
    assert session.context_items[-1]["title"] == "Coding execution session"


def test_execution_guardrails_to_context_item() -> None:
    item = execution_guardrails_to_context_item(default_execution_guardrails())

    assert item["title"] == "Execution guardrails"
    assert item["metadata"]["execution_guardrails"]["max_tool_calls"] == 20


def test_coding_execution_session_to_context_item(tmp_path: Path) -> None:
    session = start_coding_execution_session(_workflow(tmp_path), session_id="exec-1")

    item = coding_execution_session_to_context_item(session)

    assert item["title"] == "Coding execution session"
    assert item["metadata"]["coding_execution_session"]["phase"] == "prepared"
    assert item["metadata"]["coding_execution_session"]["predicted_impact_not_actual"] is True


def test_attach_write_scope_to_patch_candidate_args_adds_write_scope() -> None:
    scope = WriteScope(allowed_paths=["src/**"], source="task_scope")

    args = attach_write_scope_to_patch_candidate_args({"patch": "x"}, scope)

    assert args["write_scope"] == write_scope_to_dict(scope)


def test_attach_write_scope_to_patch_candidate_args_without_scope_keeps_args() -> None:
    args = attach_write_scope_to_patch_candidate_args({"patch": "x"}, None)

    assert args == {"patch": "x"}


def test_attach_write_scope_to_patch_candidate_args_does_not_mutate_original() -> None:
    original = {"patch": "x"}

    attach_write_scope_to_patch_candidate_args(original, WriteScope(allowed_paths=["src/**"]))

    assert original == {"patch": "x"}


def test_attach_write_scope_to_patch_candidate_args_rejects_conflicting_scope() -> None:
    args = {"write_scope": {"allowed_paths": ["docs/**"]}}

    with pytest.raises(ValueError, match="different write_scope"):
        attach_write_scope_to_patch_candidate_args(args, WriteScope(allowed_paths=["src/**"]))


def test_coding_session_to_runtime_execution_context(tmp_path: Path) -> None:
    session = start_coding_execution_session(_workflow(tmp_path), session_id="exec-1")

    context = coding_session_to_runtime_execution_context(session)

    assert context.session_id == "exec-1"
    assert context.status == session.status
    assert context.phase == session.phase
    assert context.write_scope == session.write_scope
    assert context.guardrails.max_tool_calls == session.guardrails.max_tool_calls
    assert context.guardrails.max_shell_commands == session.guardrails.max_shell_commands
    assert context.guardrails.max_patch_candidates == session.guardrails.max_patch_candidates
    assert context.counters.tool_calls == 0
    assert context.counters.shell_commands == 0
    assert context.counters.patch_candidates == 0
    assert context.predicted_impact_not_actual is True
    assert context.warnings == session.warnings


def test_execution_session_to_block(tmp_path: Path) -> None:
    session = start_coding_execution_session(_workflow(tmp_path), session_id="exec-1")

    payload = timeline_to_jsonable(execution_session_to_block(session))

    assert payload["type"] == "execution_session"
    assert payload["details"]["write_scope"]["source"] == "task_scope"


def test_execution_guardrails_to_block() -> None:
    payload = timeline_to_jsonable(execution_guardrails_to_block(default_execution_guardrails()))

    assert payload["type"] == "execution_guardrails"
    assert payload["details"]["max_patch_candidates"] == 3


def test_execution_session_summary_is_stable(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)

    first = start_coding_execution_session(workflow, session_id="exec-1")
    second = start_coding_execution_session(workflow, session_id="exec-1")

    assert first.summary_text == second.summary_text


def test_execution_public_models_have_docstrings() -> None:
    assert ExecutionGuardrails.__doc__
    assert CodingExecutionSession.__doc__
    assert CodingExecutionEvent.__doc__


def test_execution_public_helpers_have_docstrings() -> None:
    assert default_execution_guardrails.__doc__
    assert start_coding_execution_session.__doc__
    assert execution_guardrails_to_context_item.__doc__
    assert coding_execution_session_to_context_item.__doc__
    assert attach_write_scope_to_patch_candidate_args.__doc__
    assert coding_session_to_runtime_execution_context.__doc__
    assert execution_session_to_block.__doc__
    assert execution_guardrails_to_block.__doc__
