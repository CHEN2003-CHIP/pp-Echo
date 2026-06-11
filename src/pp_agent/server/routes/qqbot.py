from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable

from pp_agent.integrations.qqbot.adapter import QQBotAdapter
from pp_agent.integrations.qqbot.config import load_qqbot_config
from pp_agent.integrations.qqbot.crypto import sign_callback_validation
from pp_agent.integrations.qqbot.errors import QQBotConfigError
from pp_agent.bots.manager import BotRuntimeManager
from pp_agent.bots.models import BotEvent

logger = logging.getLogger(__name__)
WEBHOOK_PATH = "/api/integrations/qqbot/webhook"
BOT_ID = "qq-main"


def mount_qqbot_routes(app, active_workspace: Callable[[], Path], session_manager: Callable[[], object]) -> None:
    from fastapi import HTTPException, Request
    globals()["HTTPException"] = HTTPException
    globals()["Request"] = Request

    @app.get("/api/integrations/qqbot/status")
    def qqbot_status() -> dict:
        config = load_qqbot_config()
        manager = _bot_manager(app, active_workspace())
        bot = manager.get_bot(BOT_ID)
        return {
            "enabled": bot["enabled"],
            "configured": config.configured,
            "webhook_path": WEBHOOK_PATH,
            "group_trigger": config.group_trigger,
            "allow_all_c2c": config.allow_all_c2c,
            "allowed_users_count": len(config.allowed_users),
            "allowed_groups_count": len(config.allowed_groups),
            "bot_id": BOT_ID,
            "bot_state": bot.get("bot_state"),
            "process_state": bot.get("process_state"),
            "last_event_at": bot.get("last_event_at"),
            "last_message_at": bot.get("last_message_at"),
        }

    @app.post(WEBHOOK_PATH)
    async def qqbot_webhook(request: Request) -> dict:
        manager = _bot_manager(app, active_workspace())
        bot_config = manager.registry.get_config(BOT_ID)
        config = load_qqbot_config()
        try:
            payload = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc
        op = payload.get("op")
        if op != 13 and not bot_config.enabled:
            manager.event_store.publish(
                BotEvent(
                    bot_id=bot_config.id,
                    platform=bot_config.platform,
                    type="message_ignored",
                    level="warning",
                    summary="QQ webhook event ignored because bot is stopped.",
                    metadata={"reason": "bot_stopped"},
                )
            )
            return {"op": 12}
        if op != 13 and config.enabled:
            try:
                config.require_configured()
            except QQBotConfigError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        elif op != 13 and not config.configured:
            raise HTTPException(status_code=500, detail="QQ Bot AppId/AppSecret is not configured.")
        elif op != 13:
            # Bot Center owns logical enablement; env PP_ECHO_QQBOT_ENABLED is no longer required.
            config = type(config)(**{**config.__dict__, "enabled": True})
        if op == 13 and not config.app_secret:
            manager.event_store.publish(
                BotEvent(
                    bot_id=bot_config.id,
                    platform=bot_config.platform,
                    type="webhook_verify_failed",
                    level="error",
                    summary="QQ webhook verification failed because AppSecret is not configured.",
                    metadata={"reason": "missing_app_secret"},
                )
            )
            raise HTTPException(status_code=400, detail="QQ Bot AppSecret is not configured.")
        if op == 13:
            data = payload.get("d") if isinstance(payload.get("d"), dict) else {}
            result = sign_callback_validation(
                app_secret=config.app_secret,
                plain_token=str(data.get("plain_token") or ""),
                event_ts=str(data.get("event_ts") or ""),
            )
            manager.event_store.publish(
                BotEvent(
                    bot_id=bot_config.id,
                    platform=bot_config.platform,
                    type="webhook_verified",
                    summary="QQ webhook verification succeeded.",
                    metadata={"simulated": False},
                )
            )
            return result
        if op == 0:
            adapter = QQBotAdapter(
                workspace=active_workspace(),
                session_manager=session_manager(),
                config=config,
                bot_manager=manager,
                bot_id=BOT_ID,
            )
            _safe_create_task(adapter.handle_payload(payload), manager=manager, bot_id=BOT_ID)
            return {"op": 12}
        return {"op": 12}


def _safe_create_task(coro, *, manager: BotRuntimeManager | None = None, bot_id: str = BOT_ID) -> asyncio.Task:
    async def runner() -> None:
        try:
            await coro
        except asyncio.CancelledError:
            if manager is not None:
                manager.event_store.publish(
                    BotEvent(
                        bot_id=bot_id,
                        platform="qq",
                        type="run_cancelled",
                        level="warning",
                        summary="QQ Bot background task was cancelled.",
                    )
                )
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Unhandled QQ Bot background task error.")
            if manager is not None:
                manager.event_store.publish(
                    BotEvent(
                        bot_id=bot_id,
                        platform="qq",
                        type="background_task_failed",
                        level="error",
                        summary="Unhandled QQ Bot background task error.",
                    )
                )

    task = asyncio.create_task(runner())
    if manager is not None:
        manager.register_task(bot_id, task)
    return task


def _bot_manager(app, workspace: Path) -> BotRuntimeManager:
    manager = getattr(app.state, "bot_runtime_manager", None)
    if manager is None or getattr(manager, "workspace", None) != workspace:
        manager = BotRuntimeManager(workspace)
        app.state.bot_runtime_manager = manager
    return manager
