from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)
SUPPORTED_EVENT_TYPES = {
    "C2C_MSG_RECEIVE",
    "C2C_MESSAGE_CREATE",
    "GROUP_MSG_RECEIVE",
    "GROUP_MESSAGE_CREATE",
    "GROUP_AT_MESSAGE_CREATE",
}


@dataclass(frozen=True)
class QQIncomingMessage:
    event_id: str
    event_type: str
    message_id: str
    conversation_type: Literal["c2c", "group"]
    conversation_key: str
    openid: str | None
    group_openid: str | None
    user_openid: str | None
    content: str
    raw: dict[str, Any]


def parse_incoming_message(payload: dict[str, Any]) -> QQIncomingMessage | None:
    event_type = str(payload.get("t") or "")
    if event_type not in SUPPORTED_EVENT_TYPES:
        return None
    data = payload.get("d") if isinstance(payload.get("d"), dict) else {}
    event_id = str(payload.get("id") or payload.get("s") or data.get("event_id") or "")
    message_id = str(data.get("id") or data.get("msg_id") or data.get("message_id") or "")
    content = str(data.get("content") or "").strip()
    if event_type in {"C2C_MSG_RECEIVE", "C2C_MESSAGE_CREATE"}:
        user_openid = _author_user_openid(data) or _first_string(data, "openid", "user_openid", "author_openid")
        openid = _first_string(data, "openid", "user_openid", "author_openid") or user_openid
        if not event_id or not message_id or not openid:
            logger.warning("Ignoring malformed QQ C2C event: missing id/message/openid")
            return None
        return QQIncomingMessage(
            event_id=event_id,
            event_type=event_type,
            message_id=message_id,
            conversation_type="c2c",
            conversation_key=f"qq:c2c:{openid}",
            openid=openid,
            group_openid=None,
            user_openid=user_openid,
            content=content,
            raw=payload,
        )
    group_openid = _first_string(data, "group_openid", "group_id", "groupOpenid")
    user_openid = _author_user_openid(data) or _first_string(data, "user_openid", "openid")
    if not event_id or not message_id or not group_openid:
        logger.warning("Ignoring malformed QQ group event: missing id/message/group_openid")
        return None
    return QQIncomingMessage(
        event_id=event_id,
        event_type=event_type,
        message_id=message_id,
        conversation_type="group",
        conversation_key=f"qq:group:{group_openid}",
        openid=None,
        group_openid=group_openid,
        user_openid=user_openid,
        content=content,
        raw=payload,
    )


def _first_string(data: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = data.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _author_user_openid(data: dict[str, Any]) -> str | None:
    author = data.get("author") if isinstance(data.get("author"), dict) else {}
    return _first_string(author, "user_openid", "openid", "id")
