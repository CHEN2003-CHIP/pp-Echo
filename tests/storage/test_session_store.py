from pathlib import Path

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.llm import ModelConfig
from pp_agent.storage.sessions import (
    SESSION_CORRELATION_KEY,
    SESSION_MESSAGE_ID_KEY,
    SessionEvidenceLookupStatus,
    SessionStore,
    build_external_tool_result_correlation,
    build_model_continuation_completion_correlation,
    build_session_result_digest,
    ensure_session_message_id,
)


def test_session_store_save_and_load_uses_per_session_jsonl_file(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.metadata.compaction.summary = "old messages"
    record.metadata.compaction.summarized_message_count = 2
    saved_path = store.save(record)

    assert saved_path.exists()
    assert saved_path.name == f"{record.id}.jsonl"
    loaded = store.load(record.id)
    assert loaded.id == record.id
    assert loaded.system_prompt == "hello"
    assert loaded.model.model == record.model.model
    assert loaded.compaction.summary == "old messages"


def test_external_tool_result_evidence_lookup_survives_reload(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "ok", "success": True, "token": "secret-token"})
    message = ChatMessage(
        role="tool",
        tool_call_id="call-1",
        tool_name="approve_pending_action",
        content=[TextPart(text="ok")],
        timestamp=2.0,
    )
    ensure_session_message_id(message)
    message.metadata[SESSION_CORRELATION_KEY] = build_external_tool_result_correlation(
        action_id="action-1",
        result_digest=digest,
        tool_name="approve_pending_action",
        completed_at=2.0,
        turn_id="turn-1",
    )
    record.messages = [ChatMessage(role="user", content=[TextPart(text="u")], timestamp=1.0), message]
    store.save(record)

    loaded = store.load(record.id)
    result = store.lookup_external_tool_result_evidence(record.id, action_id="action-1", result_digest=digest)

    assert loaded.messages[1].metadata[SESSION_MESSAGE_ID_KEY] == message.metadata[SESSION_MESSAGE_ID_KEY]
    assert "secret-token" not in digest
    assert result.status == SessionEvidenceLookupStatus.FOUND
    assert result.evidence is not None
    assert result.evidence.action_id == "action-1"
    assert result.evidence.result_digest == digest


def test_external_tool_result_lookup_fails_closed_for_mismatch_and_duplicates(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "ok"})
    other_digest = build_session_result_digest({"result": "different"})

    def correlated_message(message_id: str) -> ChatMessage:
        message = ChatMessage(
            role="tool",
            tool_call_id=message_id,
            tool_name="approve_pending_action",
            content=[TextPart(text="ok")],
            metadata={SESSION_MESSAGE_ID_KEY: message_id},
            timestamp=2.0,
        )
        message.metadata[SESSION_CORRELATION_KEY] = build_external_tool_result_correlation(
            action_id="action-1",
            result_digest=digest,
            tool_name="approve_pending_action",
            completed_at=2.0,
        )
        return message

    record.messages = [correlated_message("msg-one"), correlated_message("msg-two")]
    store.save(record)

    duplicate = store.lookup_external_tool_result_evidence(record.id, action_id="action-1", result_digest=digest)
    mismatch = store.lookup_external_tool_result_evidence(record.id, action_id="action-1", result_digest=other_digest)

    assert duplicate.status == SessionEvidenceLookupStatus.AMBIGUOUS
    assert mismatch.status == SessionEvidenceLookupStatus.IDENTITY_MISMATCH


def test_legacy_tool_message_is_insufficient_recovery_evidence(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="tool", tool_call_id="call-1", tool_name="approve_pending_action", content=[TextPart(text="ok")], timestamp=1.0)
    ]
    store.save(record)

    result = store.lookup_external_tool_result_evidence(record.id, action_id="action-1")

    assert result.status == SessionEvidenceLookupStatus.LEGACY_INSUFFICIENT


