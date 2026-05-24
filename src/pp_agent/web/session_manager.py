from __future__ import annotations

import queue
import threading
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pp_agent.app import bootstrap
from pp_agent.runtime.control_plane import list_pending_patch_artifacts, summarize_runtime_control
from pp_agent.runtime import AgentEvent


RuntimeFactory = Callable[[Path, Optional[str], list[Callable[[AgentEvent], None]]], object]
MAX_WEB_SESSION_LIST = 200
MAX_WEB_MESSAGES = 24
MAX_WEB_TEXT_CHARS = 12_000
MAX_WEB_TOTAL_TEXT_CHARS = 80_000
MAX_WEB_LIST_EVENT_CHARS = 200_000
MAX_WEB_MEDIA_URL_CHARS = 4_096
MAX_WEB_EVENT_TEXT_CHARS = 12_000
MAX_WEB_EVENT_COLLECTION_ITEMS = 24
MAX_WEB_EVENT_OBJECT_KEYS = 80
WEB_MESSAGE_ROLES = {"user", "assistant", "tool"}


@dataclass
class QueuedWebEvent:
    session_id: str
    event: AgentEvent


class WebSessionHandle:
    def __init__(
        self,
        workspace: Path,
        session_id: Optional[str],
        *,
        runtime_factory: RuntimeFactory,
    ) -> None:
        self.workspace = workspace
        self._event_queue: queue.Queue[QueuedWebEvent] = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._runtime_factory = runtime_factory
        self.agent = self._build_runtime(session_id)

    @property
    def session_id(self) -> str:
        return str(self.agent.session_id)

    def is_busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def snapshot(self) -> dict:
        pending_artifacts = list_pending_patch_artifacts(
            bootstrap.pending_action_store_for(self.workspace),
            session_id=self.session_id,
        )
        messages = _web_message_payloads(self.agent.state.messages)
        return {
            "session_id": self.session_id,
            "busy": self.is_busy(),
            "cancel_requested": self.cancel_requested(),
            "pending_plan_token": self.agent.state.pending_plan_token,
            "pending_tool_call_count": len(self.agent.state.pending_tool_calls),
            "queued_message_count": len(self.agent.state.queued_messages),
            "turn": self.agent.state.turn.model_dump(mode="json"),
            "pending_artifacts": pending_artifacts,
            "runtime_control": summarize_runtime_control(
                pending_plan_token=self.agent.state.pending_plan_token,
                pending_tool_call_count=len(self.agent.state.pending_tool_calls),
                queued_message_count=len(self.agent.state.queued_messages),
                busy=self.is_busy(),
                cancel_requested=self.cancel_requested(),
                turn_phase=getattr(self.agent.state.turn, "phase", "idle"),
                pending_artifacts=pending_artifacts,
            ),
            "messages": messages,
            "history": _web_history_payload(
                self.agent.state.messages,
                source="active",
                returned_count=len(messages),
            ),
        }

    def drain_events(self) -> list[dict]:
        items: list[dict] = []
        while True:
            try:
                queued = self._event_queue.get_nowait()
            except queue.Empty:
                return items
            items.append(_web_event_payload(queued.event))

    def prompt(self, text: str) -> dict:
        if not text.strip():
            raise ValueError("Prompt cannot be empty.")
        if self.agent.state.pending_plan_token:
            raise RuntimeError("Approval pending. Approve or reject before sending a new prompt.")
        if self.is_busy():
            item = self.agent.enqueue_message(text, delivery="follow_up")
            self._emit_local("queue_update", "Queued follow-up prompt.", {"queued_id": item.id, "delivery": item.delivery})
            return {"session_id": self.session_id, "queued": True, "queued_message_id": item.id}
        self._start_worker("prompt", lambda value=text: self.agent.prompt(value))
        return {"session_id": self.session_id, "queued": False}

    def continue_(self) -> dict:
        self._start_worker("continue", lambda: self.agent.continue_())
        return {"session_id": self.session_id}

    def approve(self) -> dict:
        token = self.agent.state.pending_plan_token
        if not token:
            raise RuntimeError("No pending approval.")
        self._start_worker("approve", lambda: self.agent.approve_pending_plan(token))
        return {"session_id": self.session_id, "token": token}

    def reject(self) -> dict:
        token = self.agent.state.pending_plan_token
        if not token:
            raise RuntimeError("No pending approval.")
        self.agent.reject_pending_plan(token)
        self._emit_local("planner_gate_rejected", f"Rejected planner gate {token}.", {"token": token})
        return {"session_id": self.session_id, "token": token}

    def cancel(self) -> dict:
        if not self.is_busy():
            return {"session_id": self.session_id, "cancel_requested": False, "busy": False}
        request_cancel = getattr(self.agent, "request_cancel", None)
        if callable(request_cancel):
            request_cancel("cancel_requested")
        self._emit_local(
            "cancel_requested",
            "Cancel requested for the running turn.",
            {"cancel_requested": True},
        )
        return {"session_id": self.session_id, "cancel_requested": True, "busy": self.is_busy()}

    def cancel_requested(self) -> bool:
        checker = getattr(self.agent, "cancellation_requested", None)
        return bool(callable(checker) and checker())

    def _build_runtime(self, session_id: Optional[str]):
        return self._runtime_factory(
            self.workspace,
            session_id,
            [lambda event: self._event_queue.put(QueuedWebEvent(session_id=self.session_id, event=event))],
        )

    def _emit_local(self, event_type: str, message: str, details: Optional[dict] = None) -> None:
        self._event_queue.put(
            QueuedWebEvent(
                session_id=self.session_id,
                event=AgentEvent(
                    type=event_type,
                    session_id=self.session_id,
                    message=message,
                    details=details or {},
                ),
            )
        )

    def _start_worker(self, action: str, fn) -> None:
        with self._lock:
            if self.is_busy():
                raise RuntimeError(f"Agent is busy; cannot start {action}.")

            def runner() -> None:
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001
                    self._event_queue.put(
                        QueuedWebEvent(
                            session_id=self.session_id,
                            event=AgentEvent(
                                type="error",
                                session_id=self.session_id,
                                message=str(exc),
                                details={"source": "web_session_manager", "action": action},
                                is_error=True,
                            ),
                        )
                    )

            self._worker = threading.Thread(target=runner, name=f"pp-agent-web-{action}", daemon=True)
            self._worker.start()


