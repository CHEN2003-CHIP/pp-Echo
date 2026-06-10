from __future__ import annotations

import os
from dataclasses import dataclass

from pp_agent.integrations.qqbot.errors import QQBotConfigError


@dataclass(frozen=True)
class QQBotConfig:
    enabled: bool
    app_id: str
    app_secret: str
    api_base: str
    token_url: str
    group_trigger: str
    allow_all_c2c: bool
    allowed_users: tuple[str, ...]
    allowed_groups: tuple[str, ...]
    reply_max_chars: int
    request_timeout: float
    dedupe_ttl_seconds: int
    session_store: str
    dedupe_store: str

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    def require_configured(self) -> None:
        if self.enabled and not self.configured:
            raise QQBotConfigError("QQ Bot is enabled but app id or app secret is missing.")


def load_qqbot_config(environ: dict[str, str] | None = None) -> QQBotConfig:
    env = environ if environ is not None else os.environ
    return QQBotConfig(
        enabled=_bool(env.get("PP_ECHO_QQBOT_ENABLED"), default=False),
        app_id=(env.get("PP_ECHO_QQBOT_APP_ID") or "").strip(),
        app_secret=(env.get("PP_ECHO_QQBOT_APP_SECRET") or "").strip(),
        api_base=(env.get("PP_ECHO_QQBOT_API_BASE") or "https://api.sgroup.qq.com").rstrip("/"),
        token_url=env.get("PP_ECHO_QQBOT_TOKEN_URL") or "https://bots.qq.com/app/getAppAccessToken",
        group_trigger=(env.get("PP_ECHO_QQBOT_GROUP_TRIGGER") or "/pp").strip() or "/pp",
        allow_all_c2c=_bool(env.get("PP_ECHO_QQBOT_ALLOW_ALL_C2C"), default=True),
        allowed_users=_csv(env.get("PP_ECHO_QQBOT_ALLOWED_USERS")),
        allowed_groups=_csv(env.get("PP_ECHO_QQBOT_ALLOWED_GROUPS")),
        reply_max_chars=_int(env.get("PP_ECHO_QQBOT_REPLY_MAX_CHARS"), default=1800, minimum=200),
        request_timeout=float(_int(env.get("PP_ECHO_QQBOT_REQUEST_TIMEOUT"), default=10, minimum=1)),
        dedupe_ttl_seconds=_int(env.get("PP_ECHO_QQBOT_DEDUPE_TTL_SECONDS"), default=600, minimum=1),
        session_store=env.get("PP_ECHO_QQBOT_SESSION_STORE") or ".pp-agent/integrations/qqbot-sessions.json",
        dedupe_store=env.get("PP_ECHO_QQBOT_DEDUPE_STORE") or ".pp-agent/integrations/qqbot-dedupe.json",
    )


def _bool(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _int(value: str | None, *, default: int, minimum: int) -> int:
    try:
        parsed = int(str(value).strip()) if value is not None else default
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default

