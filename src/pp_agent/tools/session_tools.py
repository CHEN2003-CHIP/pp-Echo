from __future__ import annotations

from pathlib import Path
from typing import Any
from typing import Optional

from pp_agent.domain import ToolSpec
from pp_agent.storage.sessions import SessionStore
from pp_agent.storage.settings import Settings
from pp_agent.tools.base import BaseTool, ToolExecutionResult


SAFE_REWIND_MODE_VALUES = [
    "conversation_and_workspace",
    "workspace_only",
    "conversation_only",
]


class PreviewSafeRewindTool(BaseTool):
    def __init__(self, workspace: Path, current_session_id: Optional[str] = None) -> None:
        super().__init__(workspace)
        self.current_session_id = current_session_id

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="preview_safe_rewind",
            description="Preview a safe rewind for the conversation, workspace, or both without changing state.",
            parameters=_safe_rewind_parameters(),
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        session_id = _resolve_session_ref(self.workspace, arguments["session_id"], current_session_id=self.current_session_id)
        payload = _preview_rewind(self.workspace, session_id, **_safe_rewind_kwargs(arguments))
        details = _preview_details(payload)
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=details["summary"],
            details=details,
        )


class ExecuteSafeRewindTool(BaseTool):
    def __init__(self, workspace: Path, current_session_id: Optional[str] = None) -> None:
        super().__init__(workspace)
        self.current_session_id = current_session_id

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="execute_safe_rewind",
            description="Execute a safe rewind for the conversation, workspace, or both.",
            parameters=_safe_rewind_parameters(),
            requires_confirmation=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        session_id = _resolve_session_ref(self.workspace, arguments["session_id"], current_session_id=self.current_session_id)
        payload = _execute_rewind(self.workspace, session_id, **_safe_rewind_kwargs(arguments))
        details = _result_details(payload)
        return ToolExecutionResult(
            tool_call_id="",
            tool_name=self.spec.name,
            content=details["summary"],
            details=details,
        )


def _safe_rewind_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "checkpoint_id": {"type": "string"},
            "turn_count": {"type": "integer"},
            "message_count": {"type": "integer"},
            "mode": {"type": "string", "enum": SAFE_REWIND_MODE_VALUES},
            "allow_stash_snapshot": {"type": "boolean"},
        },
        "required": ["session_id"],
    }


def _safe_rewind_kwargs(arguments: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in ("checkpoint_id", "turn_count", "message_count", "mode", "allow_stash_snapshot"):
        if key in arguments and arguments[key] is not None:
            payload[key] = arguments[key]
    return payload


def _resolve_session_ref(workspace: Path, session_ref: str, *, current_session_id: Optional[str] = None) -> str:
    ref = str(session_ref or "").strip()
    if not ref:
        raise ValueError("Session id is required")
    if "@" in ref:
        raise ValueError("Safe rewind does not accept session@turn references. Use session_id plus turn_count or checkpoint_id.")
    if ref == "current":
        if current_session_id:
            return current_session_id
        raise ValueError("Unknown session reference 'current'. Use the active session id or a unique prefix.")

    store = _session_store_for(workspace)
    entries = store.tree()
    exact = next((entry.id for entry in entries if entry.id == ref), None)
    if exact:
        return exact
    matches = [entry.id for entry in entries if entry.id.startswith(ref)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        if current_session_id:
            raise ValueError(f"Unknown session reference '{ref}'. Use the active session id {current_session_id} or a unique prefix.")
        raise ValueError(f"Unknown session reference '{ref}'. Use the active session id or a unique prefix.")
    raise ValueError(f"Session prefix is ambiguous: {ref}")


def _session_store_for(workspace: Path) -> SessionStore:
    settings = Settings.load(workspace)
    candidates = [settings.global_dir / "sessions", settings.project_dir / "global" / "sessions"]
    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            return SessionStore(candidate)
        except PermissionError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise PermissionError("Unable to create a writable session tree store")


def _preview_rewind(workspace: Any, session_id: str, **kwargs: Any) -> dict[str, Any]:
    from pp_agent.api import sdk

    return sdk.preview_rewind(workspace, session_id, **kwargs)


def _execute_rewind(workspace: Any, session_id: str, **kwargs: Any) -> dict[str, Any]:
    from pp_agent.api import sdk

    return sdk.rewind_safe(workspace, session_id, **kwargs)


def _preview_details(payload: dict[str, Any]) -> dict[str, Any]:
    checkpoint = payload.get("checkpoint") or {}
    restore_preview = payload.get("restore_preview") or {}
    warning_messages = list(payload.get("warning_messages") or [])
    affected_files = list(restore_preview.get("affected_files") or [])
    details = {
        "session_id": payload.get("source_session_id"),
        "checkpoint_id": checkpoint.get("checkpoint_id"),
        "snapshot_type": checkpoint.get("snapshot_type"),
        "mode": payload.get("mode"),
        "preview_only": True,
        "restored_workspace": False,
        "affected_message_count": payload.get("message_count"),
        "affected_turn_count": payload.get("turn_count"),
        "target_head_id": payload.get("target_head_id"),
        "workspace_file_count": len(affected_files),
        "warning_messages": warning_messages,
    }
    details["summary"] = _preview_summary(details, affected_files, warning_messages)
    return details


def _result_details(payload: dict[str, Any]) -> dict[str, Any]:
    warning_messages = list(payload.get("warning_messages") or [])
    details = {
        "session_id": payload.get("session_id") or payload.get("source_session_id"),
        "checkpoint_id": payload.get("checkpoint_id"),
        "snapshot_type": payload.get("snapshot_type"),
        "mode": payload.get("mode"),
        "preview_only": False,
        "restored_workspace": bool(payload.get("restored_workspace", False)),
        "affected_message_count": None,
        "affected_turn_count": None,
        "target_head_id": payload.get("active_head_id"),
        "workspace_file_count": None,
        "warning_messages": warning_messages,
    }
    details["summary"] = _result_summary(details, bool(payload.get("restored_conversation", False)), warning_messages)
    return details


def _preview_summary(details: dict[str, Any], affected_files: list[str], warning_messages: list[str]) -> str:
    scope = _mode_label(details["mode"])
    checkpoint = details["checkpoint_id"] or "auto-resolve"
    impact_bits = [
        f"session={details['session_id']}",
        f"checkpoint={checkpoint}",
        f"messages={details['affected_message_count']}",
        f"turns={details['affected_turn_count']}",
        f"workspace_files={len(affected_files)}",
        f"target_head={details['target_head_id']}",
    ]
    if warning_messages:
        impact_bits.append(f"warnings={len(warning_messages)}")
    return f"Preview safe rewind for {scope}: " + ", ".join(impact_bits)


def _result_summary(details: dict[str, Any], restored_conversation: bool, warning_messages: list[str]) -> str:
    scope = _mode_label(details["mode"])
    impact_bits = [
        f"session={details['session_id']}",
        f"checkpoint={details['checkpoint_id'] or 'none'}",
        f"restored_workspace={details['restored_workspace']}",
        f"restored_conversation={restored_conversation}",
        f"target_head={details['target_head_id']}",
    ]
    if warning_messages:
        impact_bits.append(f"warnings={len(warning_messages)}")
    return f"Executed safe rewind for {scope}: " + ", ".join(impact_bits)


def _mode_label(mode: Any) -> str:
    if mode in SAFE_REWIND_MODE_VALUES:
        return str(mode)
    return "conversation_and_workspace"
