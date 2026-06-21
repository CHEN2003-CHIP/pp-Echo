from __future__ import annotations

import json
from pathlib import Path

from pp_agent.app.bootstrap import load_settings
from pp_agent.cli.render.runtime import console
from pp_agent.memory.core_renderer import workspace_id_for_path
from pp_agent.memory.core_service import service_for_workspace
from pp_agent.memory.core_tools import candidate_from_arguments
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
    scope: str = "auto",
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
            scope=scope if scope in {"auto", "workspace", "global", "all"} else "auto",  # type: ignore[arg-type]
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


def memory_propose_main(
    workspace: Path,
    content: str,
    *,
    scope: str = "workspace",
    section: str = "project_profile",
    memory_type: str = "general",
    confidence: float = 0.5,
    reason: str = "",
    json_mode: bool = False,
) -> None:
    settings = load_settings(workspace)
    service = service_for_workspace(workspace, settings)
    candidate = candidate_from_arguments(
        {
            "content": content,
            "scope": scope,
            "section": section,
            "type": memory_type,
            "confidence": confidence,
            "reason": reason,
        },
        workspace=workspace,
    )
    result = service.propose(candidate, actor="cli", reason=reason)
    _print_payload(
        {
            "memory": result.memory.model_dump(mode="python"),
            "warnings": result.warnings,
            "duplicate_of": result.duplicate_of,
            "safety": result.safety,
            "conflicts_with": result.conflicts_with,
            "budget": result.budget,
            "audit": result.audit,
        },
        json_mode=json_mode,
    )


def memory_pending_main(workspace: Path, *, json_mode: bool = False) -> None:
    settings = load_settings(workspace)
    service = service_for_workspace(workspace, settings)
    memories = service.store.list_pending(workspace_id=workspace_id_for_path(workspace))
    _print_payload({"pending": [memory.model_dump(mode="python") for memory in memories]}, json_mode=json_mode)


def memory_approve_main(workspace: Path, memory_id: str, *, json_mode: bool = False) -> None:
    _memory_status_main(workspace, memory_id, "approve", json_mode=json_mode)


def memory_reject_main(workspace: Path, memory_id: str, *, json_mode: bool = False) -> None:
    _memory_status_main(workspace, memory_id, "reject", json_mode=json_mode)


def memory_archive_main(workspace: Path, memory_id: str, *, json_mode: bool = False) -> None:
    _memory_status_main(workspace, memory_id, "archive", json_mode=json_mode)


def memory_replace_main(
    workspace: Path,
    old_memory_id: str,
    content: str,
    *,
    section: str = "project_profile",
    memory_type: str = "general",
    confidence: float = 0.5,
    json_mode: bool = False,
) -> None:
    settings = load_settings(workspace)
    service = service_for_workspace(workspace, settings)
    candidate = candidate_from_arguments(
        {"content": content, "section": section, "type": memory_type, "confidence": confidence},
        workspace=workspace,
    )
    result = service.replace(old_memory_id, candidate, actor="cli")
    _print_payload({"memory": result.memory.model_dump(mode="python"), "warnings": result.warnings, "budget": result.budget, "audit": result.audit}, json_mode=json_mode)


def memory_snapshot_main(workspace: Path, *, json_mode: bool = False) -> None:
    settings = load_settings(workspace)
    result = service_for_workspace(workspace, settings).snapshot()
    _print_payload(result.model_dump(mode="python"), json_mode=json_mode)


def memory_audit_main(workspace: Path, memory_id: str | None = None, *, limit: int = 100, json_mode: bool = False) -> None:
    settings = load_settings(workspace)
    records = service_for_workspace(workspace, settings).audit(memory_id=memory_id, limit=limit)
    _print_payload({"audit": [record.model_dump(mode="python") for record in records]}, json_mode=json_mode)


def memory_compact_preview_main(workspace: Path, *, json_mode: bool = False) -> None:
    settings = load_settings(workspace)
    payload = service_for_workspace(workspace, settings).compact_preview()
    _print_payload(payload, json_mode=json_mode)


def memory_compact_apply_main(workspace: Path, *, reason: str = "manual_compaction", json_mode: bool = False) -> None:
    settings = load_settings(workspace)
    payload = service_for_workspace(workspace, settings).compact_apply(actor="cli", reason=reason)
    _print_payload(payload, json_mode=json_mode)


def memory_merge_preview_main(workspace: Path, *, json_mode: bool = False) -> None:
    settings = load_settings(workspace)
    payload = service_for_workspace(workspace, settings).merge_preview()
    _print_payload(payload, json_mode=json_mode)


def memory_merge_apply_main(workspace: Path, *, reason: str = "auto_merge", json_mode: bool = False) -> None:
    settings = load_settings(workspace)
    payload = service_for_workspace(workspace, settings).merge_apply(actor="cli", reason=reason)
    _print_payload(payload, json_mode=json_mode)


def memory_provider_status_main(workspace: Path, *, json_mode: bool = False) -> None:
    settings = load_settings(workspace)
    payload = service_for_workspace(workspace, settings).provider.status()
    _print_payload(payload, json_mode=json_mode)


def _memory_status_main(workspace: Path, memory_id: str, action: str, *, json_mode: bool) -> None:
    settings = load_settings(workspace)
    service = service_for_workspace(workspace, settings)
    if action == "approve":
        result = service.approve(memory_id, actor="cli")
    elif action == "reject":
        result = service.reject(memory_id, actor="cli")
    elif action == "archive":
        result = service.archive(memory_id, actor="cli")
    else:
        raise ValueError(action)
    _print_payload({"memory": result.memory.model_dump(mode="python"), "warnings": result.warnings, "budget": result.budget, "audit": result.audit}, json_mode=json_mode)


def _print_payload(payload: dict[str, object], *, json_mode: bool) -> None:
    rendered = json.dumps(payload, ensure_ascii=True, indent=2)
    if json_mode:
        console.print(rendered)
        return
    console.print(rendered)


__all__ = [
    "memory_archive_main",
    "memory_approve_main",
    "memory_audit_main",
    "memory_compact_apply_main",
    "memory_compact_preview_main",
    "memory_get_main",
    "memory_merge_apply_main",
    "memory_merge_preview_main",
    "memory_pending_main",
    "memory_propose_main",
    "memory_provider_status_main",
    "memory_reject_main",
    "memory_replace_main",
    "memory_search_main",
    "memory_snapshot_main",
    "memory_sync_main",
]
