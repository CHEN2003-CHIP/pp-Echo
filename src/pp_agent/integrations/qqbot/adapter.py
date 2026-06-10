from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from pp_agent.integrations.qqbot.client import QQBotClient
from pp_agent.integrations.qqbot.config import QQBotConfig
from pp_agent.integrations.qqbot.dedupe import QQEventDedupeStore
from pp_agent.integrations.qqbot.schema import QQIncomingMessage, parse_incoming_message
from pp_agent.integrations.qqbot.session_store import QQSessionStore

logger = logging.getLogger(__name__)
APPROVAL_REPLY = "这个操作需要在 pp-Echo Web UI 中审批。我已经创建了待审批动作，请到本地 Web UI 查看。"
ERROR_REPLY_PREFIX = "pp-Echo 处理这条消息时出错"
TRUNCATION_SUFFIX = "\n\n...内容较长，已截断。请在 pp-Echo Web UI 查看完整结果。"


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
    ) -> None:
        self.workspace = workspace
        self.session_manager = session_manager
        self.config = config
        self.client = client or QQBotClient(config)
        self.session_store = session_store or QQSessionStore(workspace / config.session_store)
        self.dedupe_store = dedupe_store or QQEventDedupeStore(workspace / config.dedupe_store, ttl_seconds=config.dedupe_ttl_seconds)

    async def handle_payload(self, payload: dict[str, Any]) -> None:
        if payload.get("op") != 0:
            return
        message = parse_incoming_message(payload)
        if message is None:
            logger.info("Ignoring unsupported or malformed QQ event.")
            return
        event_key = f"qq:{message.event_id}:{message.message_id}"
        if self.dedupe_store.seen_or_mark(event_key):
            logger.info("Ignoring duplicate QQ event %s", redact_id(message.event_id))
            return
        prompt_text = self._prompt_from_message(message)
        if prompt_text is None:
            return
        if not self._allowed(message):
            logger.warning("QQ message denied by allowlist: %s", redact_id(message.conversation_key))
            return
        session_id = self.session_store.resolve(message.conversation_key, message.conversation_type)
        try:
            attachment_note = await maybe_ingest_qq_attachments(message.raw, session_id=session_id)
            wrapped_prompt = build_agent_prompt(message, prompt_text, attachment_note=attachment_note)
            result = await self._run_agent(session_id, wrapped_prompt)
            reply = approval_reply_if_needed(result) or extract_reply_text(result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("QQ adapter failed while processing event %s", redact_id(message.event_id))
            reply = f"{ERROR_REPLY_PREFIX}：{type(exc).__name__}。请查看本地日志或 TraceInspect。"
        await self._send_reply(message, truncate_reply(reply, self.config.reply_max_chars))

    def _prompt_from_message(self, message: QQIncomingMessage) -> str | None:
        if message.conversation_type == "c2c":
            return message.content
        text = message.content.strip()
        if not is_group_triggered(text, self.config.group_trigger):
            logger.info("Ignoring QQ group message without trigger.")
            return None
        prompt = text[len(self.config.group_trigger) :].strip()
        return prompt or "请简单介绍 pp-Echo 的 QQ Bot 用法。"

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

    async def _send_reply(self, message: QQIncomingMessage, reply: str) -> None:
        if message.conversation_type == "c2c" and message.openid:
            await self.client.send_c2c_text(message.openid, reply, msg_id=message.message_id, event_id=message.event_id)
        elif message.conversation_type == "group" and message.group_openid:
            await self.client.send_group_text(message.group_openid, reply, msg_id=message.message_id, event_id=message.event_id)


def is_group_triggered(text: str, trigger: str) -> bool:
    return text.strip().startswith(trigger)


async def maybe_ingest_qq_attachments(raw: dict[str, Any], *, session_id: str) -> str | None:
    _ = session_id
    data = raw.get("d") if isinstance(raw.get("d"), dict) else {}
    for key in ("attachments", "attachment", "media", "file", "files", "images"):
        value = data.get(key)
        if value:
            return "该 QQ 消息包含附件或媒体，但当前 QQ adapter 仅稳定支持文本，尚未实现下载到 AttachmentService。"
    return None


def build_agent_prompt(message: QQIncomingMessage, text: str, *, attachment_note: str | None = None) -> str:
    lines = [
        "[QQ Bot Message]",
        "source=qq",
        f"conversation_type={message.conversation_type}",
        f"conversation_key={redact_id(message.conversation_key)}",
        f"sender={redact_id(message.user_openid or message.openid or '')}",
        "",
        "用户消息:",
        text,
    ]
    if attachment_note:
        lines.extend(["", attachment_note])
    return "\n".join(lines)


def extract_reply_text(result: Any) -> str:
    if isinstance(result, str):
        return result.strip() or "pp-Echo 没有返回可发送的文本。"
    if isinstance(result, dict):
        for key in ("reply", "assistant", "content", "text", "message"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        text = _messages_reply_text(result.get("messages")) or _events_reply_text(result.get("events"))
        return text or "pp-Echo 已处理，但没有返回可发送的文本。"
    for attr in ("reply", "content"):
        value = getattr(result, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "pp-Echo 已处理，但没有返回可发送的文本。"


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

