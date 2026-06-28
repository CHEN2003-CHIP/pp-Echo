from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from pp_agent.memory.embedding import DashScopeEmbeddingProvider, NoopEmbeddingProvider
from pp_agent.memory.file_memory_chunker import MarkdownFileChunker
from pp_agent.memory.file_memory_search import FileMemorySearchEngine, FileMemorySearchRequest
from pp_agent.memory.file_memory_store import FileMemoryAccessError, FileMemoryIndexStore
from pp_agent.memory.file_memory_vector import ChromaFileMemoryVectorIndex, NoopFileMemoryVectorIndex
from pp_agent.storage.settings import Settings
from pp_agent.tools.base import ToolExecutionResult
from pp_agent.tools.policy import PermissionDomain
from pp_agent.tools.registry import ToolRegistry


logger = logging.getLogger(__name__)


MEMORY_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "top_k": {"type": "integer", "default": 5},
        "mode": {"type": "string", "enum": ["auto", "hybrid", "bm25", "vector"], "default": "auto"},
        "scope": {"type": "string", "enum": ["auto", "workspace", "global", "all"], "default": "auto"},
        "include_debug": {"type": "boolean", "default": False},
    },
    "required": ["query"],
}

MEMORY_GET_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "start_line": {"type": "integer"},
        "line_count": {"type": "integer"},
    },
    "required": ["path"],
}


def register_file_memory_tools(registry: ToolRegistry, *, settings: Settings | None = None) -> None:
    settings = settings or Settings.load(registry.workspace)
    if not settings.memory.file_memory_enable or not settings.memory.file_memory_search_enable:
        return
    search_settings = settings.model_copy(deep=True)
    search_settings.memory.file_memory_allow_remote_embedding = False
    registry.register_function_tool(
        name="memory_search",
        description=(
            "Search Markdown long-term memory files (MEMORY.md and memory/**/*.md) with local BM25 recall. "
            "Use before answering prior preferences, previous project decisions, old bugs, long-running tasks, or remembered facts."
        ),
        parameters=MEMORY_SEARCH_SCHEMA,
        executor=lambda workspace, arguments: memory_search_executor(workspace, arguments, settings=search_settings),
        category="memory",
        permission_domain=PermissionDomain.READ,
        tool_family="extension",
        exact_effect_mode="auto",
        non_side_effectful=True,
        known_safe_inspect=True,
        requests_network_hint=False,
    )
    registry.register_function_tool(
        name="memory_get",
        description=(
            "Read an exact line range from Markdown memory files returned by memory_search. "
            "Only MEMORY.md and memory/**/*.md are allowed; do not use this to read arbitrary workspace files."
        ),
        parameters=MEMORY_GET_SCHEMA,
        executor=lambda workspace, arguments: memory_get_executor(workspace, arguments, settings=settings),
        category="memory",
        permission_domain=PermissionDomain.READ,
        tool_family="extension",
        exact_effect_mode="auto",
        non_side_effectful=True,
        known_safe_inspect=True,
        requests_network_hint=False,
    )


