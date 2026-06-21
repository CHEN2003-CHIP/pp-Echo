from __future__ import annotations

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from pp_agent.app import bootstrap
from pp_agent.config import ConfigValidationError, get_config_manager
from pp_agent.config.schema import config_error
from pp_agent.extensions.index import extension_search_roots, load_extensions
from pp_agent.memory.file_memory_store import FileMemoryAccessError
from pp_agent.memory.file_memory_tools import build_file_memory_search_engine, build_file_memory_store
from pp_agent.memory.file_memory_search import FileMemorySearchRequest
from pp_agent.mcp.config import MCPConfigDocument, MCPServerConfig, load_mcp_config
from pp_agent.skills.index import load_skills, skill_search_roots
from pp_agent.storage.sessions import SNAPSHOT_EVENT


class CapabilitySettingsPatch(BaseModel):
    capabilities: dict[str, Any] = Field(default_factory=dict)


class MCPServerRequest(BaseModel):
    name: str
    description: str = ""
    intent_tags: list[str] = Field(default_factory=list)
    auto_match_examples: list[str] = Field(default_factory=list)
    transport: Optional[str] = None
    protocol: str = "auto"
    command: Optional[str] = None
    args: list[str] = Field(default_factory=list)
    url: Optional[str] = None
    headers: dict[str, str] = Field(default_factory=dict)
    bearer_token: Optional[str] = None
    bearer_token_env: Optional[str] = None
    env: dict[str, str] = Field(default_factory=dict)
    cwd: Optional[str] = None
    is_remote: bool = False
    requires_auth: bool = False
    approval_mode: str = "default"
    idle_timeout_seconds: int = 300
    timeout_seconds: int = 30


class SkillRequest(BaseModel):
    name: str
    description: str
    body: str = ""


class PluginRequest(BaseModel):
    name: str
    description: str
    entrypoint: Optional[str] = None
    provides: list[str] = Field(default_factory=list)


