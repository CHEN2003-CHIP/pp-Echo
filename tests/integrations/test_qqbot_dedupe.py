from __future__ import annotations

from pathlib import Path

from pp_agent.integrations.qqbot.dedupe import QQEventDedupeStore


def test_dedupe_first_false_then_true(tmp_path: Path) -> None:
    now = [100.0]
    store = QQEventDedupeStore(tmp_path / "qqbot-dedupe.json", ttl_seconds=10, clock=lambda: now[0])

    assert store.seen_or_mark("event") is False
    assert store.seen_or_mark("event") is True
    now[0] = 120.0
    assert store.seen_or_mark("event") is False


def test_dedupe_recovers_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "qqbot-dedupe.json"
    path.write_text("{bad", encoding="utf-8")
    store = QQEventDedupeStore(path)

    assert store.seen_or_mark("event") is False
    assert list(tmp_path.glob("qqbot-dedupe.json.corrupt.*"))
