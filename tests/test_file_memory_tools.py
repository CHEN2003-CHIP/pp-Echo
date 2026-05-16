from __future__ import annotations

import json
from pathlib import Path

from pp_agent.memory.file_memory_tools import memory_get_executor, memory_search_executor
from pp_agent.storage.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    settings = Settings.load(tmp_path)
    settings.memory.file_memory_allow_remote_embedding = False
    settings.global_dir = tmp_path / ".global"
    settings.global_dir.mkdir(parents=True, exist_ok=True)
    return settings


def test_memory_search_tool_returns_structured_empty_results(tmp_path: Path) -> None:
    result = memory_search_executor(tmp_path, {"query": "anything"}, settings=_settings(tmp_path))
    payload = json.loads(result.content)

    assert result.is_error is False
    assert payload["results"] == []
    assert payload["query"] == "anything"


def test_memory_search_tool_returns_snippets_not_whole_file(tmp_path: Path) -> None:
    (tmp_path / "MEMORY.md").write_text("# Memory\n" + ("pytest " * 300), encoding="utf-8")
    settings = _settings(tmp_path)
    settings.memory.file_memory_snippet_chars = 80

    result = memory_search_executor(tmp_path, {"query": "pytest", "top_k": 1}, settings=settings)
    payload = json.loads(result.content)

    assert payload["results"]
    assert len(payload["results"][0]["snippet"]) <= 80


def test_memory_get_tool_returns_content_and_structured_errors(tmp_path: Path) -> None:
    (tmp_path / "MEMORY.md").write_text("one\ntwo\nthree", encoding="utf-8")
    ok = memory_get_executor(tmp_path, {"path": "MEMORY.md", "start_line": 2, "line_count": 1}, settings=_settings(tmp_path))
    bad = memory_get_executor(tmp_path, {"path": "../secret.md"}, settings=_settings(tmp_path))

    ok_payload = json.loads(ok.content)
    bad_payload = json.loads(bad.content)
    assert ok_payload["content"] == "two"
    assert bad.is_error is True
    assert bad_payload["error"]["code"] in {"path_escape", "forbidden_path", "absolute_path"}


def test_memory_search_and_get_support_global_scope(tmp_path: Path, monkeypatch) -> None:
    global_root = tmp_path / ".global"
    global_root.mkdir()
    (global_root / "MEMORY.md").write_text("# Global Memory\n\nUser always prefers Chinese plans.\n", encoding="utf-8")
    monkeypatch.setenv("PP_AGENT_HOME", str(global_root))
    settings = _settings(tmp_path)

    result = memory_search_executor(tmp_path, {"query": "Chinese plans", "scope": "global"}, settings=settings)
    payload = json.loads(result.content)
    read = memory_get_executor(tmp_path, {"path": "global/MEMORY.md", "start_line": 1, "line_count": 3}, settings=settings)
    read_payload = json.loads(read.content)

    assert payload["results"]
    assert payload["results"][0]["path"] == "global/MEMORY.md"
    assert payload["results"][0]["source_scope"] == "global_bootstrap"
    assert "Chinese plans" in read_payload["content"]
