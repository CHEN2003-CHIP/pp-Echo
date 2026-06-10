from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from pp_agent.bots.manager import BotRuntimeManager
from pp_agent.bots.models import BotEvent, BotSource, NormalizedBotMessage, utc_now
from pp_agent.bots.paths import get_bot_root
from pp_agent.integrations.qqbot.client import QQBotClient
from pp_agent.integrations.qqbot.config import QQBotConfig
from pp_agent.integrations.qqbot.dedupe import QQEventDedupeStore
from pp_agent.integrations.qqbot.schema import QQIncomingMessage, parse_incoming_message
from pp_agent.integrations.qqbot.session_store import QQSessionStore

logger = logging.getLogger(__name__)
APPROVAL_REPLY = "This action needs approval in the local pp-Echo Web UI."
ERROR_REPLY_PREFIX = "pp-Echo failed while processing this QQ message"
TRUNCATION_SUFFIX = "\n\n...内容较长，已截断。Open pp-Echo Web UI for the full result."


class QQBotAdapter:
    def __init__(
        self,
        *,
        workspace: Path,
        session_manager: Any,
        config: QQBotConfig,
        client: QQBotClient | None = None,
        session_store: QQSessionStore | None = None,
        dedupe_store: QQEventDedupeStore | None = None,
        bot_manager: BotRuntimeManager | None = None,
        bot_id: str = "qq-main",
    ) -> None:
        self.workspace = workspace
        self.session_manager = session_manager
        self.config = config
        self.client = client or QQBotClient(config)
        self.session_store = session_store or QQSessionStore(workspace / config.session_store)
        self.dedupe_store = dedupe_store or QQEventDedupeStore(workspace / config.dedupe_store, ttl_seconds=config.dedupe_ttl_seconds)
        self.bot_manager = bot_manager
        self.bot_id = bot_id

    async def handle_payload(self, payload: dict[str, Any]) -> None:
        if payload.get("op") != 0:
            return
        message = parse_incoming_message(payload)
        if message is None:
            logger.info("Ignoring unsupported or malformed QQ event.")
            self._event("message_ignored", "Ignoring unsupported or malformed QQ event.", level="warning", metadata={"reason": "unsupported_event_type"})
            return
        event_key = f"qq:{message.event_id}:{message.message_id}"
        if self.dedupe_store.seen_or_mark(event_key):
            logger.info("Ignoring duplicate QQ event %s", redact_id(message.event_id))
            self._event("message_ignored", "Ignoring duplicate QQ event.", metadata={"reason": "duplicate", "raw_event_id": message.event_id})
            return

        source = self._source(message)
        prompt_text = self._prompt_from_message(message)
        if prompt_text is None:
            self._event(
                "message_ignored",
                "QQ group message ignored because it did not include the trigger.",
                level="warning",
                message_id=message.message_id,
                metadata={"reason": "missing_group_trigger", "source": source.model_dump(mode="json", exclude_none=True)},
            )
            return
        if not self._allowed(message):
            reason = "user_not_allowed" if message.conversation_type == "c2c" else "group_not_allowed"
            logger.warning("QQ message denied by allowlist: %s", redact_id(message.conversation_key))
            self._event(
                "message_ignored",
                "QQ message ignored by allowlist.",
                level="warning",
                message_id=message.message_id,
                metadata={"reason": reason, "source": source.model_dump(mode="json", exclude_none=True)},
            )
            return

        normalized = NormalizedBotMessage(source=source, text=prompt_text, raw=payload)
        self._record_message(normalized)
        self._event(
            "message_received",
            "QQ message received.",
            message_id=message.message_id,
            metadata={"source": source.model_dump(mode="json", exclude_none=True), "text_preview": prompt_text[:160]},
        )

        session_id = self.session_store.resolve(
            message.conversation_key,
            message.conversation_type,
            session_id_factory=self._create_session_id,
        )
        run_id = f"run_{uuid4().hex}"
        run_info = {
            "run_id": run_id,
            "session_id": session_id,
            "trace_id": None,
            "source": source.model_dump(mode="json", exclude_none=True),
            "input_preview": prompt_text[:240],
            "status": "running",
            "started_at": utc_now().isoformat(),
            "finished_at": None,
            "error": None,
            "trace_path": None,
        }
        self._record_run(run_info)

        try:
            attachment_note = await maybe_ingest_qq_attachments(message.raw, session_id=session_id)
            wrapped_prompt = build_agent_prompt(message, prompt_text, attachment_note=attachment_note, source=source)
            self._event(
                "agent_run_started",
                "QQ message started an Agent run.",
                session_id=session_id,
                run_id=run_id,
                message_id=message.message_id,
                metadata={"source": source.model_dump(mode="json", exclude_none=True)},
            )
            try:
                result = await self._run_agent(session_id, wrapped_prompt)
            except FileNotFoundError:
                session_id = self.session_store.replace(
                    message.conversation_key,
                    message.conversation_type,
                    self._create_session_id(),
                )
                run_info["session_id"] = session_id
                result = await self._run_agent(session_id, wrapped_prompt)
            needs_approval = approval_reply_if_needed(result) is not None
            reply = approval_reply_if_needed(result) or extract_reply_text(result)
            run_info.update({"status": "waiting_approval" if needs_approval else "completed", "finished_at": utc_now().isoformat()})
            self._record_run(run_info)
            if needs_approval:
                self._event("approval_required", "Agent run is waiting for approval.", session_id=session_id, run_id=run_id, metadata={"source": source.model_dump(mode="json", exclude_none=True)})
            self._event("agent_run_completed", "Agent run completed.", session_id=session_id, run_id=run_id, metadata={"source": source.model_dump(mode="json", exclude_none=True)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("QQ adapter failed while processing event %s", redact_id(message.event_id))
            reply = f"{ERROR_REPLY_PREFIX}: {type(exc).__name__}. See local logs or TraceInspect."
            run_info.update({"status": "error", "finished_at": utc_now().isoformat(), "error": type(exc).__name__})
            self._record_run(run_info)
            self._event("error", f"QQ adapter failed: {type(exc).__name__}", level="error", session_id=session_id, run_id=run_id, metadata={"source": source.model_dump(mode="json", exclude_none=True)})

        try:
            await self._send_reply(message, truncate_reply(reply, self.config.reply_max_chars))
            self._event("reply_sent", "QQ reply sent.", session_id=session_id, run_id=run_id, message_id=message.message_id, metadata={"source": source.model_dump(mode="json", exclude_none=True)})
        except Exception as exc:  # noqa: BLE001
            self._event("reply_failed", f"QQ reply failed: {type(exc).__name__}", level="error", session_id=session_id, run_id=run_id, message_id=message.message_id, metadata={"source": source.model_dump(mode="json", exclude_none=True)})
            raise

    def _prompt_from_message(self, message: QQIncomingMessage) -> str | None:
        if message.conversation_type == "c2c":
            return message.content
        text = message.content.strip()
        if not is_group_triggered(text, self.config.group_trigger):
            logger.info("Ignoring QQ group message without trigger.")
            return None
        prompt = text[len(self.config.group_trigger) :].strip()
        return prompt or "Please briefly introduce pp-Echo QQ Bot usage."

    def _allowed(self, message: QQIncomingMessage) -> bool:
        if message.conversation_type == "c2c":
            return self.config.allow_all_c2c or (message.openid in self.config.allowed_users)
        return not self.config.allowed_groups or (message.group_openid in self.config.allowed_groups)

    async def _run_agent(self, session_id: str, prompt: str) -> Any:
        def run_and_wait() -> Any:
            handle = self.session_manager.get_handle(session_id)
            result = handle.prompt(prompt)
            worker = getattr(handle, "_worker", None)
            if worker is not None and hasattr(worker, "join"):
                worker.join()
            snapshot = handle.snapshot() if hasattr(handle, "snapshot") else {}
            if _snapshot_has_pending_approval(snapshot):
                return {"pending_approval": True, "snapshot": snapshot, **(result if isinstance(result, dict) else {})}
            return snapshot or result

        return await asyncio.to_thread(run_and_wait)

    def _create_session_id(self) -> str:
        creator = getattr(self.session_manager, "create_session", None)
        if callable(creator):
            snapshot = creator()
            session_id = snapshot.get("session_id") or snapshot.get("id") if isinstance(snapshot, dict) else None
            if session_id:
                return str(session_id)
        import uuid

        return str(uuid.uuid4())

    async def _send_reply(self, message: QQIncomingMessage, reply: str) -> None:
        if message.conversation_type == "c2c" and message.openid:
            await self.client.send_c2c_text(message.openid, reply, msg_id=message.message_id, event_id=message.event_id)
        elif message.conversation_type == "group" and message.group_openid:
            await self.client.send_group_text(message.group_openid, reply, msg_id=message.message_id, event_id=message.event_id)

    def _source(self, message: QQIncomingMessage) -> BotSource:
        return BotSource(
            bot_id=self.bot_id,
            platform="qq",
            bot_path=str(get_bot_root(self.workspace, "qq", self.bot_id)),
            conversation_type=message.conversation_type,
            channel_id=message.group_openid if message.conversation_type == "group" else message.openid,
            user_id=message.user_openid or message.openid,
            message_id=message.message_id,
            raw_event_id=message.event_id,
        )

    def _event(
        self,
        event_type: str,
        summary: str,
        *,
        level: str = "info",
        session_id: str | None = None,
        run_id: str | None = None,
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.bot_manager is None:
            return
        self.bot_manager.event_store.publish(
            BotEvent(
                bot_id=self.bot_id,
                platform="qq",
                type=event_type,
                level=level,
                summary=summary,
                session_id=session_id,
                run_id=run_id,
                message_id=message_id,
                metadata=metadata or {},
            )
        )

    def _record_message(self, message: NormalizedBotMessage) -> None:
        if self.bot_manager is not None:
            self.bot_manager.record_message(self.bot_id, message)

    def _record_run(self, run_info: dict[str, Any]) -> None:
        if self.bot_manager is not None:
            self.bot_manager.record_run(self.bot_id, run_info)


def is_group_triggered(text: str, trigger: str) -> bool:
    return text.strip().startswith(trigger)


async def maybe_ingest_qq_attachments(raw: dict[str, Any], *, session_id: str) -> str | None:
    _ = session_id
    data = raw.get("d") if isinstance(raw.get("d"), dict) else {}
    for key in ("attachments", "attachment", "media", "file", "files", "images"):
        value = data.get(key)
        if value:
            return "The QQ message includes attachments or media, but this adapter currently handles text only."
    return None


def build_agent_prompt(message: QQIncomingMessage, text: str, *, attachment_note: str | None = None, source: BotSource | None = None) -> str:
    lines = [
        "[QQ Bot Message]",
        "source=qq",
        f"bot_id={source.bot_id if source else 'qq-main'}",
        f"conversation_type={message.conversation_type}",
        f"conversation_key={redact_id(message.conversation_key)}",
        f"sender={redact_id(message.user_openid or message.openid or '')}",
        "",
        "User message:",
        text,
    ]
    if attachment_note:
        lines.extend(["", attachment_note])
    return "\n".join(lines)


def extract_reply_text(result: Any) -> str:
    if isinstance(result, str):
        return result.strip() or "pp-Echo did not return sendable text."
    if isinstance(result, dict):
        for key in ("reply", "assistant", "content", "text", "message"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        text = _messages_reply_text(result.get("messages")) or _events_reply_text(result.get("events"))
        return text or "pp-Echo processed the message, but returned no sendable text."
    for attr in ("reply", "content"):
        value = getattr(result, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "pp-Echo processed the message, but returned no sendable text."


def approval_reply_if_needed(result: Any) -> str | None:
    if isinstance(result, dict) and (result.get("pending_approval") or result.get("pending_plan_token")):
        return APPROVAL_REPLY
    if isinstance(result, dict):
        control = result.get("runtime_control") if isinstance(result.get("runtime_control"), dict) else {}
        if control.get("pending_plan_token") or "approval" in str(control.get("status", "")):
            return APPROVAL_REPLY
    return None


def truncate_reply(text: str, max_chars: int) -> str:
    limit = max(1, int(max_chars))
    if len(text) <= limit:
        return text
    suffix = TRUNCATION_SUFFIX
    return text[: max(1, limit - len(suffix))].rstrip() + suffix


def redact_id(value: str) -> str:
    value = str(value or "")
    if len(value) <= 10:
        return "***"
    return value[:6] + "..." + value[-4:]


def _snapshot_has_pending_approval(snapshot: dict[str, Any]) -> bool:
    return bool(snapshot.get("pending_plan_token") or snapshot.get("pending_tool_call_count") or snapshot.get("pending_artifacts"))


def _messages_reply_text(messages: Any) -> str | None:
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", "")
        if role != "assistant":
            continue
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", [])
        parts: list[str] = []
        for part in content or []:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
            elif hasattr(part, "text"):
                parts.append(str(part.text))
        text = "\n".join(part for part in parts if part).strip()
        if text:
            return text
    return None


def _events_reply_text(events: Any) -> str | None:
    if not isinstance(events, list):
        return None
    chunks: list[str] = []
    for event in events:
        if isinstance(event, dict) and event.get("type") == "message_delta" and isinstance(event.get("delta"), str):
            chunks.append(event["delta"])
    return "".join(chunks).strip() or None
