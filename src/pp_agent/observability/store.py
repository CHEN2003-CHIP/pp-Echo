from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pp_agent.observability.diagnosis import diagnose_trace
from pp_agent.observability.schema import TraceArtifact, TraceDetail, TraceEvent, TraceRun, TraceRunSummary, TraceSpan
from pp_agent.observability.summary import build_trace_summary


class TraceStore:
    """
    负责将结构化 Trace 追加写入 workspace 下的 .pp-agent/traces 目录。

    TraceStore 是持久化层，不关心 Runtime、ToolRegistry 或 Web UI 的业务逻辑。
    它只提供 append-only 写入和按 run_id 读取能力，保证即使 Agent 中途异常，
    已经产生的 span/event 仍然可以被 TraceInspect 页面读取和复盘。

    设计边界：
    - 所有路径都限制在当前 workspace 的 .pp-agent/traces 下。
    - JSONL 每行一个 JSON 对象，便于异常中断后保留已写记录。
    - 读取损坏行会加入 warnings，而不是让 API 整体 500。
    """

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.root = (self.workspace / ".pp-agent" / "traces").resolve()
        if not self._inside_workspace_trace_root(self.root):
            raise ValueError("Trace root must stay inside workspace/.pp-agent/traces")

    def append_record(self, run_id: str, record: dict[str, Any]) -> None:
        path = self._run_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def append_index(self, summary: TraceRunSummary) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._index_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n")

    def list_runs(self, limit: int = 50, session_id: str | None = None) -> list[TraceRunSummary]:
        warnings: list[str] = []
        latest: dict[str, TraceRunSummary] = {}
        capped_limit = max(1, min(200, int(limit)))
        for item in self._read_jsonl(self._index_path(), warnings):
            try:
                summary = TraceRunSummary(**item)
            except Exception:
                warnings.append("index contains an invalid summary row")
                continue
            if session_id and summary.session_id != session_id:
                continue
            latest[summary.run_id] = summary
        for summary in self._scan_run_summaries(limit=max(capped_limit * 3, 50), session_id=session_id):
            current = latest.get(summary.run_id)
            if current is None or summary.started_at >= current.started_at:
                latest[summary.run_id] = summary
        return sorted(latest.values(), key=lambda item: item.started_at, reverse=True)[:capped_limit]

    def read_run(self, run_id: str) -> TraceDetail:
        path = self._run_path(run_id)
        if not path.exists():
            raise FileNotFoundError(run_id)
        warnings: list[str] = []
        run: TraceRun | None = None
        spans: dict[str, TraceSpan] = {}
        events: list[TraceEvent] = []
        artifacts: list[TraceArtifact] = []
        for row in self._read_jsonl(path, warnings):
            kind = row.get("record_type")
            payload = row.get("data") if isinstance(row.get("data"), dict) else row
            try:
                if kind == "run_start" or kind == "run_end":
                    run = TraceRun(**payload)
                elif kind == "span_start" or kind == "span_end":
                    span = TraceSpan(**payload)
                    spans[span.span_id] = span
                elif kind == "event":
                    events.append(TraceEvent(**payload))
                elif kind == "artifact":
                    artifacts.append(TraceArtifact(**payload))
            except Exception as exc:
                warnings.append(f"invalid {kind or 'record'} row skipped: {exc}")
        detail = TraceDetail(run=run, spans=sorted(spans.values(), key=lambda item: item.started_at), events=events, artifacts=artifacts, warnings=warnings)
        detail.summary = build_trace_summary(detail)
        detail.diagnosis = diagnose_trace(detail)
        return detail

    def find_latest_run(self, session_id: str | None = None) -> TraceRunSummary | None:
        runs = self.list_runs(limit=1, session_id=session_id)
        return runs[0] if runs else None

    def _index_path(self) -> Path:
        return self.root / "index.jsonl"

    def _run_path(self, run_id: str) -> Path:
        safe = self._safe_run_id(run_id)
        # 日期目录由 run_id 首段之外的当前文件 mtime 不可靠，这里从 summary 读取前先采用 flat fallback。
        candidates = list(self.root.glob(f"????-??-??/{safe}.jsonl")) if self.root.exists() else []
        if candidates:
            return candidates[0].resolve()
        from datetime import datetime

        path = (self.root / datetime.utcnow().strftime("%Y-%m-%d") / f"{safe}.jsonl").resolve()
        if not self._inside_workspace_trace_root(path):
            raise ValueError("Trace path escapes workspace trace root")
        return path

    def _scan_run_summaries(self, limit: int, session_id: str | None = None) -> list[TraceRunSummary]:
        if not self.root.exists():
            return []
        candidates: list[Path] = []
        for path in self.root.glob("????-??-??/*.jsonl"):
            if path.name == "index.jsonl":
                continue
            try:
                path.resolve().relative_to(self.root)
            except ValueError:
                continue
            candidates.append(path)
        candidates.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0.0, reverse=True)
        summaries: list[TraceRunSummary] = []
        for path in candidates[: max(1, min(500, int(limit)))]:
            try:
                detail = self.read_run(path.stem)
            except Exception:
                continue
            if detail.summary is None:
                continue
            if session_id and detail.summary.session_id != session_id:
                continue
            summaries.append(detail.summary)
        return summaries

    def _safe_run_id(self, run_id: str) -> str:
        safe = "".join(ch for ch in str(run_id) if ch.isalnum() or ch in {"-", "_"})
        if not safe:
            raise ValueError("run_id is empty")
        return safe[:120]

    def _inside_workspace_trace_root(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
            return True
        except ValueError:
            return path.resolve() == self.root

    @staticmethod
    def _read_jsonl(path: Path, warnings: list[str]) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    item = json.loads(text)
                except json.JSONDecodeError:
                    warnings.append(f"{path.name}:{line_number} is not valid JSON")
                    continue
                if isinstance(item, dict):
                    rows.append(item)
                else:
                    warnings.append(f"{path.name}:{line_number} is not a JSON object")
        return rows