_LOG_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[T ][^ ]+)?\s*(?:\[(?P<bracket_level>[A-Z]+)\]|(?P<level>DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL))?\s*(?P<message>.*)$"
)
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def mount_capability_config_routes(app, active_workspace) -> None:
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    def workspace() -> Path:
        return active_workspace().resolve()

    def validation_error(exc: ConfigValidationError):
        return HTTPException(status_code=400, detail={"message": str(exc), "errors": exc.errors})

    @app.get("/api/logs")
    def logs(
        level: Optional[str] = None,
        source: Optional[str] = None,
        session_id: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        entries = _read_log_entries(workspace(), limit=max(1, min(1000, int(limit))))
        entries = _filter_log_entries(entries, level=level, source=source, session_id=session_id, search=search)
        return {"logs": entries[-max(1, min(1000, int(limit))) :], "sources": sorted({str(item.get("source") or "") for item in entries if item.get("source")})}

    @app.get("/api/memory/status")
    def memory_status() -> dict[str, Any]:
        """Return UI-facing status for each memory layer.

        ``enabled`` is kept for older Web clients and mirrors the stable
        Episodic Memory history switch. ``episodic_memory_enabled`` reports the
        effective retrieval layer state after the nested episodic toggle is
        applied, while Core Memory and File Memory remain separate statuses.
        """

        settings = _safe_memory_settings(workspace())
        store = build_file_memory_store(workspace(), settings=settings)
        files = store.scan_memory_files()
        indexed = store.indexed_files()
        episodic_enabled = settings.memory.enable and settings.memory.episodic_memory.enabled
        return {
            "workspace": str(workspace()),
            "enabled": settings.memory.enable,
            "episodic_memory_enabled": episodic_enabled,
            "episodic_history_enabled": settings.memory.enable,
            "core_memory_enabled": settings.memory.core_memory.enabled,
            "file_memory_enabled": settings.memory.file_memory_enable,
            "search_enabled": settings.memory.file_memory_search_enable,
            "memory_root": str(settings.file_memory_root_path()),
            "index_path": str(settings.file_memory_index_path()),
            "global_root": str(settings.global_dir),
            "file_count": len(files),
            "indexed_file_count": len(indexed),
            "files": [_memory_file_payload(item) for item in files],
        }

    @app.get("/api/memory/search")
    def memory_search(query: str = "", scope: str = "auto", limit: int = 8) -> dict[str, Any]:
        settings = _safe_memory_settings(workspace())
        search_settings = settings.model_copy(deep=True)
        search_settings.memory.file_memory_allow_remote_embedding = False
        engine = build_file_memory_search_engine(workspace(), settings=search_settings)
        result = engine.search(
            FileMemorySearchRequest(
                query=query,
                top_k=max(1, min(20, int(limit))),
                mode="bm25",
                scope=scope if scope in {"auto", "workspace", "global", "all"} else "auto",  # type: ignore[arg-type]
            )
        )
        return result.to_dict(include_debug=False)

    @app.get("/api/memory/files")
    def memory_files() -> dict[str, Any]:
        settings = _safe_memory_settings(workspace())
        store = build_file_memory_store(workspace(), settings=settings)
        return {"files": [_memory_file_payload(item) for item in store.scan_memory_files()]}

    @app.get("/api/memory/file")
    def memory_file(path: str, start_line: Optional[int] = None, line_count: Optional[int] = None) -> dict[str, Any]:
        settings = _safe_memory_settings(workspace())
        store = build_file_memory_store(workspace(), settings=settings)
        try:
            read = store.read_line_range(path, start_line=start_line, line_count=line_count)
            return {"path": read.path, "line_start": read.line_start, "line_end": read.line_end, "content": read.content}
        except FileMemoryAccessError as exc:
            raise HTTPException(status_code=400, detail={"message": exc.message, "errors": [config_error("path", exc.code, exc.message)]}) from exc

    @app.get("/api/capability-config")
    def capability_config() -> dict[str, Any]:
        return _capability_inventory(workspace())

    @app.patch("/api/capability-config/settings")
    def update_capability_settings(request: CapabilitySettingsPatch) -> dict[str, Any]:
        try:
            patch = _capability_settings_patch(request.capabilities)
            snapshot = get_config_manager(workspace()).patch_project_config(patch)
            return {"snapshot": snapshot.model_dump(mode="json"), "inventory": _capability_inventory(workspace())}
        except ConfigValidationError as exc:
            raise validation_error(exc) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/mcp/servers")
    def create_mcp_server(request: MCPServerRequest) -> dict[str, Any]:
        try:
            _upsert_mcp_server(workspace(), request, original_name=None)
            return _capability_inventory(workspace())
        except ConfigValidationError as exc:
            raise validation_error(exc) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/mcp/servers/{name}")
    def update_mcp_server(name: str, request: MCPServerRequest) -> dict[str, Any]:
        try:
            _upsert_mcp_server(workspace(), request, original_name=name)
            return _capability_inventory(workspace())
        except ConfigValidationError as exc:
            raise validation_error(exc) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/mcp/servers/{name}")
    def delete_mcp_server(name: str) -> dict[str, Any]:
        try:
            _delete_mcp_server(workspace(), name)
            return _capability_inventory(workspace())
        except ConfigValidationError as exc:
            raise validation_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/skills")
    def create_skill(request: SkillRequest) -> dict[str, Any]:
        try:
            _write_skill(workspace(), request, original_name=None)
            return _capability_inventory(workspace())
        except ConfigValidationError as exc:
            raise validation_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/skills/{name}")
    def update_skill(name: str, request: SkillRequest) -> dict[str, Any]:
        try:
            _write_skill(workspace(), request, original_name=name)
            return _capability_inventory(workspace())
        except ConfigValidationError as exc:
            raise validation_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/plugins")
    def create_plugin(request: PluginRequest) -> dict[str, Any]:
        try:
            _write_plugin(workspace(), request, original_name=None)
            return _capability_inventory(workspace())
        except ConfigValidationError as exc:
            raise validation_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/plugins/{name}")
    def update_plugin(name: str, request: PluginRequest) -> dict[str, Any]:
        try:
            _write_plugin(workspace(), request, original_name=name)
            return _capability_inventory(workspace())
        except ConfigValidationError as exc:
            raise validation_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/favicon.ico")
    def favicon():
        path = Path(__file__).resolve().parents[4] / "web" / "public" / "favicon.svg"
        if not path.exists():
            raise HTTPException(status_code=404, detail="favicon not found")
        return FileResponse(path, media_type="image/svg+xml")


def _capability_inventory(workspace: Path) -> dict[str, Any]:
    settings = bootstrap.load_settings(workspace)
    project_dir = workspace / ".pp-agent"
    user_root = settings.global_dir
    mcp_paths = settings.capabilities.mcp.resolved_config_paths(project_dir)
    mcp_errors: list[dict[str, str]] = []
    try:
        mcp_document = load_mcp_config(project_dir, config_paths=mcp_paths)
        mcp_servers = [
            {
                **server.model_dump(mode="json"),
                "resolved_transport": server.resolved_transport(),
                "enabled": settings.capabilities.mcp.enable and settings.capabilities.mcp.includes_server(server.name),
                "filtered": not settings.capabilities.mcp.includes_server(server.name),
            }
            for server in mcp_document.servers
        ]
        mcp_settings = mcp_document.settings.model_dump(mode="json")
    except Exception as exc:
        mcp_servers = []
        mcp_settings = {}
        mcp_errors.append({"path": "capabilities.mcp.config_paths", "code": "load_error", "message": str(exc)})

    skill_roots = skill_search_roots(workspace, user_root, config=settings.capabilities.skills)
    extension_roots = extension_search_roots(workspace, user_root, config=settings.capabilities.extensions)
    skills = load_skills(workspace, user_root, config=settings.capabilities.skills, search_roots=skill_roots)
    extensions = load_extensions(workspace, user_root, config=settings.capabilities.extensions, search_roots=extension_roots)
    return {
        "workspace": str(workspace),
        "settings": {
            "mcp": settings.capabilities.mcp.model_dump(mode="json"),
            "skills": settings.capabilities.skills.model_dump(mode="json"),
            "plugins": settings.capabilities.extensions.model_dump(mode="json"),
        },
        "mcp": {
            "enabled": settings.capabilities.mcp.enable,
            "config_paths": [str(path) for path in mcp_paths],
            "settings": mcp_settings,
            "servers": mcp_servers,
            "errors": mcp_errors,
        },
        "skills": {
            "roots": [root.model_dump(mode="json") for root in skill_roots],
            "items": [_skill_payload(item, settings.capabilities.skills) for item in skills.values()],
        },
        "plugins": {
            "roots": [root.model_dump(mode="json") for root in extension_roots],
            "items": [_plugin_payload(item, settings.capabilities.extensions) for item in extensions.values()],
        },
    }


def _safe_memory_settings(workspace: Path):
    settings = bootstrap.load_settings(workspace)
    try:
        settings.global_dir.resolve()
    except (OSError, PermissionError):
        settings = settings.model_copy(deep=True)
        fallback = settings.project_dir / "global"
        fallback.mkdir(parents=True, exist_ok=True)
        settings.global_dir = fallback
    return settings


def _skill_payload(descriptor: Any, config: Any) -> dict[str, Any]:
    body = ""
    try:
        raw = Path(descriptor.path).read_text(encoding="utf-8")
        if raw.startswith("---"):
            body = raw.split("---", 2)[2].strip()
    except OSError:
        body = ""
    return {
        "name": descriptor.name,
        "description": descriptor.description,
        "path": str(descriptor.path),
        "body": body,
        "origin_type": descriptor.origin_type,
        "root_name": descriptor.root_name,
        "precedence": descriptor.precedence,
        "enabled": config.includes_name(descriptor.name),
        "filtered": not config.includes_name(descriptor.name),
    }


def _plugin_payload(descriptor: Any, config: Any) -> dict[str, Any]:
    return {
        "name": descriptor.name,
        "description": descriptor.description,
        "path": str(descriptor.path) if descriptor.path else "",
        "entrypoint": descriptor.entrypoint,
        "provides": list(descriptor.provides),
        "origin_type": descriptor.origin_type,
        "root_name": descriptor.root_name,
        "precedence": descriptor.precedence,
        "enabled": config.includes_name(descriptor.name),
        "filtered": not config.includes_name(descriptor.name),
    }


def _capability_settings_patch(capabilities: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "mcp": {"enable", "config_paths", "server_filters"},
        "skills": {"enable_project", "enable_user", "enable_builtin", "custom_directories", "ignored", "include"},
        "extensions": {"enable_project", "enable_user", "enable_builtin", "custom_directories", "ignored", "include"},
        "plugins": {"enable_project", "enable_user", "enable_builtin", "custom_directories", "ignored", "include"},
    }
    patch: dict[str, Any] = {"capabilities": {}}
    errors: list[dict[str, str]] = []
    for group, values in capabilities.items():
        target = "extensions" if group == "plugins" else group
        if target not in allowed or not isinstance(values, dict):
            errors.append(config_error(f"capabilities.{group}", "unknown_path", "Unsupported capability settings group"))
            continue
        unknown = set(values) - allowed[target]
        if unknown:
            errors.extend(config_error(f"capabilities.{group}.{key}", "unknown_path", "Unsupported capability setting") for key in sorted(unknown))
        patch["capabilities"][target] = {key: value for key, value in values.items() if key in allowed[target]}
    if errors:
        raise ConfigValidationError(errors)
    return patch


def _read_log_entries(workspace: Path, *, limit: int) -> list[dict[str, Any]]:
    logs_dir = workspace / ".pp-agent" / "logs"
    entries = []
    entries.extend(_read_timeline_log_entries(workspace, limit=limit))
    entries.extend(_read_session_jsonl_log_entries(workspace, limit=limit))
    if not logs_dir.exists():
        return sorted(entries, key=_log_entry_sort_key)[-limit:]
    for path in sorted([*logs_dir.glob("*.jsonl"), *logs_dir.glob("*.log")], key=lambda item: item.stat().st_mtime):
        for line in _tail_lines(path, limit):
            entry = _parse_log_line(line, source=path.name)
            if entry:
                entries.append(entry)
    return sorted(entries, key=_log_entry_sort_key)[-limit:]


def _read_timeline_log_entries(workspace: Path, *, limit: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        timeline = bootstrap.timeline_store_for(workspace).list_recent(limit=limit)
    except (OSError, ValueError):
        return entries
    for item in timeline:
        level = "error" if item.is_error else "info"
        message = item.message or item.event_type
        details = {
            "event_type": item.event_type,
            "turn_id": item.turn_id,
            "phase": item.phase,
            "tool_name": item.tool_name,
            "details": item.details,
        }
        entries.append(
            {
                "timestamp": item.created_at,
                "level": level,
                "source": "timeline",
                "session_id": item.session_id,
                "message": message,
                "details": details,
                "raw": json.dumps(item.model_dump(mode="json"), ensure_ascii=False),
            }
        )
    return entries


def _read_session_jsonl_log_entries(workspace: Path, *, limit: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        session_root = bootstrap.session_store_for(workspace).root
    except (OSError, ValueError):
        return entries
    for path in sorted(session_root.glob("*.jsonl"), key=lambda item: item.stat().st_mtime):
        for line in _tail_lines(path, limit):
            entry = _parse_session_event_line(line, source=path.name)
            if entry:
                entries.append(entry)
    return entries


def _tail_lines(path: Path, limit: int) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []


def _parse_log_line(line: str, *, source: str) -> dict[str, Any] | None:
    if not line.strip():
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return {
            "timestamp": payload.get("timestamp") or payload.get("time") or payload.get("created_at"),
            "level": str(payload.get("level") or payload.get("severity") or "info").lower(),
            "source": str(payload.get("logger") or payload.get("source") or source),
            "session_id": payload.get("session_id"),
            "message": str(payload.get("message") or payload.get("msg") or ""),
            "details": payload.get("details"),
            "raw": line,
        }
    match = _LOG_LINE_RE.match(line)
    level = (match.group("bracket_level") or match.group("level") or "info").lower() if match else "info"
    message = (match.group("message") or line).strip() if match else line.strip()
    timestamp = match.group("timestamp") if match else None
    return {"timestamp": timestamp, "level": level, "source": source, "session_id": None, "message": message, "details": None, "raw": line}


def _parse_session_event_line(line: str, *, source: str) -> dict[str, Any] | None:
    if not line.strip():
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    event_type = str(payload.get("type") or payload.get("event_type") or "").strip()
    if not event_type:
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    timestamp = payload.get("at") or payload.get("timestamp") or payload.get("created_at")
    level = "error" if any(token in event_type.lower() for token in ("error", "failed", "rejected", "cancel")) else "info"
    return {
        "timestamp": timestamp,
        "level": level,
        "source": "session-jsonl",
        "session_id": payload.get("session_id"),
        "message": _session_event_message(event_type, data),
        "details": {
            "event_type": event_type,
            "source_file": source,
            "data": data,
        },
        "raw": line,
    }


def _session_event_message(event_type: str, data: dict[str, Any]) -> str:
    kind = event_type.replace("_", " ").strip()
    if event_type in {"metadata_created", "metadata_updated"}:
        model = data.get("model")
        model_name = model.get("model") if isinstance(model, dict) else None
        if model_name:
            return f"{kind}: {model_name}"
        return kind
    if event_type == "messages_appended":
        count = data.get("count")
        if isinstance(count, int):
            return f"{kind}: +{count} messages"
        return kind
    if event_type == "messages_replaced":
        count = data.get("count")
        if isinstance(count, int):
            return f"{kind}: {count} messages"
        return kind
    if event_type == "turn_node_added":
        node_type = data.get("entry_type") or data.get("type")
        turn_id = data.get("id")
        bits = [kind]
        if node_type:
            bits.append(str(node_type))
        if turn_id:
            bits.append(str(turn_id))
        return " ".join(bits)
    if event_type == "turn_nodes_replaced":
        count = data.get("count")
        return f"{kind}: {count} nodes" if isinstance(count, int) else kind
    if event_type == "head_updated":
        head_id = data.get("active_head_id")
        return f"{kind}: {head_id}" if head_id else kind
    if event_type == "compaction_recorded":
        count = data.get("summarized_message_count")
        return f"{kind}: {count} messages" if isinstance(count, int) else kind
    if event_type == "pending_state_updated":
        pending_plan_token = data.get("pending_plan_token")
        pending_tool_calls = data.get("pending_tool_calls")
        queued_messages = data.get("queued_messages")
        bits = [kind]
        if pending_plan_token:
            bits.append(f"plan={pending_plan_token}")
        if isinstance(pending_tool_calls, list):
            bits.append(f"tools={len(pending_tool_calls)}")
        if isinstance(queued_messages, list):
            bits.append(f"queued={len(queued_messages)}")
        return " ".join(bits)
    if event_type == SNAPSHOT_EVENT:
        messages = data.get("messages")
        turn_nodes = data.get("turn_nodes")
        bits = [kind]
        if isinstance(messages, list):
            bits.append(f"messages={len(messages)}")
        if isinstance(turn_nodes, list):
            bits.append(f"turns={len(turn_nodes)}")
        return " ".join(bits)
    return kind


def _log_entry_sort_key(entry: dict[str, Any]) -> tuple[float, str, str]:
    timestamp = entry.get("timestamp")
    if isinstance(timestamp, (int, float)):
        numeric = float(timestamp)
    elif isinstance(timestamp, str):
        numeric = _parse_timestamp_value(timestamp)
    else:
        numeric = 0.0
    return (numeric, str(entry.get("source") or ""), str(entry.get("message") or ""))


def _parse_timestamp_value(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return 0.0


def _memory_file_payload(file: Any) -> dict[str, Any]:
    return {
        "path": file.path,
        "mtime": file.mtime,
        "size": file.size,
        "content_hash": file.content_hash,
        "scope": _memory_scope(file.path),
    }


def _memory_scope(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized == "global/MEMORY.md":
        return "global"
    if normalized == "MEMORY.md":
        return "workspace"
    if normalized.startswith("memory/daily/"):
        return "daily"
    return "detailed"


def _filter_log_entries(
    entries: list[dict[str, Any]],
    *,
    level: str | None,
    source: str | None,
    session_id: str | None,
    search: str | None,
) -> list[dict[str, Any]]:
    level = (level or "").strip().lower()
    source = (source or "").strip().lower()
    session_id = (session_id or "").strip()
    search = (search or "").strip().lower()
    result = entries
    if level and level != "all":
        result = [item for item in result if str(item.get("level") or "").lower() == level]
    if source and source != "all":
        result = [item for item in result if source in str(item.get("source") or "").lower()]
    if session_id:
        result = [item for item in result if str(item.get("session_id") or "") == session_id]
    if search:
        result = [item for item in result if search in json.dumps(item, ensure_ascii=False).lower()]
    return result


def _upsert_mcp_server(workspace: Path, request: MCPServerRequest, *, original_name: str | None) -> None:
    name = _validate_name(request.name, "mcp.server.name")
    server = MCPServerConfig(**request.model_dump())
    transport = server.resolved_transport()
    if transport == "stdio" and not server.command:
        raise ConfigValidationError([config_error("command", "required", "stdio MCP servers require command")])
    if transport == "http" and not server.url:
        raise ConfigValidationError([config_error("url", "required", "http MCP servers require url")])
    server.resolved_protocol()
    path = _project_mcp_path(workspace)
    document = _read_project_mcp_document(path)
    if original_name and not any(item.name == original_name for item in document.servers):
        raise ConfigValidationError([config_error("name", "not_found", f"MCP server not found: {original_name}")])
    servers = [item for item in document.servers if item.name != (original_name or name)]
    if any(item.name == name for item in servers):
        raise ConfigValidationError([config_error("name", "duplicate", f"MCP server already exists: {name}")])
    if not original_name and any(item.name == name for item in document.servers):
        raise ConfigValidationError([config_error("name", "duplicate", f"MCP server already exists: {name}")])
    servers.append(server)
    _write_project_mcp_document(path, MCPConfigDocument(settings=document.settings, servers=sorted(servers, key=lambda item: item.name)))


def _delete_mcp_server(workspace: Path, name: str) -> None:
    _validate_name(name, "mcp.server.name")
    path = _project_mcp_path(workspace)
    document = _read_project_mcp_document(path)
    servers = [item for item in document.servers if item.name != name]
    if len(servers) == len(document.servers):
        raise ConfigValidationError([config_error("name", "not_found", f"MCP server not found: {name}")])
    _write_project_mcp_document(path, MCPConfigDocument(settings=document.settings, servers=servers))


def _project_mcp_path(workspace: Path) -> Path:
    return workspace / ".pp-agent" / "mcp.json"


def _read_project_mcp_document(path: Path) -> MCPConfigDocument:
    if not path.exists():
        return MCPConfigDocument()
    return load_mcp_config(path.parent, config_paths=[path])


def _write_project_mcp_document(path: Path, document: MCPConfigDocument) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = document.model_dump(mode="json")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_skill(workspace: Path, request: SkillRequest, *, original_name: str | None) -> None:
    name = _validate_name(request.name, "skills.name")
    if not request.description.strip():
        raise ConfigValidationError([config_error("description", "required", "Description is required")])
    base = _safe_project_dir(workspace, "skills")
    target_dir = _safe_child_dir(base, name)
    if original_name:
        original_dir = _safe_child_dir(base, _validate_name(original_name, "skills.name"))
        if not original_dir.exists():
            raise ConfigValidationError([config_error("name", "not_found", f"Skill not found: {original_name}")])
        if original_dir.exists() and original_dir != target_dir:
            original_dir.rename(target_dir)
    elif target_dir.exists():
        raise ConfigValidationError([config_error("name", "duplicate", f"Skill already exists: {name}")])
    target_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {request.description.strip()}\n---\n\n{request.body.strip()}\n"
    (target_dir / "SKILL.md").write_text(content, encoding="utf-8")


def _write_plugin(workspace: Path, request: PluginRequest, *, original_name: str | None) -> None:
    name = _validate_name(request.name, "plugins.name")
    if not request.description.strip():
        raise ConfigValidationError([config_error("description", "required", "Description is required")])
    base = _safe_project_dir(workspace, ".pp-agent/extensions")
    target_dir = _safe_child_dir(base, name)
    if original_name:
        original_dir = _safe_child_dir(base, _validate_name(original_name, "plugins.name"))
        if not original_dir.exists():
            raise ConfigValidationError([config_error("name", "not_found", f"Plugin not found: {original_name}")])
        if original_dir.exists() and original_dir != target_dir:
            original_dir.rename(target_dir)
    elif target_dir.exists():
        raise ConfigValidationError([config_error("name", "duplicate", f"Plugin already exists: {name}")])
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": name,
        "description": request.description.strip(),
        "entrypoint": request.entrypoint or None,
        "provides": request.provides,
    }
    (target_dir / "EXTENSION.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_name(name: str, path: str) -> str:
    value = str(name or "").strip()
    if not value:
        raise ConfigValidationError([config_error(path, "required", "Name is required")])
    if not _SAFE_NAME_RE.match(value):
        raise ConfigValidationError([config_error(path, "value", "Use letters, numbers, dots, underscores, or dashes")])
    return value


def _safe_project_dir(workspace: Path, relative: str) -> Path:
    base = (workspace / relative).resolve()
    workspace_root = workspace.resolve()
    if workspace_root not in base.parents and base != workspace_root:
        raise ConfigValidationError([config_error(relative, "path", "Path must stay inside the workspace")])
    return base


def _safe_child_dir(base: Path, name: str) -> Path:
    child = (base / name).resolve()
    if base not in child.parents and child != base:
        raise ConfigValidationError([config_error("name", "path", "Path must stay inside the capability directory")])
    return child
