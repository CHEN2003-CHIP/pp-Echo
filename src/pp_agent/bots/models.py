from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BotConfig(BaseModel):
    id: str
    type: str
    platform: str
    name: str
    enabled: bool = False
    description: Optional[str] = None
    adapter: Dict[str, Any] = Field(default_factory=dict)
    ingress: Dict[str, Any] = Field(default_factory=dict)
    routing: Dict[str, Any] = Field(default_factory=dict)
    security: Dict[str, Any] = Field(default_factory=dict)


class BotStatus(BaseModel):
    bot_id: str
    type: str
    platform: str
    name: str
    enabled: bool
    configured: bool = False
    desired_state: Literal["enabled", "disabled"] = "disabled"
    process_state: Literal["not_managed", "starting", "running", "stopping", "stopped", "error", "crashed"] = "not_managed"
    agent_state: Literal["idle", "receiving", "running_agent", "waiting_approval", "error"] = "idle"
    ingress_state: Literal["local_only", "public_configured", "public_reachable", "public_unreachable", "tunnel_starting", "public_error", "unknown"] = "local_only"
    qq_state: Literal["not_configured", "configured", "token_ok", "token_error", "unknown"] = "unknown"
    bot_state: Literal["idle", "receiving", "running_agent", "replying", "waiting_approval", "error"] = "idle"
    local_url: Optional[str] = None
    public_url: Optional[str] = None
    webhook_url: Optional[str] = None
    bot_path: str
    pid: Optional[int] = None
    started_at: Optional[datetime] = None
    last_heartbeat_at: Optional[datetime] = None
    last_event_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
    last_reply_at: Optional[datetime] = None
    last_error: Optional[str] = None
    last_run_at: Optional[datetime] = None
    warnings: List[str] = Field(default_factory=list)
    still_running_count: int = 0
    queued_count: int = 0
    effective_policy: Dict[str, Any] = Field(default_factory=dict)


class BotEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex}")
    bot_id: str
    platform: str
    type: str
    level: Literal["debug", "info", "warning", "error"] = "info"
    timestamp: datetime = Field(default_factory=utc_now)
    summary: str
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    trace_id: Optional[str] = None
    approval_id: Optional[str] = None
    message_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BotSource(BaseModel):
    bot_id: str
    platform: str
    bot_path: str
    conversation_type: Literal["c2c", "group", "channel", "unknown"] = "unknown"
    channel_id: Optional[str] = None
    user_id: Optional[str] = None
    message_id: Optional[str] = None
    raw_event_id: Optional[str] = None


class NormalizedBotMessage(BaseModel):
    source: BotSource
    text: str
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=utc_now)


def default_qq_main_config() -> BotConfig:
    return BotConfig(
        id="qq-main",
        type="qqbot",
        platform="qq",
        name="QQ 主机器人",
        enabled=False,
        description="QQ official webhook bot for pp-Echo",
        ingress={
            "mode": "qq_only_proxy",
            "local_host": "127.0.0.1",
            "local_port": 8788,
            "public_url": "",
            "tunnel": {"provider": "manual", "managed": False, "command": ""},
        },
        routing={"private_chat": True, "group_trigger": "/pp", "default_session_policy": "per_conversation"},
        security={
            "allowed_user_ids": [],
            "allowed_group_ids": [],
            "require_approval_for_tools": True,
            "allow_shell": False,
            "allowed_workspace_roots": [],
        },
    )
