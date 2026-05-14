from __future__ import annotations

import json
from pathlib import Path

from pp_agent.app.bootstrap import load_settings
from pp_agent.cli.render.runtime import console
from pp_agent.memory.file_memory_search import FileMemorySearchRequest
from pp_agent.memory.file_memory_tools import build_file_memory_search_engine, build_file_memory_store


def memory_sync_main(workspace: Path, *, json_mode: bool = False) -> None:
    settings = load_settings(workspace)
    summary = build_file_memory_search_engine(workspace, settings=settings).sync().to_dict()
    _print_payload(summary, json_mode=json_mode)


def memory_search_main(
    workspace: Path,
    query: str,
    *,
    top_k: int = 5,
    mode: str = "auto",
    json_mode: bool = False,
    include_debug: bool = False,
) -> None:
    settings = load_settings(workspace)
    engine = build_file_memory_search_engine(workspace, settings=settings)
    result = engine.search(
        FileMemorySearchRequest(
            query=query,
            top_k=top_k,
            mode=mode if mode in {"auto", "hybrid", "bm25", "vector"} else "auto",  # type: ignore[arg-type]
            include_debug=include_debug,
        )
    )
    payload = result.to_dict(include_debug=include_debug)
    _print_payload(payload, json_mode=json_mode)


def memory_get_main(
    workspace: Path,
    path: str,
    *,
    start_line: int | None = None,
    line_count: int | None = None,
    json_mode: bool = False,
) -> None:
    settings = load_settings(workspace)
    store = build_file_memory_store(workspace, settings=settings)
    try:
        result = store.read_line_range(path, start_line=start_line, line_count=line_count)
        payload = {
            "path": result.path,
            "line_start": result.line_start,
            "line_end": result.line_end,
            "content": result.content,
        }
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "read_failed")
        payload = {
            "path": path,
            "error": {"code": code, "message": str(exc)},
        }
    _print_payload(payload, json_mode=json_mode)


def _print_payload(payload: dict[str, object], *, json_mode: bool) -> None:
    rendered = json.dumps(payload, ensure_ascii=True, indent=2)
    if json_mode:
        console.print(rendered)
        return
    console.print(rendered)


__all__ = ["memory_get_main", "memory_search_main", "memory_sync_main"]
