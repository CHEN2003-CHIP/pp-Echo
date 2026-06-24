from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from pp_agent.observability.store import TraceStore

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{0,160}$")


def mount_trace_routes(app, active_workspace: Callable[[], Path]) -> None:
    """
    挂载 TraceInspect 所需的 FastAPI 路由。

    路由只读取当前 workspace 下的 .pp-agent/traces，不接受外部路径参数。run_id 和
    session_id 均按普通标识符过滤，避免路径穿越或读取其它工作区 trace。
    """

    from fastapi import HTTPException

    def store() -> TraceStore:
        return TraceStore(active_workspace())

    def clamp_limit(limit: int) -> int:
        return max(1, min(200, int(limit)))

    def clean_session_id(session_id: Optional[str]) -> Optional[str]:
        if session_id is None or session_id == "":
            return None
        if not SESSION_ID_RE.match(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id")
        return session_id

    def dump_detail(run_id: str) -> dict:
        try:
            detail = store().read_run(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Trace run not found: {run_id}") from exc
        return detail.model_dump(mode="json")

    @app.get("/api/traces")
    def list_traces(limit: int = 50, session_id: Optional[str] = None) -> dict:
        runs = store().list_runs(limit=clamp_limit(limit), session_id=clean_session_id(session_id))
        return {"runs": [item.model_dump(mode="json") for item in runs]}

    @app.get("/api/traces/latest")
    def latest_trace(session_id: Optional[str] = None) -> dict:
        latest = store().find_latest_run(session_id=clean_session_id(session_id))
        if latest is None:
            raise HTTPException(status_code=404, detail="No trace run found")
        return latest.model_dump(mode="json")

    @app.get("/api/traces/{run_id}")
    def trace_detail(run_id: str) -> dict:
        return dump_detail(run_id)

    @app.get("/api/traces/{run_id}/summary")
    def trace_summary(run_id: str) -> dict:
        return dump_detail(run_id)["summary"]

    @app.get("/api/traces/{run_id}/spans")
    def trace_spans(run_id: str) -> dict:
        return {"spans": dump_detail(run_id)["spans"]}

    @app.get("/api/traces/{run_id}/events")
    def trace_events(run_id: str) -> dict:
        return {"events": dump_detail(run_id)["events"]}

    @app.get("/api/traces/{run_id}/context-pack")
    def trace_context_pack(run_id: str) -> dict:
        events = dump_detail(run_id)["events"]
        context_events = [
            event
            for event in events
            if event.get("name") == "context_built" and isinstance(event.get("payload", {}).get("details"), dict)
        ]
        if not context_events:
            raise HTTPException(status_code=404, detail="ContextPack v3 payload not found")
        details = context_events[-1]["payload"]["details"]
        return {
            "context_payload_version": details.get("context_payload_version"),
            "pipeline_mode": details.get("pipeline_mode"),
            "pipeline_used": details.get("pipeline_used"),
            "fallback_reason": details.get("fallback_reason"),
            "diff_summary": details.get("diff_summary") or {},
            "context": details.get("context") or {},
            "context_pack_v3": details.get("context_pack_v3") or {},
        }

    @app.get("/api/sessions/{session_id}/traces")
    def session_traces(session_id: str, limit: int = 20) -> dict:
        runs = store().list_runs(limit=clamp_limit(limit), session_id=clean_session_id(session_id))
        return {"runs": [item.model_dump(mode="json") for item in runs]}
