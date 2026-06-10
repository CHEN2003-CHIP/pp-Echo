from __future__ import annotations

from pathlib import Path

from pp_agent.integrations.qqbot.session_store import QQSessionStore


def test_session_store_creates_and_reuses_session(tmp_path: Path) -> None:
    store = QQSessionStore(tmp_path / "qqbot-sessions.json")

    first = store.resolve("qq:c2c:user", "c2c")
    second = store.resolve("qq:c2c:user", "c2c")
    other = store.resolve("qq:group:group", "group")

    assert first == second
    assert first != other
    assert (tmp_path / "qqbot-sessions.json").exists()


def test_session_store_recovers_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "qqbot-sessions.json"
    path.write_text("{bad", encoding="utf-8")
    store = QQSessionStore(path)

    session_id = store.resolve("qq:c2c:user", "c2c")

    assert session_id
    assert list(tmp_path.glob("qqbot-sessions.json.corrupt.*"))

