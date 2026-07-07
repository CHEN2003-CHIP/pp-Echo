from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional


TERMINAL_LIFECYCLE_STATES = {
    "denied",
    "expired",
    "execution_failed",
    "grant_consumed",
    "grant_invalidated",
    "orphaned",
    "quarantined",
    "rejected",
}
ACTIVE_LIFECYCLE_STATES = {"staged_not_granted", "grant_attached"}
ARCHIVED_LIFECYCLE_STATES = {
    "denied",
    "expired",
    "execution_failed",
    "grant_consumed",
    "grant_invalidated",
    "orphaned",
    "quarantined",
    "rejected",
}
KNOWN_LIFECYCLE_STATES = ACTIVE_LIFECYCLE_STATES | ARCHIVED_LIFECYCLE_STATES | {"execution_in_progress", "execution_succeeded"}


def lifecycle_snapshot(
    state: str,
    *,
    failure_reason_code: str | None = None,
    failure_reason_detail: str | None = None,
    updated_at: float | None = None,
) -> dict[str, Any]:
    return {
        "state": state,
        "updated_at": updated_at or time.time(),
        "failure_reason_code": failure_reason_code,
        "failure_reason_detail": failure_reason_detail,
    }


class PendingActionStore:
    """【待处理操作本地文件存储】"""
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def stage(
        self,
        *,
        action_type: str,
        target_path: Optional[Path] = None,
        before: str = "",
        after: str = "",
        command: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        effect: Optional[dict[str, Any]] = None,
        approval_grant: Optional[dict[str, Any]] = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        tool_call_id: str | None = None,
        origin: dict[str, Any] | str | None = None,
        expires_at: float | None = None,
    ) -> dict[str, Any]:
        """将一个待处理操作添加到存储中"""
        now = time.time()
        if effect is not None:
            existing = self._find_active_match(
                action_type=action_type,
                effect=effect,
                target_path=target_path,
                command=command,
                session_id=session_id,
            )
            if existing is not None:
                return existing
        token = str(uuid.uuid4())
        normalized_arguments = effect.get("normalized_arguments") if isinstance(effect, dict) else None
        lifecycle_state = "staged_not_granted" if effect is not None else None
        effective_expires_at = expires_at
        if effective_expires_at is None and effect is not None:
            effective_expires_at = now + 7 * 24 * 60 * 60
        payload = {
            "token": token,
            "action_type": action_type,
            "target_path": str(target_path) if target_path else None,
            "before": before,
            "after": after,
            "command": command,
            "created_at": now,
            "details": details or {},
            "effect": effect,
            "approval_grant": approval_grant,
            "session_id": session_id or (details or {}).get("session_id"),
            "turn_id": turn_id or (details or {}).get("turn_id"),
            "tool_call_id": tool_call_id or (details or {}).get("tool_call_id"),
            "origin": origin or (details or {}).get("origin"),
            "expires_at": effective_expires_at,
            "canonical_key": effect.get("payload_digest") if isinstance(effect, dict) else None,
            "normalized_arguments": normalized_arguments,
            "lifecycle": lifecycle_snapshot(lifecycle_state) if lifecycle_state is not None else None,
            "latest_audit": None,
            "latest_audit_path": None,
        }
        target = self.root / f"{token}.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def _find_active_match(
        self,
        *,
        action_type: str,
        effect: dict[str, Any],
        target_path: Optional[Path] = None,
        command: Optional[str] = None,
        session_id: str | None = None,
    ) -> dict[str, Any] | None:
        payload_digest = effect.get("payload_digest")
        if not isinstance(payload_digest, str) or not payload_digest:
            return None
        for item in self.list():
            if item.get("action_type") != action_type:
                continue
            if not is_active_pending_action(item):
                continue
            existing_key = item.get("canonical_key") or (item.get("effect") or {}).get("payload_digest")
            if existing_key != payload_digest:
                continue
            if session_id:
                existing_session_id = item.get("session_id") or (item.get("details") or {}).get("session_id")
                if existing_session_id and existing_session_id != session_id:
                    continue
            if target_path is not None and str(item.get("target_path") or "") != str(target_path):
                continue
            if command is not None and str(item.get("command") or "") != str(command):
                continue
            return item
        return None

    def load(self, token: str) -> dict[str, Any]:
        target = self.root / f"{token}.json"
        if not target.exists():
            raise FileNotFoundError(f"Pending action token not found: {token}")
        return json.loads(target.read_text(encoding="utf-8"))

    def remove(self, token: str) -> None:
        (self.root / f"{token}.json").unlink(missing_ok=True)

    def save(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        target = self.root / f"{token}.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def attach_approval_grant(self, token: str, *, granted_by: str = "host") -> dict[str, Any]:
        payload = self.load(token)
        effect = payload.get("effect")
        if effect is None:
            raise ValueError("Pending action is missing an effect record.")
        payload["approval_grant"] = create_approval_grant(effect, granted_by=granted_by)
        proposal_digest = _proposal_digest_from_payload(payload)
        if proposal_digest:
            payload["approval_grant"]["proposal_digest"] = proposal_digest
        payload["lifecycle"] = lifecycle_snapshot("grant_attached")
        self.save(token, payload)
        return payload

    def set_lifecycle(
        self,
        token: str,
        state: str,
        *,
        failure_reason_code: str | None = None,
        failure_reason_detail: str | None = None,
    ) -> dict[str, Any]:
        payload = self.load(token)
        payload["lifecycle"] = lifecycle_snapshot(
            state,
            failure_reason_code=failure_reason_code,
            failure_reason_detail=failure_reason_detail,
        )
        self.save(token, payload)
        return payload

    def write_audit_record(
        self,
        token: str,
        *,
        lifecycle_state: str,
        failure_reason_code: str | None = None,
        failure_reason_detail: str | None = None,
    ) -> dict[str, Any]:
        payload = self.load(token)
        effect = payload.get("effect") or {}
        analysis = effect.get("analysis") or {}
        grant = payload.get("approval_grant") or {}
        timestamp = time.time()
        record = {
            "effect_id": effect.get("effect_id"),
            "grant_id": grant.get("grant_id"),
            "tool_name": effect.get("tool_name"),
            "family": analysis.get("family"),
            "summary": analysis.get("summary", effect.get("summary")),
            "lifecycle_state": lifecycle_state,
            "failure_reason_code": failure_reason_code,
            "failure_reason_detail": failure_reason_detail,
            "timestamp": timestamp,
        }
        audit_root = self.root / "audit"
        audit_root.mkdir(parents=True, exist_ok=True)
        effect_id = effect.get("effect_id") or "unknown-effect"
        audit_path = audit_root / f"{timestamp:.6f}-{effect_id}.json"
        audit_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["latest_audit"] = record
        payload["latest_audit_path"] = str(audit_path)
        self.save(token, payload)
        return record

    def list(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                items.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return items


def create_approval_grant(effect: dict[str, Any], *, granted_by: str = "host") -> dict[str, Any]:
    return {
        "grant_id": str(uuid.uuid4()),
        "effect_id": effect["effect_id"],
        "payload_digest": effect["payload_digest"],
        "granted_at": time.time(),
        "granted_by": granted_by,
        "status": "active",
        "invalidated_at": None,
        "consumed_at": None,
    }


def _proposal_digest_from_payload(payload: dict[str, Any]) -> str | None:
    details = payload.get("details")
    if not isinstance(details, dict):
        return None
    proposal = details.get("patch_proposal")
    if not isinstance(proposal, dict):
        proposal = details.get("command_proposal")
    if not isinstance(proposal, dict):
        return None
    digest = proposal.get("proposal_digest")
    return str(digest) if digest else None


def is_active_pending_action(item: dict[str, Any]) -> bool:
    lifecycle = item.get("lifecycle") or {}
    state = str(lifecycle.get("state") or "").strip()
    if state and state not in ACTIVE_LIFECYCLE_STATES:
        return False
    expires_at = item.get("expires_at")
    if isinstance(expires_at, (int, float)) and expires_at > 0 and time.time() > float(expires_at):
        return False
    return True


def classify_pending_action(item: dict[str, Any]) -> str:
    expires_at = item.get("expires_at")
    if isinstance(expires_at, (int, float)) and expires_at > 0 and time.time() > float(expires_at):
        return "expired"
    lifecycle = item.get("lifecycle") or {}
    state = str(lifecycle.get("state") or "").strip()
    if not state or state in ACTIVE_LIFECYCLE_STATES:
        return "active"
    if state in {"orphaned", "quarantined"}:
        return state
    if state in ARCHIVED_LIFECYCLE_STATES:
        return "archived"
    return "unknown"


def pending_action_state(item: dict[str, Any]) -> str:
    classification = classify_pending_action(item)
    if classification != "archived":
        return classification
    lifecycle = item.get("lifecycle") or {}
    state = str(lifecycle.get("state") or "").strip()
    return state if state in KNOWN_LIFECYCLE_STATES else "archived"
