from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from pp_agent.config import ConfigValidationError, get_config_manager
from pp_agent.storage.approvals import PendingActionStore, classify_pending_action, is_active_pending_action, pending_action_state
from pp_agent.storage.sessions import SessionStore


def _normalized_paths(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        text = str(value).replace("\\", "/").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def list_pending_patch_artifacts(
    pending_store: PendingActionStore,
    *,
    session_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    从待执行任务列表里，筛选出「AI 准备要打的文件补丁」，整理成前端能显示的待修改文件列表。
    """
    artifacts: list[dict[str, Any]] = []
    for item in pending_store.list():
        if item.get("action_type") != "apply_patch_artifact":
            continue
        if not is_active_pending_action(item):
            continue
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        item_session_id = str(details.get("session_id") or "").strip()
        if session_id is not None and item_session_id != session_id:
            continue
        artifacts.append(
            {
                "token": str(item.get("token") or "").strip(),
                "session_id": item_session_id,
                "workflow": str(details.get("workflow") or "").strip(),
                "artifact_id": str(details.get("artifact_id") or "").strip(),
                "changed_paths": _normalized_paths(details.get("changed_paths")),
                "target_path": str(item.get("target_path") or "").strip(),
                "lifecycle_state": str((item.get("lifecycle") or {}).get("state") or "staged").strip(),
            }
        )
    return artifacts


def summarize_runtime_control(
    *,
    pending_plan_token: str | None,
    pending_tool_call_count: int,
    queued_message_count: int,
    busy: bool,
    cancel_requested: bool,
    turn_phase: str,
    pending_artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    这是整个 AI 对话系统的「状态大脑」，
    根据当前所有运行数据，自动判断出 AI 现在到底处于什么状态，然后返回给前端显示（比如：等待批准、执行中、空闲、已取消）。
    """
    if cancel_requested:
        status = "canceled"
    elif pending_artifacts:
        status = "awaiting_artifact_approval"
    elif pending_plan_token:
        status = "awaiting_plan_approval"
    elif busy or pending_tool_call_count > 0:
        status = "planning" if turn_phase == "planning" else "executing"
    elif turn_phase == "idle":
        status = "idle"
    else:
        status = turn_phase or "idle"
    return {
        "status": status,
        "turn_phase": turn_phase,
        "busy": bool(busy),
        "cancel_requested": bool(cancel_requested),
        "pending_plan_token": pending_plan_token,
        "pending_tool_call_count": int(pending_tool_call_count),
        "queued_message_count": int(queued_message_count),
        "pending_artifact_count": len(pending_artifacts),
        "pending_artifacts": pending_artifacts,
    }


def build_runtime_doctor_report(
    workspace: Path,
    *,
    session_store: SessionStore,
    pending_store: PendingActionStore,
    session_id: str | None = None,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    sessions = session_store.tree()
    session_ids = {entry.id for entry in sessions}
    pending_items = pending_store.list()
    patch_artifacts = list_pending_patch_artifacts(pending_store, session_id=session_id)
    findings: list[dict[str, Any]] = []
    config_status: dict[str, Any] = {"status": "ok", "pending_effects": []}
    active_pending_items = [item for item in pending_items if classify_pending_action(item) == "active"]
    pending_state_counts: dict[str, int] = {}
    for item in pending_items:
        state = pending_action_state(item)
        pending_state_counts[state] = pending_state_counts.get(state, 0) + 1

    try:
        config_snapshot = get_config_manager(workspace).get_effective_snapshot(session_id=session_id)
        config_status = {
            "status": "ok",
            "active_profile": config_snapshot.active_profile,
            "config_version": config_snapshot.config_version,
            "reload_policy": config_snapshot.reload_policy,
            "pending_effects": list(config_snapshot.pending_effects),
        }
    except ConfigValidationError as exc:
        config_status = {"status": "invalid", "pending_effects": [], "errors": exc.errors}
        findings.append({"kind": "invalid_config", "errors": exc.errors})
    except (ValueError, TypeError) as exc:
        config_status = {"status": "invalid", "pending_effects": [], "error": str(exc)}
        findings.append({"kind": "invalid_config", "error": str(exc)})

    for item in pending_items:
        token = str(item.get("token") or "").strip()
        action_type = str(item.get("action_type") or "").strip()
        lifecycle_state = str((item.get("lifecycle") or {}).get("state") or "").strip()
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        item_session_id = str(details.get("session_id") or "").strip()
        if session_id is not None and item_session_id and item_session_id != session_id:
            continue
        if action_type in {"planner_approval", "apply_patch_artifact"}:
            if not item_session_id:
                findings.append(
                    {
                        "kind": "missing_session_id",
                        "token": token,
                        "action_type": action_type,
                    }
                )
            elif item_session_id not in session_ids:
                findings.append(
                    {
                        "kind": "orphaned_pending_token",
                        "token": token,
                        "action_type": action_type,
                        "session_id": item_session_id,
                    }
                )
        if action_type == "apply_patch_artifact":
            if lifecycle_state in {"expired", "quarantined"}:
                findings.append(
                    {
                        "kind": lifecycle_state,
                        "token": token,
                        "session_id": item_session_id,
                    }
                )
            target_path = str(item.get("target_path") or "").strip()
            if not target_path:
                findings.append(
                    {
                        "kind": "missing_artifact_path",
                        "token": token,
                        "session_id": item_session_id,
                    }
                )
            elif not Path(target_path).exists():
                findings.append(
                    {
                        "kind": "missing_artifact_file",
                        "token": token,
                        "session_id": item_session_id,
                        "target_path": target_path,
                    }
                )

    remediation = build_runtime_maintenance_preview(
        workspace,
        session_store=session_store,
        pending_store=pending_store,
        session_id=session_id,
    )
    storage_status = build_storage_health_summary(workspace, session_store=session_store)
    retention_status = build_retention_summary(workspace, session_store=session_store, pending_store=pending_store)

    session_summaries: list[dict[str, Any]] = []
    for entry in sessions:
        if session_id is not None and entry.id != session_id:
            continue
        session_artifacts = [artifact for artifact in patch_artifacts if artifact.get("session_id") == entry.id]
        pending_plan = bool(entry.pending_plan_token)
        if session_artifacts:
            status = "awaiting_artifact_approval"
        elif pending_plan:
            status = "awaiting_plan_approval"
        else:
            status = "idle"
        session_summaries.append(
            {
                "session_id": entry.id,
                "pending_plan_token": entry.pending_plan_token,
                "pending_artifact_count": len(session_artifacts),
                "status": status,
            }
        )

    return {
        "workspace": str(workspace),
        "status": "ok" if not findings else "warning",
        "session_id": session_id,
        "summary": {
            "session_count": len(session_summaries) if session_id is not None else len(sessions),
            "pending_action_count": len(pending_items),
            "active_pending_action_count": len(active_pending_items),
            "pending_action_state_counts": pending_state_counts,
            "pending_artifact_count": len(patch_artifacts),
            "finding_count": len(findings),
            "pending_config_effect_count": len(config_status.get("pending_effects") or []),
        },
        "config": config_status,
        "sessions": session_summaries,
        "pending_artifacts": patch_artifacts,
        "findings": findings,
        "remediation": remediation,
        "storage": storage_status,
        "retention": retention_status,
        "trace_store": retention_status["traces"],
    }


def build_storage_health_summary(
    workspace: Path,
    *,
    session_store: SessionStore,
) -> dict[str, Any]:
    session_files = sorted(session_store.root.glob("*.jsonl"))
    corrupted: list[dict[str, Any]] = []
    missing_snapshot: list[str] = []
    for path in session_files:
        has_snapshot = False
        try:
            for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                text = raw.strip()
                if not text:
                    continue
                try:
                    item = json.loads(text)
                except json.JSONDecodeError as exc:
                    corrupted.append({"path": str(path), "line": line_number, "error": str(exc)})
                    continue
                if item.get("type") == "session_snapshot":
                    has_snapshot = True
        except OSError as exc:
            corrupted.append({"path": str(path), "line": None, "error": str(exc)})
            continue
        if not has_snapshot:
            missing_snapshot.append(str(path))
    return {
        "workspace": str(workspace.resolve()),
        "session_store": str(session_store.root),
        "session_file_count": len(session_files),
        "corrupted_jsonl_count": len(corrupted),
        "missing_snapshot_count": len(missing_snapshot),
        "corrupted_jsonl": corrupted[:20],
        "missing_snapshot_files": missing_snapshot[:20],
        "status": "ok" if not corrupted and not missing_snapshot else "warning",
    }


def build_retention_summary(
    workspace: Path,
    *,
    session_store: SessionStore,
    pending_store: PendingActionStore,
) -> dict[str, Any]:
    agent_dir = workspace.resolve() / ".pp-agent"
    artifacts = _combined_directory_summary(
        "artifacts",
        [agent_dir / "artifacts", agent_dir / "patch-artifacts"],
    )
    return {
        "sessions": _directory_summary("sessions", session_store.root),
        "traces": _directory_summary("traces", agent_dir / "traces"),
        "pending_actions": _directory_summary("pending_actions", pending_store.root),
        "artifacts": artifacts,
    }


def build_runtime_maintenance_preview(
    workspace: Path,
    *,
    session_store: SessionStore,
    pending_store: PendingActionStore,
    session_id: str | None = None,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    sessions = session_store.tree()
    session_ids = {entry.id for entry in sessions}
    actions: list[dict[str, Any]] = []

    for item in pending_store.list():
        token = str(item.get("token") or "").strip()
        action_type = str(item.get("action_type") or "").strip()
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        item_session_id = str(item.get("session_id") or details.get("session_id") or "").strip()
        if session_id is not None and item_session_id and item_session_id != session_id:
            continue
        lifecycle_state = str((item.get("lifecycle") or {}).get("state") or "").strip()

        if action_type in {"planner_approval", "apply_patch_artifact"} and item_session_id and item_session_id not in session_ids:
            actions.append(
                _maintenance_action(
                    "remove_pending_action",
                    token=token,
                    reason="orphaned_pending_token",
                    safe=True,
                    explanation="Pending action references a session that no longer exists.",
                )
            )
            continue

        if action_type == "apply_patch_artifact":
            target_path = str(item.get("target_path") or "").strip()
            if not item_session_id:
                actions.append(
                    _maintenance_action(
                        "remove_pending_action",
                        token=token,
                        reason="missing_session_id",
                        safe=True,
                        explanation="Patch artifact approval is not tied to a session.",
                    )
                )
                continue
            if target_path and not Path(target_path).exists():
                actions.append(
                    _maintenance_action(
                        "remove_pending_action",
                        token=token,
                        reason="missing_artifact_file",
                        safe=True,
                        explanation="Patch artifact approval points at a file that no longer exists.",
                        affected_paths=[target_path],
                    )
                )
                continue
            if lifecycle_state in {"expired", "quarantined"}:
                actions.append(
                    _maintenance_action(
                        "remove_pending_action",
                        token=token,
                        reason=lifecycle_state,
                        safe=True,
                        explanation=f"Patch artifact approval is already {lifecycle_state}.",
                        affected_paths=[target_path] if target_path else [],
                    )
                )

    return {
        "workspace": str(workspace),
        "mode": "preview",
        "action_count": len(actions),
        "safe_action_count": len([action for action in actions if action.get("safe_to_apply")]),
        "actions": actions,
    }


def apply_runtime_maintenance(
    workspace: Path,
    *,
    session_store: SessionStore,
    pending_store: PendingActionStore,
    session_id: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    preview = build_runtime_maintenance_preview(
        workspace,
        session_store=session_store,
        pending_store=pending_store,
        session_id=session_id,
    )
    if not apply:
        return {**preview, "mode": "dry-run", "applied_count": 0, "applied": []}

    applied: list[dict[str, Any]] = []
    backup_root = pending_store.root / "maintenance-backups" / str(int(time.time()))
    for action in preview["actions"]:
        if action.get("operation") != "remove_pending_action" or not action.get("safe_to_apply"):
            continue
        token = str(action.get("token") or "").strip()
        source = pending_store.root / f"{token}.json"
        if not source.exists():
            applied.append({**action, "status": "skipped", "detail": "token file no longer exists"})
            continue
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_path = backup_root / source.name
        shutil.copy2(source, backup_path)
        pending_store.remove(token)
        applied.append({**action, "status": "applied", "backup_path": str(backup_path)})

    return {
        **preview,
        "mode": "apply",
        "applied_count": len([item for item in applied if item.get("status") == "applied"]),
        "applied": applied,
    }


def _maintenance_action(
    operation: str,
    *,
    token: str,
    reason: str,
    safe: bool,
    explanation: str,
    affected_paths: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "operation": operation,
        "token": token,
        "reason": reason,
        "safe_to_apply": bool(safe),
        "explanation": explanation,
        "affected_paths": affected_paths or [],
    }


def _directory_summary(label: str, root: Path) -> dict[str, Any]:
    root = root.resolve()
    files: list[Path] = []
    total_size = 0
    latest_mtime: float | None = None
    if root.exists():
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            files.append(path)
            total_size += int(stat.st_size)
            latest_mtime = max(latest_mtime or 0.0, float(stat.st_mtime))
    return {
        "label": label,
        "path": str(root),
        "exists": root.exists(),
        "file_count": len(files),
        "size_bytes": total_size,
        "latest_mtime": latest_mtime,
    }


def _combined_directory_summary(label: str, roots: list[Path]) -> dict[str, Any]:
    summaries = [_directory_summary(root.name, root) for root in roots]
    latest_values = [item["latest_mtime"] for item in summaries if item.get("latest_mtime") is not None]
    return {
        "label": label,
        "paths": [item["path"] for item in summaries],
        "exists": any(item["exists"] for item in summaries),
        "file_count": sum(int(item["file_count"]) for item in summaries),
        "size_bytes": sum(int(item["size_bytes"]) for item in summaries),
        "latest_mtime": max(latest_values) if latest_values else None,
        "directories": summaries,
    }


__all__ = [
    "apply_runtime_maintenance",
    "build_runtime_doctor_report",
    "build_runtime_maintenance_preview",
    "build_retention_summary",
    "build_storage_health_summary",
    "list_pending_patch_artifacts",
    "summarize_runtime_control",
]
