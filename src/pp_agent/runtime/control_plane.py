from __future__ import annotations

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
    }


__all__ = [
    "build_runtime_doctor_report",
    "list_pending_patch_artifacts",
    "summarize_runtime_control",
]
