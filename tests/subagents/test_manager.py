from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pp_agent.llm.models import ModelConfig
from pp_agent.runtime.session_host import SessionHost
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.checkpoints import CheckpointStore
from pp_agent.storage.models import StoredModelConfig
from pp_agent.storage.sessions import SessionStore
from pp_agent.subagents.manager import SubAgentManager
from pp_agent.tools.registry import ToolRegistry


class StubRuntime:
    def __init__(self, session_store: SessionStore, session_id: str, system_prompt: str, recorder: dict[str, object]) -> None:
        self.session_store = session_store
        self.session_id = session_id
        self.state = SimpleNamespace(
            system_prompt=system_prompt,
            messages=[],
            model=ModelConfig(),
            turn=SimpleNamespace(turn_id=0),
        )
        self.require_plan_approval = False
        self.tool_registry = ToolRegistry(session_store.root.parent, current_session_id=session_id)
        self._recorder = recorder
        self._pending_events = []
        self.llm_client = SimpleNamespace(model=ModelConfig())

    def restore_session_record(self, record, *, emit_event: bool = True) -> None:
        self._recorder["restore_called"] = True
        self._recorder["restored_session_id"] = record.id

    def _event(self, event_type: str, **kwargs):
        return SimpleNamespace(type=event_type, **kwargs)

    def _queue_lifecycle_event(self, event) -> None:
        self._pending_events.append(event)

    def _emit(self, event):
        self._recorder.setdefault("emitted_events", []).append(event.type)
        return [event]

    def prompt(self, prompt_text: str):
        self._recorder["prompt_calls"] = int(self._recorder.get("prompt_calls", 0)) + 1
        self._recorder["prompt_text"] = prompt_text
        self._recorder["system_prompt"] = self.state.system_prompt
        self._recorder["tools"] = [item["function"]["name"] for item in self.tool_registry.openapi_specs()]
        self.state.messages = [
            SimpleNamespace(
                role="assistant",
                content=[
                    SimpleNamespace(
                        text=(
                            "Findings\n"
                            "- Repository notes inspected.\n\n"
                            "Recommended next action\n"
                            "- Continue with the requested change.\n\n"
                            "Files/paths inspected\n"
                            "- notes.txt\n\n"
                            "Confidence\n"
                            "- medium"
                        )
                    )
                ],
            )
        ]
        return [
            SimpleNamespace(type="tool_call", tool_name="read_file"),
            SimpleNamespace(type="agent_end", tool_name=None),
        ]


def _host(tmp_path: Path, recorder: dict[str, object]) -> SessionHost:
    session_store = SessionStore(tmp_path / "sessions")

    def runtime_factory(workspace: Path, record, lifecycle_subscribers=None):
        _ = workspace, lifecycle_subscribers
        return StubRuntime(session_store, record.id, record.system_prompt, recorder)

    return SessionHost(
        runtime_factory=runtime_factory,
        session_store_factory=lambda _workspace: session_store,
        pending_action_store_factory=lambda workspace: PendingActionStore(workspace / "pending"),
        session_defaults_factory=lambda _workspace: {"system_prompt": "parent system", "model": StoredModelConfig()},
        checkpoint_store_factory=lambda workspace: CheckpointStore(workspace / "checkpoints"),
    )


def test_subagent_manager_runs_in_forked_session_with_restricted_tools(tmp_path: Path) -> None:
    recorder: dict[str, object] = {}
    host = _host(tmp_path, recorder)
    parent_runtime = host.create_session(tmp_path)
    session_store = SessionStore(tmp_path / "sessions")
    parent_registry = ToolRegistry(tmp_path, current_session_id=parent_runtime.session_id)
    parent_registry.register_function_tool(
        name="spawn_subagent",
        description="Delegate to a child subagent.",
        parameters={"type": "object", "properties": {}},
        executor=lambda _workspace, _arguments: "not allowed",
        tool_family="extension",
        exact_effect_mode="required",
    )
    manager = SubAgentManager(
        workspace=tmp_path,
        session_host=host,
        parent_registry=parent_registry,
        session_store=session_store,
        runtime_factory=host._runtime_factory,
    )

    result = manager.run_sync(
        parent_session_id=parent_runtime.session_id,
        parent_head_id=parent_runtime.session_store.load(parent_runtime.session_id).active_head_id,
        spec_name="repo-researcher",
        task="Inspect the repository notes and summarize them.",
    )

    parent_record = session_store.load(parent_runtime.session_id)
    child_record = session_store.load(result.session_id)

    assert result.success is True
    assert result.session_id != parent_runtime.session_id
    assert result.final_text.startswith("Findings")
    assert result.summary == "Repository notes inspected."
    assert result.recommended_next_action == "Continue with the requested change."
    assert result.inspected_paths == ["notes.txt"]
    assert result.confidence == "medium"
    assert result.tool_calls_used == ["read_file"]
    assert result.event_count > 0
    assert recorder["tools"] == ["read_file", "list_files", "search_text", "grep_code"]
    assert "spawn_subagent" not in recorder["tools"]
    assert "write_file" not in recorder["tools"]
    assert "approve_pending_action" not in recorder["tools"]
    assert "repo-researcher" in str(recorder["system_prompt"])
    assert recorder["prompt_calls"] == 1
    assert "You are subagent 'repo-researcher'." in str(recorder["prompt_text"])
    assert parent_record.messages == []
    assert child_record.messages == []