def test_model_continuation_completion_lookup_requires_matching_metadata(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    legacy = ChatMessage(role="assistant", content=[TextPart(text="done")], timestamp=1.0)
    correlated = ChatMessage(role="assistant", content=[TextPart(text="done")], timestamp=2.0)
    ensure_session_message_id(correlated)
    correlated.metadata[SESSION_CORRELATION_KEY] = build_model_continuation_completion_correlation(
        continuation_id="cont-1",
        completed_at=2.0,
        turn_id="turn-2",
    )
    record.messages = [legacy, correlated]
    store.save(record)

    found = store.lookup_model_continuation_completion_evidence(record.id, continuation_id="cont-1")
    missing = store.lookup_model_continuation_completion_evidence(record.id, continuation_id="cont-missing")

    assert found.status == SessionEvidenceLookupStatus.FOUND
    assert found.evidence is not None
    assert found.evidence.correlation_id == "cont-1"
    assert missing.status == SessionEvidenceLookupStatus.NOT_FOUND


def test_session_store_save_is_append_only_for_existing_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    store.save(record)
    path = tmp_path / f"{record.id}.jsonl"
    original_lines = path.read_text(encoding="utf-8").splitlines()

    record.messages = [ChatMessage(role="user", content=[TextPart(text="hello")], timestamp=1.0)]
    store.save(record)
    updated_lines = path.read_text(encoding="utf-8").splitlines()

    assert len(updated_lines) > len(original_lines)
    assert updated_lines[: len(original_lines)] == original_lines


def test_session_store_fork_creates_parent_child_link(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    source = store.create("hello", ModelConfig())
    source.metadata.compaction.summary = "summary"
    source.messages = [ChatMessage(role="user", content=[TextPart(text="root question")], timestamp=1.0)]
    store.save(source)

    forked = store.fork(source.id)
    store.save(forked)

    assert forked.parent_id == source.id
    assert forked.id != source.id
    assert forked.compaction.summary == "summary"
    assert len(forked.messages) == 1


def test_session_store_tree_returns_branch_structure_and_previews(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    root = store.create("hello", ModelConfig())
    root.metadata.compaction.summary = "root summary preview"
    root.messages = [
        ChatMessage(role="user", content=[TextPart(text="user asks about planner")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="assistant answers briefly")], timestamp=2.0),
    ]
    store.save(root)
    branch = store.fork(root.id)
    branch.messages.append(ChatMessage(role="user", content=[TextPart(text="branch follow-up")], timestamp=3.0))
    store.save(branch)

    tree = store.tree()
    description = store.describe(root.id)

    assert len(tree) == 2
    assert any(node.id == root.id and node.parent_id is None and node.summary_preview and node.turn_count == 1 for node in tree)
    assert any(node.id == branch.id and node.parent_id == root.id and node.last_user_preview == "branch follow-up" and node.turn_count == 2 for node in tree)
    assert description["current"]["id"] == root.id
    assert description["children"][0]["id"] == branch.id


def test_session_store_rewind_creates_truncated_branch(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    source = store.create("hello", ModelConfig())
    source.metadata.compaction.summary = "summary"
    source.metadata.pending_plan_token = "token-1"
    source.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
        ChatMessage(role="user", content=[TextPart(text="u2")], timestamp=3.0),
    ]
    store.save(source)

    rewound = store.rewind(source.id, 2)
    store.save(rewound)

    assert rewound.parent_id == source.id
    assert len(rewound.messages) == 2
    assert rewound.messages[-1].role == "assistant"
    assert rewound.compaction.summary == ""
    assert rewound.pending_plan_token is None


def test_session_store_rewind_turns_uses_complete_turns(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    source = store.create("hello", ModelConfig())
    source.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
        ChatMessage(role="tool", content=[TextPart(text="t1")], timestamp=3.0),
        ChatMessage(role="user", content=[TextPart(text="u2")], timestamp=4.0),
        ChatMessage(role="assistant", content=[TextPart(text="a2")], timestamp=5.0),
    ]
    store.save(source)

    rewound = store.rewind_turns(source.id, 1)

    assert [message.role for message in rewound.messages] == ["user", "assistant", "tool"]


def test_session_store_list_returns_metadata(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    store.save(record)

    sessions = store.list()

    assert len(sessions) == 1
    assert sessions[0].id == record.id


def test_session_store_children_of_returns_direct_children(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    root = store.create("hello", ModelConfig())
    store.save(root)
    child = store.fork(root.id)
    store.save(child)

    children = store.children_of(root.id)

    assert len(children) == 1
    assert children[0].id == child.id


def test_session_store_load_builds_turn_index_and_active_head(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
        ChatMessage(role="user", content=[TextPart(text="u2")], timestamp=3.0),
        ChatMessage(role="assistant", content=[TextPart(text="a2")], timestamp=4.0),
    ]
    store.save(record)

    loaded = store.load(record.id)

    assert len(loaded.turn_nodes) == 2
    assert loaded.active_head_id == loaded.turn_nodes[-1].id
    assert [message.role for message in store.branch_messages(loaded, loaded.active_head_id)] == ["user", "assistant", "user", "assistant"]


def test_session_store_can_switch_active_head_to_historical_turn(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
        ChatMessage(role="user", content=[TextPart(text="u2")], timestamp=3.0),
        ChatMessage(role="assistant", content=[TextPart(text="a2")], timestamp=4.0),
    ]
    store.save(record)
    loaded = store.load(record.id)

    historical_head = loaded.turn_nodes[0].id
    store.set_active_head(loaded.id, historical_head)
    switched = store.load(loaded.id)

    assert switched.active_head_id == historical_head
    assert [message.role for message in store.branch_messages(switched, switched.active_head_id)] == ["user", "assistant"]


def test_session_store_sync_branch_state_appends_turn_branch_from_historical_head(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
        ChatMessage(role="user", content=[TextPart(text="u2")], timestamp=3.0),
        ChatMessage(role="assistant", content=[TextPart(text="a2")], timestamp=4.0),
    ]
    store.save(record)
    loaded = store.load(record.id)
    historical_head = loaded.turn_nodes[0].id

    new_branch_messages = store.branch_messages(loaded, historical_head) + [
        ChatMessage(role="user", content=[TextPart(text="branch user")], timestamp=5.0),
        ChatMessage(role="assistant", content=[TextPart(text="branch answer")], timestamp=6.0),
    ]
    updated = store.sync_branch_state(
        loaded,
        base_head_id=historical_head,
        branch_messages=new_branch_messages,
        pending_plan_token=None,
        pending_tool_calls=[],
    )
    store.save(updated)
    saved = store.load(record.id)

    assert len(saved.turn_nodes) == 3
    assert saved.active_head_id == saved.turn_nodes[-1].id
    assert saved.turn_nodes[-1].parent_id == historical_head
    assert [message.role for message in store.branch_messages(saved, saved.active_head_id)] == ["user", "assistant", "user", "assistant"]
    assert any(node.parent_id == historical_head and node.id != loaded.turn_nodes[1].id for node in saved.turn_nodes)


def test_session_store_migrates_compaction_metadata_into_turn_tree_entry(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
    ]
    record.metadata.compaction.summary = "old summary"
    record.metadata.compaction.summarized_message_count = 2
    store.save(record)

    loaded = store.load(record.id)
    compaction_nodes = [node for node in loaded.turn_nodes if node.entry_type == "compaction"]

    assert loaded.compaction.summary == "old summary"
    assert loaded.active_head_id == compaction_nodes[-1].id
    assert compaction_nodes[-1].summary == "old summary"
    assert compaction_nodes[-1].summarized_message_count == 2


def test_session_store_turn_entries_include_compaction_entries(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
    ]
    record.metadata.compaction.summary = "summary line"
    record.metadata.compaction.summarized_message_count = 2
    store.save(record)

    entries = store.turn_entries(record.id)

    assert [entry.entry_type for entry in entries] == ["turn", "compaction"]
    assert entries[-1].summary_preview == "summary line"
    assert entries[-1].summarized_message_count == 2


def test_session_store_fork_from_compaction_head_uses_head_branch(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
    ]
    record.metadata.compaction.summary = "summary line"
    record.metadata.compaction.summarized_message_count = 2
    store.save(record)
    saved = store.load(record.id)
    compaction_head = next(node.id for node in saved.turn_nodes if node.entry_type == "compaction")

    forked = store.fork_from_head(saved.id, compaction_head)

    assert forked.compaction.summary == "summary line"
    assert forked.messages == saved.messages
    assert forked.active_head_id is not None


def test_session_store_turn_node_uses_indexed_lookup(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
    ]
    store.save(record)
    loaded = store.load(record.id)

    node = store.turn_node(loaded, loaded.active_head_id)

    assert node is not None
    assert loaded._turn_index[loaded.active_head_id].id == node.id


def test_session_store_tree_skips_partial_session_files_without_snapshot(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    good = store.create("hello", ModelConfig())
    store.save(good)
    (tmp_path / "broken-session.jsonl").write_text('{"type":"metadata_created","session_id":"broken"}\n', encoding="utf-8")

    tree = store.tree()

    assert len(tree) == 1
    assert tree[0].id == good.id
