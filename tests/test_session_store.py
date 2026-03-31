from pathlib import Path

from agent_core.types import ModelConfig
from storage.sessions import SessionStore


def test_session_store_save_and_load(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.metadata.compaction.summary = "old messages"
    record.metadata.compaction.summarized_message_count = 2
    saved_path = store.save(record)

    assert saved_path.exists()
    loaded = store.load(record.id)
    assert loaded.id == record.id
    assert loaded.system_prompt == "hello"
    assert loaded.model.model == "qwen3.5-plus"
    assert loaded.compaction.summary == "old messages"


def test_session_store_fork(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    source = store.create("hello", ModelConfig())
    source.metadata.compaction.summary = "summary"
    store.save(source)

    forked = store.fork(source.id)
    store.save(forked)

    assert forked.parent_id == source.id
    assert forked.id != source.id
    assert forked.compaction.summary == "summary"


def test_session_store_list_returns_metadata(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    store.save(record)

    sessions = store.list()

    assert len(sessions) == 1
    assert sessions[0].id == record.id