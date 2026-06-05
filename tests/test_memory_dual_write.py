import logging
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.llm import ModelConfig
from pp_agent.memory import HistoryIndexer, NoopMemoryProvider, SQLiteHistoryStore, SQLiteMemoryProvider
from pp_agent.memory.auto_index import NoopAutoIndexScheduler
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.sessions import SessionStore
from pp_agent.tools.registry import ToolRegistry


class _NoopLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {"text": "ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class _FailingMemoryProvider:
    def is_enabled(self) -> bool:
        return True

    def on_turn_persisted(self, *, session_id: str, turn_id: str, new_messages: list[ChatMessage], metadata=None) -> None:
        raise RuntimeError("simulated memory failure")


class _RecordingAutoIndexScheduler:
    def __init__(self, *, enabled: bool = True, submit_result: bool = True) -> None:
        self.enabled = enabled
        self.submit_result = submit_result
        self.submit_calls = 0

    def is_enabled(self) -> bool:
        return self.enabled

    def submit(self) -> bool:
        self.submit_calls += 1
        return self.submit_result


def _build_runtime(tmp_path: Path, *, memory_provider, auto_index_scheduler=None) -> AgentRuntime:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentRuntime(
        llm_client=_NoopLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
        memory_provider=memory_provider,
        auto_index_scheduler=auto_index_scheduler or NoopAutoIndexScheduler(),
    )
    agent.restore_session_record(record)
    return agent


def test_dual_write_failure_does_not_break_main_flow(tmp_path: Path, caplog) -> None:
    agent = _build_runtime(tmp_path, memory_provider=_FailingMemoryProvider())

    with caplog.at_level(logging.WARNING):
        events = agent.prompt("hello")

    saved = agent.session_store.load(agent.session_id)
    assert saved.messages
    assert any(event.type == "agent_end" for event in events)
    assert "Memory dual write failed" in caplog.text


def test_disabled_memory_provider_noop(tmp_path: Path) -> None:
    agent = _build_runtime(tmp_path, memory_provider=NoopMemoryProvider())

    agent.prompt("hello")

    assert (tmp_path / "history.db").exists() is False
    saved = agent.session_store.load(agent.session_id)
    assert saved.messages[-1].role == "assistant"


def test_no_duplicate_write_for_same_turn_message(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    provider = SQLiteMemoryProvider(
        store=SQLiteHistoryStore(db_path),
        indexer=HistoryIndexer(chunk_target_tokens=30, chunk_max_tokens=40),
    )
    message = ChatMessage(role="user", content=[TextPart(text="hello world " * 20)], timestamp=1.0)

    provider.on_turn_persisted(
        session_id="session-1",
        turn_id="turn-1",
        new_messages=[message],
        metadata={"source": "runtime_dual_write", "workspace": str(tmp_path)},
    )
    with sqlite3.connect(db_path) as connection:
        initial_message_count = connection.execute("SELECT COUNT(*) FROM history_messages").fetchone()[0]
        initial_chunk_count = connection.execute("SELECT COUNT(*) FROM history_chunks").fetchone()[0]

    provider.on_turn_persisted(
        session_id="session-1",
        turn_id="turn-1",
        new_messages=[message],
        metadata={"source": "runtime_dual_write", "workspace": str(tmp_path)},
    )
    with sqlite3.connect(db_path) as connection:
        message_count = connection.execute("SELECT COUNT(*) FROM history_messages").fetchone()[0]
        chunk_count = connection.execute("SELECT COUNT(*) FROM history_chunks").fetchone()[0]

    assert initial_message_count == 1
    assert initial_chunk_count >= 1
    assert message_count == initial_message_count
    assert chunk_count == initial_chunk_count


def test_no_duplicate_write_after_provider_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    message = ChatMessage(role="assistant", content=[TextPart(text="hello world " * 30)], timestamp=1.0)
    provider_one = SQLiteMemoryProvider(
        store=SQLiteHistoryStore(db_path),
        indexer=HistoryIndexer(chunk_target_tokens=30, chunk_max_tokens=40),
    )
    provider_one.on_turn_persisted(
        session_id="session-1",
        turn_id="turn-1",
        new_messages=[message],
        metadata={"source": "runtime_dual_write", "workspace": str(tmp_path)},
    )
    with sqlite3.connect(db_path) as connection:
        initial_message_count = connection.execute("SELECT COUNT(*) FROM history_messages").fetchone()[0]
        initial_chunk_count = connection.execute("SELECT COUNT(*) FROM history_chunks").fetchone()[0]

    provider_two = SQLiteMemoryProvider(
        store=SQLiteHistoryStore(db_path),
        indexer=HistoryIndexer(chunk_target_tokens=30, chunk_max_tokens=40),
    )
    provider_two.on_turn_persisted(
        session_id="session-1",
        turn_id="turn-1",
        new_messages=[message],
        metadata={"source": "runtime_dual_write", "workspace": str(tmp_path)},
    )

    with sqlite3.connect(db_path) as connection:
        message_count = connection.execute("SELECT COUNT(*) FROM history_messages").fetchone()[0]
        chunk_count = connection.execute("SELECT COUNT(*) FROM history_chunks").fetchone()[0]

    assert initial_message_count == 1
    assert initial_chunk_count >= 1
    assert message_count == initial_message_count
    assert chunk_count == initial_chunk_count


def test_auto_index_submit_happens_after_successful_dual_write(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    provider = SQLiteMemoryProvider(
        store=SQLiteHistoryStore(db_path),
        indexer=HistoryIndexer(chunk_target_tokens=30, chunk_max_tokens=40),
    )
    scheduler = _RecordingAutoIndexScheduler()
    agent = _build_runtime(tmp_path, memory_provider=provider, auto_index_scheduler=scheduler)

    events = agent.prompt("hello")

    assert any(event.type == "agent_end" for event in events)
    assert scheduler.submit_calls == 1


def test_auto_index_submit_skipped_when_dual_write_fails(tmp_path: Path, caplog) -> None:
    scheduler = _RecordingAutoIndexScheduler()
    agent = _build_runtime(tmp_path, memory_provider=_FailingMemoryProvider(), auto_index_scheduler=scheduler)

    with caplog.at_level(logging.WARNING):
        events = agent.prompt("hello")

    assert any(event.type == "agent_end" for event in events)
    assert "Memory dual write failed" in caplog.text
    assert scheduler.submit_calls == 0