def memory_search_executor(workspace: Path, arguments: dict[str, Any], *, settings: Settings | None = None) -> ToolExecutionResult:
    settings = settings or Settings.load(workspace)
    if not settings.memory.file_memory_enable or not settings.memory.file_memory_search_enable:
        payload = {
            "query": str(arguments.get("query") or ""),
            "mode": "bm25",
            "semantic_available": False,
            "bm25_available": False,
            "results": [],
            "warnings": ["File memory search is disabled by configuration."],
        }
        return _json_result("memory_search", payload)
    top_k = int(arguments.get("top_k") or settings.memory.file_memory_top_k)
    mode = str(arguments.get("mode") or "auto")
    if mode not in {"auto", "hybrid", "bm25", "vector"}:
        mode = "auto"
    include_debug = bool(arguments.get("include_debug", False))
    scope = str(arguments.get("scope") or "auto")
    if scope not in {"auto", "workspace", "global", "all"}:
        scope = "auto"
    query = str(arguments.get("query") or "")
    try:
        engine = build_file_memory_search_engine(workspace, settings=settings)
        result = engine.search(
            FileMemorySearchRequest(
                query=query,
                top_k=max(1, top_k),
                mode=mode,  # type: ignore[arg-type]
                scope=scope,  # type: ignore[arg-type]
                include_debug=include_debug,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("File memory search failed and returned a structured error: %s", exc)
        return _json_result(
            "memory_search",
            {
                "query": query,
                "mode": mode,
                "semantic_available": False,
                "bm25_available": False,
                "results": [],
                "warnings": ["File memory search failed."],
                "error": {"code": "search_failed", "message": str(exc)},
            },
            is_error=True,
        )
    return _json_result("memory_search", result.to_dict(include_debug=include_debug))


def memory_get_executor(workspace: Path, arguments: dict[str, Any], *, settings: Settings | None = None) -> ToolExecutionResult:
    settings = settings or Settings.load(workspace)
    store = build_file_memory_store(workspace, settings=settings)
    raw_path = str(arguments.get("path") or "")
    try:
        read = store.read_line_range(
            raw_path,
            start_line=arguments.get("start_line"),
            line_count=arguments.get("line_count"),
        )
        return _json_result(
            "memory_get",
            {
                "path": read.path,
                "line_start": read.line_start,
                "line_end": read.line_end,
                "content": read.content,
            },
        )
    except FileMemoryAccessError as exc:
        return _json_result(
            "memory_get",
            {
                "path": raw_path,
                "error": {"code": exc.code, "message": exc.message},
            },
            is_error=True,
        )
    except OSError as exc:
        return _json_result(
            "memory_get",
            {
                "path": raw_path,
                "error": {"code": "read_failed", "message": str(exc)},
            },
            is_error=True,
        )


def build_file_memory_search_engine(workspace: Path, *, settings: Settings | None = None) -> FileMemorySearchEngine:
    settings = settings or Settings.load(workspace)
    memory = settings.memory
    return FileMemorySearchEngine(
        store=build_file_memory_store(workspace, settings=settings),
        chunker=MarkdownFileChunker(
            target_chars=memory.file_memory_chunk_target_chars,
            overlap_lines=memory.file_memory_chunk_overlap_lines,
        ),
        embedding_provider=_embedding_provider(settings),
        vector_index=_vector_index(settings),
        vector_weight=memory.file_memory_vector_weight,
        bm25_weight=memory.file_memory_bm25_weight,
        candidate_multiplier=memory.file_memory_candidate_multiplier,
        max_per_file=memory.file_memory_max_per_file,
        snippet_chars=memory.file_memory_snippet_chars,
        sync_on_search=memory.file_memory_sync_on_search,
        allow_remote_embedding=memory.file_memory_allow_remote_embedding,
    )


def build_file_memory_store(workspace: Path, *, settings: Settings | None = None) -> FileMemoryIndexStore:
    settings = settings or Settings.load(workspace)
    return FileMemoryIndexStore(
        workspace=settings.workspace,
        index_path=settings.file_memory_index_path(),
        memory_root=settings.file_memory_root_path(),
        global_root=settings.global_dir,
        extra_paths=settings.memory.file_memory_extra_paths,
        busy_timeout_ms=settings.memory.sqlite_busy_timeout_ms,
    )


def _embedding_provider(settings: Settings):
    memory = settings.memory
    if not (memory.file_memory_allow_remote_embedding and memory.embedding_enable and memory.embedding_provider == "dashscope"):
        return NoopEmbeddingProvider()
    return DashScopeEmbeddingProvider(
        api_key_env=memory.dashscope_api_key_env,
        model=memory.embedding_model,
    )


def _vector_index(settings: Settings):
    memory = settings.memory
    if not (memory.file_memory_allow_remote_embedding and memory.vector_enable and memory.vector_backend == "chroma"):
        return NoopFileMemoryVectorIndex()
    try:
        return ChromaFileMemoryVectorIndex(
            path=settings.chroma_dir_path(),
            collection_name=_file_memory_chroma_collection_name(settings),
        )
    except RuntimeError as exc:
        logger.warning("File memory vector index disabled because Chroma is unavailable: %s", exc)
        return NoopFileMemoryVectorIndex()


def _file_memory_chroma_collection_name(settings: Settings) -> str:
    memory = settings.memory
    base = memory.file_memory_chroma_collection or "pp_agent_file_memory"
    if not memory.chroma_collection_per_embedding:
        return _safe_chroma_collection_segment(base)
    suffix_source = f"{memory.embedding_provider}:{memory.embedding_model}"
    suffix = hashlib.sha256(suffix_source.encode("utf-8")).hexdigest()[:12]
    safe_base = _safe_chroma_collection_segment(base)
    max_base_len = 63 - len(suffix) - 1
    safe_base = safe_base[:max_base_len].rstrip("_-") or "ppagent"
    return f"{safe_base}_{suffix}"


def _safe_chroma_collection_segment(value: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_-").lower()
    if not segment:
        return "ppagent"
    if len(segment) < 3:
        segment = f"{segment}_collection"
    return segment


def _json_result(tool_name: str, payload: dict[str, object], *, is_error: bool = False) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_call_id="",
        tool_name=tool_name,
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        is_error=is_error,
        details=payload,
    )