class WebSessionManager:
    def __init__(
        self,
        workspace: Path,
        *,
        runtime_factory: Optional[RuntimeFactory] = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self._runtime_factory = runtime_factory or self._default_runtime_factory
        self._handles: dict[str, WebSessionHandle] = {}
        self._lock = threading.Lock()

    def create_session(self) -> dict:
        handle = WebSessionHandle(self.workspace, None, runtime_factory=self._runtime_factory)
        with self._lock:
            self._handles[handle.session_id] = handle
        return handle.snapshot()

    def get_handle(self, session_id: str) -> WebSessionHandle:
        with self._lock:
            handle = self._handles.get(session_id)
        if handle is not None:
            return handle
        handle = WebSessionHandle(self.workspace, session_id, runtime_factory=self._runtime_factory)
        with self._lock:
            self._handles[handle.session_id] = handle
        return handle

    def get_active_handle(self, session_id: str) -> Optional[WebSessionHandle]:
        with self._lock:
            return self._handles.get(session_id)

    def snapshot(self, session_id: str) -> dict:
        handle = self.get_active_handle(session_id)
        if handle is not None:
            return handle.snapshot()
        return self._stored_snapshot(session_id)

    def list_sessions(self) -> list[dict]:
        store = bootstrap.session_store_for(self.workspace)
        entries: list[dict] = []
        for path in store.root.glob("*.jsonl"):
            entry = _stored_session_list_entry(path)
            if entry is not None:
                entries.append(entry)
        return sorted(entries, key=lambda item: item.get("updated_at", 0), reverse=True)[:MAX_WEB_SESSION_LIST]

    def list_active(self) -> list[dict]:
        with self._lock:
            handles = list(self._handles.values())
        return [handle.snapshot() for handle in handles]

    @staticmethod
    def _default_runtime_factory(workspace: Path, session_id: Optional[str], subscribers: list[Callable[[AgentEvent], None]]):
        return bootstrap.build_agent(workspace, session_id=session_id, lifecycle_subscribers=subscribers)

    def _stored_snapshot(self, session_id: str) -> dict:
        store = bootstrap.session_store_for(self.workspace)
        event_snapshot = _stored_event_snapshot(self.workspace, store.root, session_id)
        if event_snapshot is not None:
            return event_snapshot
        record = store.load(session_id)
        branch_messages, branch_message_count = _stored_branch_tail(store, record)
        pending_artifacts = list_pending_patch_artifacts(
            bootstrap.pending_action_store_for(self.workspace),
            session_id=record.id,
        )
        pending_tool_call_count = len(record.pending_tool_calls)
        queued_message_count = len(record.queued_messages)
        messages = _web_message_payloads(branch_messages)
        return {
            "session_id": record.id,
            "busy": False,
            "cancel_requested": False,
            "pending_plan_token": record.pending_plan_token,
            "pending_tool_call_count": pending_tool_call_count,
            "queued_message_count": queued_message_count,
            "turn": {"phase": "idle", "reason": None},
            "pending_artifacts": pending_artifacts,
            "runtime_control": summarize_runtime_control(
                pending_plan_token=record.pending_plan_token,
                pending_tool_call_count=pending_tool_call_count,
                queued_message_count=queued_message_count,
                busy=False,
                cancel_requested=False,
                turn_phase="idle",
                pending_artifacts=pending_artifacts,
            ),
            "messages": messages,
            "history": _web_history_payload(
                branch_messages,
                source="stored",
                returned_count=len(messages),
                total_message_count=branch_message_count,
            ),
        }


def _stored_event_snapshot(workspace: Path, session_root: Path, session_id: str) -> dict | None:
    path = session_root / f"{session_id}.jsonl"
    if not path.exists():
        return None

    messages: list[dict] = []
    total_message_count = 0
    total_visible_count = 0
    pending_plan_token = None
    pending_tool_calls: list[dict] = []
    queued_messages: list[dict] = []

    try:
        line_iter = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return None
    with line_iter as handle:
        for raw in handle:
            event_type, data = _parse_web_event_line(raw)
            if event_type == "messages_appended":
                appended = [message for message in data.get("messages", []) if isinstance(message, dict)]
                count = data.get("count")
                total_message_count += int(count) if isinstance(count, int) else len(appended)
                for message in appended:
                    if _is_web_visible_message(message):
                        total_visible_count += 1
                        messages.append(message)
                del messages[:-MAX_WEB_MESSAGES]
                continue
            if event_type == "messages_replaced":
                count = data.get("count")
                total_message_count = int(count) if isinstance(count, int) else 0
                total_visible_count = 0
                messages.clear()
                continue
            if event_type == "pending_state_updated":
                pending_plan_token = data.get("pending_plan_token")
                pending_tool_calls = [item for item in data.get("pending_tool_calls", []) if isinstance(item, dict)]
                queued_messages = [item for item in data.get("queued_messages", []) if isinstance(item, dict)]

    pending_artifacts = list_pending_patch_artifacts(
        bootstrap.pending_action_store_for(workspace),
        session_id=session_id,
    )
    rendered_messages = _web_message_payloads(messages)
    return {
        "session_id": session_id,
        "busy": False,
        "cancel_requested": False,
        "pending_plan_token": pending_plan_token if isinstance(pending_plan_token, str) else None,
        "pending_tool_call_count": len(pending_tool_calls),
        "queued_message_count": len(queued_messages),
        "turn": {"phase": "idle", "reason": None},
        "pending_artifacts": pending_artifacts,
        "runtime_control": summarize_runtime_control(
            pending_plan_token=pending_plan_token if isinstance(pending_plan_token, str) else None,
            pending_tool_call_count=len(pending_tool_calls),
            queued_message_count=len(queued_messages),
            busy=False,
            cancel_requested=False,
            turn_phase="idle",
            pending_artifacts=pending_artifacts,
        ),
        "messages": rendered_messages,
        "history": _web_history_payload(
            messages,
            source="stored",
            returned_count=len(rendered_messages),
            total_message_count=total_message_count,
            total_visible_count=total_visible_count,
        ),
    }


def _parse_web_event_line(raw: str) -> tuple[str | None, dict]:
    stripped = raw.strip()
    if not stripped:
        return None, {}
    if '"type": "session_snapshot"' in stripped or '"type":"session_snapshot"' in stripped:
        return None, {}
    try:
        item = json.loads(stripped) if len(stripped) <= MAX_WEB_LIST_EVENT_CHARS else _large_event_stub(stripped)
    except json.JSONDecodeError:
        return None, {}
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    event_type = item.get("type")
    return (event_type if isinstance(event_type, str) else None), data


def _stored_session_list_entry(path: Path) -> dict | None:
    session_id = path.stem
    parent_id = None
    updated_at = path.stat().st_mtime
    model = ""
    active_head_id = None
    pending_plan_token = None
    message_count = 0
    turn_count = 0
    summary_preview = ""
    last_user_preview = ""
    last_assistant_preview = ""

    try:
        line_iter = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return None

    with line_iter as handle:
        for raw in handle:
            stripped = raw.strip()
            if not stripped:
                continue
            if '"type": "session_snapshot"' in stripped or '"type":"session_snapshot"' in stripped:
                continue
            try:
                item = json.loads(stripped) if len(stripped) <= MAX_WEB_LIST_EVENT_CHARS else _large_event_stub(stripped)
            except json.JSONDecodeError:
                continue
            event_type = item.get("type")
            at = item.get("at")
            if isinstance(at, (int, float)):
                updated_at = max(updated_at, float(at))
            data = item.get("data") if isinstance(item.get("data"), dict) else {}

            if event_type in {"metadata_created", "metadata_updated"}:
                parent_id = data.get("parent_id") if isinstance(data.get("parent_id"), str) else parent_id
                model_payload = data.get("model")
                if isinstance(model_payload, dict) and isinstance(model_payload.get("model"), str):
                    model = model_payload["model"]
                continue
            if event_type == "head_updated":
                active_head_id = data.get("active_head_id") if isinstance(data.get("active_head_id"), str) else active_head_id
                continue
            if event_type == "pending_state_updated":
                pending_plan_token = data.get("pending_plan_token") if isinstance(data.get("pending_plan_token"), str) else None
                continue
            if event_type == "turn_node_added":
                node = data
                if node.get("entry_type", "turn") == "turn":
                    turn_count += 1
                    start = node.get("start_message_index")
                    end = node.get("end_message_index")
                    if isinstance(start, int) and isinstance(end, int):
                        message_count = max(message_count, end)
                elif isinstance(node.get("summary"), str):
                    summary_preview = _preview_text(node["summary"])
                continue
            if event_type == "messages_appended":
                count = data.get("count")
                if isinstance(count, int):
                    message_count += count
                for message in data.get("messages", []):
                    if not isinstance(message, dict):
                        continue
                    role = str(message.get("role", ""))
                    if role == "user":
                        last_user_preview = _preview_text(_dict_message_text(message))
                    elif role == "assistant":
                        last_assistant_preview = _preview_text(_dict_message_text(message))
                continue
            if event_type == "messages_replaced":
                count = data.get("count")
                if isinstance(count, int):
                    message_count = count
                    last_user_preview = ""
                    last_assistant_preview = ""

    return {
        "id": session_id,
        "parent_id": parent_id,
        "updated_at": updated_at,
        "model": model or "unknown",
        "message_count": message_count,
        "turn_count": turn_count,
        "pending_plan_token": pending_plan_token,
        "active_head_id": active_head_id,
        "summary_preview": summary_preview,
        "last_user_preview": last_user_preview,
        "last_assistant_preview": last_assistant_preview,
    }


def _large_event_stub(raw: str) -> dict:
    event_type = _extract_json_string(raw, "type")
    data: dict[str, object] = {}
    count = _extract_json_int(raw, "count")
    if count is not None:
        data["count"] = count
    active_head_id = _extract_json_string(raw, "active_head_id")
    if active_head_id is not None:
        data["active_head_id"] = active_head_id
    return {"type": event_type, "data": data}


def _extract_json_string(raw: str, key: str) -> str | None:
    marker = f'"{key}"'
    start = raw.find(marker)
    if start < 0:
        return None
    colon = raw.find(":", start + len(marker))
    if colon < 0:
        return None
    quote = raw.find('"', colon + 1)
    if quote < 0:
        return None
    end = raw.find('"', quote + 1)
    if end < 0:
        return None
    return raw[quote + 1 : end]


def _extract_json_int(raw: str, key: str) -> int | None:
    marker = f'"{key}"'
    start = raw.find(marker)
    if start < 0:
        return None
    colon = raw.find(":", start + len(marker))
    if colon < 0:
        return None
    index = colon + 1
    while index < len(raw) and raw[index].isspace():
        index += 1
    end = index
    while end < len(raw) and raw[end].isdigit():
        end += 1
    if end == index:
        return None
    return int(raw[index:end])


def _tail_for_web(messages: list[dict]) -> list[dict]:
    tail: list[dict] = []
    visible_count = 0
    for message in reversed(messages):
        tail.append(message)
        if _is_web_visible_message(message):
            visible_count += 1
        if visible_count >= MAX_WEB_MESSAGES:
            break
    return list(reversed(tail))


def _stored_branch_tail(store, record) -> tuple[list[object], int]:
    path = store.turn_path(record, record.active_head_id)
    total_message_count = sum(
        node.end_message_index - node.start_message_index
        for node in path
        if node.entry_type == "turn"
    )
    tail: list[object] = []
    visible_count = 0
    for node in reversed(path):
        if node.entry_type != "turn":
            continue
        node_messages = record.messages[node.start_message_index:node.end_message_index]
        for message in reversed(node_messages):
            tail.append(message)
            if _is_web_visible_message(message):
                visible_count += 1
            if visible_count >= MAX_WEB_MESSAGES:
                return list(reversed(tail)), total_message_count
    return list(reversed(tail)), total_message_count


def _is_web_visible_message(message) -> bool:
    role = message.get("role") if isinstance(message, dict) else getattr(message, "role", "")
    return str(role) in WEB_MESSAGE_ROLES


def _web_message_payloads(messages) -> list[dict]:
    visible = [message for message in messages if _is_web_visible_message(message)]
    payloads: list[dict] = []
    remaining = MAX_WEB_TOTAL_TEXT_CHARS
    for message in reversed(visible[-MAX_WEB_MESSAGES:]):
        if remaining <= 0:
            break
        payload, used = _web_message_payload(message, text_budget=remaining)
        if payload["content"] or payload["metadata"]:
            payloads.append(payload)
            remaining -= used
    return list(reversed(payloads))


def _web_history_payload(
    messages,
    *,
    source: str,
    returned_count: int,
    total_message_count: int | None = None,
    total_visible_count: int | None = None,
) -> dict:
    visible_count = (
        sum(1 for message in messages if _is_web_visible_message(message))
        if total_visible_count is None
        else total_visible_count
    )
    total = len(messages) if total_message_count is None else total_message_count
    return {
        "source": source,
        "message_count": total,
        "visible_message_count": visible_count,
        "returned_message_count": returned_count,
        "truncated": total > len(messages) or visible_count > returned_count,
        "max_messages": MAX_WEB_MESSAGES,
        "max_total_text_chars": MAX_WEB_TOTAL_TEXT_CHARS,
    }


def _web_message_payload(message, *, text_budget: int = MAX_WEB_TOTAL_TEXT_CHARS) -> tuple[dict, int]:
    payload = dict(message) if isinstance(message, dict) else message.model_dump(mode="json")
    content: list[dict] = []
    used = 0
    remaining = max(0, text_budget)
    for part in payload.get("content", []):
        rendered, part_used = _web_content_part(part, text_budget=remaining)
        if rendered is None:
            continue
        content.append(rendered)
        used += part_used
        remaining = max(0, remaining - part_used)
    payload["content"] = content
    payload["metadata"] = _web_metadata(payload.get("metadata") or {})
    return payload, used


def _web_content_part(part: dict, *, text_budget: int) -> tuple[dict | None, int]:
    part_type = part.get("type")
    if part_type == "text":
        text = str(part.get("text", ""))
        limit = min(MAX_WEB_TEXT_CHARS, max(0, text_budget))
        if limit <= 0:
            return None, 0
        rendered = _truncate_web_text(text, limit=limit)
        return {"type": "text", "text": rendered}, len(rendered)
    if part_type == "image":
        url = _web_media_url(str(part.get("url", "")))
        if url is None:
            return None, 0
        return {
            "type": "image",
            "url": url,
            "alt": _safe_optional_string(part.get("alt")),
            "title": _safe_optional_string(part.get("title")),
            "mime_type": _safe_optional_string(part.get("mime_type")),
        }, 0
    return None, 0


def _web_metadata(metadata: dict) -> dict:
    safe: dict[str, object] = {}
    for key in ("attachments", "images"):
        value = metadata.get(key)
        if isinstance(value, list):
            safe[key] = [_web_attachment(item) for item in value[:24]]
    return safe


def _web_attachment(value) -> object:
    if isinstance(value, str):
        url = _web_media_url(value)
        return url if url is not None else {}
    if not isinstance(value, dict):
        return {}
    url = _first_safe_media_url(value)
    payload = {
        key: _truncate_web_scalar(value[key], MAX_WEB_EVENT_TEXT_CHARS)
        for key in ("alt", "caption", "description", "title", "name", "filename", "mime_type", "mimeType")
        if key in value and isinstance(value[key], str)
    }
    if url is not None:
        payload["url"] = url
    for alias in ("src", "href", "image_url"):
        if alias in value and url is not None:
            payload[alias] = url
    return payload


def _first_safe_media_url(value: dict) -> str | None:
    for key in ("url", "src", "href", "image_url"):
        candidate = value.get(key)
        if isinstance(candidate, str):
            url = _web_media_url(candidate)
            if url is not None:
                return url
    return None


def _web_media_url(value: str) -> str | None:
    compact = value.strip()
    if not compact:
        return None
    if len(compact) > MAX_WEB_MEDIA_URL_CHARS:
        return None
    if compact.lower().startswith("data:") and len(compact) > MAX_WEB_MEDIA_URL_CHARS:
        return None
    return compact


def _safe_optional_string(value) -> str | None:
    if not isinstance(value, str):
        return None
    return _truncate_web_scalar(value, MAX_WEB_EVENT_TEXT_CHARS)


def _web_event_payload(event: AgentEvent) -> dict:
    payload = event.model_dump(mode="json")
    for key in ("message", "delta"):
        if isinstance(payload.get(key), str):
            payload[key] = _truncate_web_scalar(payload[key], MAX_WEB_EVENT_TEXT_CHARS)
    if isinstance(payload.get("tool_args"), dict):
        payload["tool_args"] = _web_lightweight_value(payload["tool_args"])
    if isinstance(payload.get("details"), dict):
        payload["details"] = _web_lightweight_value(payload["details"])
    if isinstance(payload.get("plan_step"), dict):
        payload["plan_step"] = _web_lightweight_value(payload["plan_step"])
    return payload


def _web_lightweight_value(value, *, depth: int = 0):
    if isinstance(value, str):
        return _truncate_web_scalar(value, MAX_WEB_EVENT_TEXT_CHARS)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if depth >= 3:
        return _preview_text(str(value), limit=160)
    if isinstance(value, list):
        return [_web_lightweight_value(item, depth=depth + 1) for item in value[:MAX_WEB_EVENT_COLLECTION_ITEMS]]
    if isinstance(value, dict):
        safe: dict[str, object] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_WEB_EVENT_OBJECT_KEYS:
                safe["_truncated_keys"] = len(value) - MAX_WEB_EVENT_OBJECT_KEYS
                break
            safe[str(key)] = _web_lightweight_value(item, depth=depth + 1)
        return safe
    return _preview_text(str(value), limit=160)


def _truncate_web_scalar(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    omitted = len(value) - limit
    return f"{value[:limit]}\n\n[Web preview truncated {omitted} characters to keep the browser responsive.]"


def _dict_message_text(message: dict) -> str:
    parts: list[str] = []
    for part in message.get("content", []):
        if isinstance(part, dict) and part.get("type") == "text":
            parts.append(str(part.get("text", "")))
    return "\n".join(parts)


def _preview_text(text: str, *, limit: int = 96) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _truncate_web_text(text: str, *, limit: int = MAX_WEB_TEXT_CHARS) -> str:
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n\n[Web preview truncated {omitted} characters to keep the browser responsive.]"
