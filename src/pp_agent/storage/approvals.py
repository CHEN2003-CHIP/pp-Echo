from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional


TERMINAL_LIFECYCLE_STATES = {"execution_failed", "grant_invalidated", "grant_consumed"}


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
    ) -> dict[str, Any]:
        """将一个待处理操作添加到存储中"""
        token = str(uuid.uuid4())
        payload = {
            "token": token,
            "action_type": action_type,
            "target_path": str(target_path) if target_path else None,
            "before": before,
            "after": after,
            "command": command,
            "created_at": time.time(),
            "details": details or {},
            "effect": effect,
            "approval_grant": approval_grant,
            "lifecycle": lifecycle_snapshot("staged_not_granted") if effect is not None else None,
            "latest_audit": None,
            "latest_audit_path": None,
        }
        target = self.root / f"{token}.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

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
