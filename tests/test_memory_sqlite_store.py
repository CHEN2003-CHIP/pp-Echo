import sqlite3
from pathlib import Path

from pp_agent.memory import HistoryIndexer, SQLiteHistoryStore


def test_append_message_persists_to_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    store = SQLiteHistoryStore(db_path, busy_timeout_ms=3210)

    message_id = store.append_message(
        session_id="session-1",
        turn_id="turn-1",
        message_index=0,
        role="user",
        text="hello sqlite memory",
        metadata={"source": "runtime_dual_write", "workspace": str(tmp_path)},
    )

    rows = store.list_messages_by_turn(session_id="session-1", turn_id="turn-1")
    assert len(rows) == 1
    assert rows[0].id == message_id
    assert rows[0].role == "user"
    assert rows[0].text == "hello sqlite memory"
    assert rows[0].metadata is not None
    assert rows[0].metadata["source"] == "runtime_dual_write"

    with store._connect() as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert str(journal_mode).lower() in {"wal", "memory"}
    assert busy_timeout == 3210


def test_append_chunks_created_for_long_message(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    store = SQLiteHistoryStore(db_path)
    indexer = HistoryIndexer(chunk_target_tokens=30, chunk_max_tokens=40)
    message_id = store.append_message(
        session_id="session-1",
        turn_id="turn-1",
        message_index=0,
        role="assistant",
        text="seed",
        metadata={"source": "runtime_dual_write"},
    )
    long_text = "\n\n".join(
        [
            " ".join(f"paragraph-{paragraph}-word-{index}" for index in range(50))
            for paragraph in range(4)
        ]
    )

    chunk_ids = store.append_chunks(
        session_id="session-1",
        turn_id="turn-1",
        message_id=message_id,
        chunks=indexer.chunk_message(
            text=long_text,
            role="assistant",
            metadata={"source": "runtime_dual_write", "workspace": str(tmp_path)},
        ),
    )

    assert len(chunk_ids) >= 2
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT source_kind, embedding_status, embedding_model, embedding_dim, vector_ref
            FROM history_chunks
            WHERE message_id = ?
            ORDER BY chunk_index ASC
            """,
            (message_id,),
        ).fetchall()

    assert rows
    assert all(row[0] == "assistant" for row in rows)
    assert all(row[1] == "pending" for row in rows)
    assert all(row[2] is None for row in rows)
    assert all(row[3] is None for row in rows)
    assert all(row[4] is None for row in rows)
