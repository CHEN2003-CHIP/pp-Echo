from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable

from pp_agent.integrations.qqbot.adapter import QQBotAdapter
from pp_agent.integrations.qqbot.config import load_qqbot_config
from pp_agent.integrations.qqbot.crypto import sign_callback_validation
from pp_agent.integrations.qqbot.errors import QQBotConfigError

logger = logging.getLogger(__name__)
WEBHOOK_PATH = "/api/integrations/qqbot/webhook"


def mount_qqbot_routes(app, active_workspace: Callable[[], Path], session_manager: Callable[[], object]) -> None:
    from fastapi import HTTPException, Request
    globals()["HTTPException"] = HTTPException
    globals()["Request"] = Request

    @app.get("/api/integrations/qqbot/status")
    def qqbot_status() -> dict:
        config = load_qqbot_config()
        return {
            "enabled": config.enabled,
            "configured": config.configured,
            "webhook_path": WEBHOOK_PATH,
            "group_trigger": config.group_trigger,
            "allow_all_c2c": config.allow_all_c2c,
            "allowed_users_count": len(config.allowed_users),
            "allowed_groups_count": len(config.allowed_groups),
        }

    @app.post(WEBHOOK_PATH)
    async def qqbot_webhook(request: Request) -> dict:
        config = load_qqbot_config()
        if not config.enabled:
            raise HTTPException(status_code=404, detail="QQ Bot integration is disabled.")
        try:
            config.require_configured()
        except QQBotConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        payload = await request.json()
        op = payload.get("op")
        if op == 13:
            data = payload.get("d") if isinstance(payload.get("d"), dict) else {}
            return sign_callback_validation(
                app_secret=config.app_secret,
                plain_token=str(data.get("plain_token") or ""),
                event_ts=str(data.get("event_ts") or ""),
            )
        if op == 0:
            adapter = QQBotAdapter(
                workspace=active_workspace(),
                session_manager=session_manager(),
                config=config,
            )
            _safe_create_task(adapter.handle_payload(payload))
            return {"op": 12}
        return {"op": 12}


def _safe_create_task(coro) -> asyncio.Task:
    async def runner() -> None:
        try:
            await coro
        except Exception:  # noqa: BLE001
            logger.exception("Unhandled QQ Bot background task error.")

    return asyncio.create_task(runner())
