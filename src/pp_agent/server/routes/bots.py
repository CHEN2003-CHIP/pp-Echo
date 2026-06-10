from __future__ import annotations

from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from pp_agent.bots.manager import BotRuntimeManager
from pp_agent.bots.models import BotEvent
from pp_agent.integrations.qqbot.crypto import sign_callback_validation
from pp_agent.integrations.qqbot.config import load_qqbot_config


class ConfigPatchRequest(BaseModel):
    patch: dict


class PublicUrlRequest(BaseModel):
    public_url: str


def mount_bot_routes(app, active_workspace: Callable[[], Path]) -> None:
    from fastapi import HTTPException

    def manager() -> BotRuntimeManager:
        return getattr(app.state, "bot_runtime_manager", None) or _make_manager(app, active_workspace())

    @app.get("/api/bots")
    def list_bots() -> dict:
        return {"bots": manager().list_bots()}

    @app.get("/api/bots/events/stream")
    def bot_events_stream() -> dict:
        # Polling remains the stable first implementation; this endpoint keeps the API surface reserved.
        return {"events": [], "streaming": False}

    @app.get("/api/bots/{bot_id}")
    def bot_detail(bot_id: str) -> dict:
        try:
            return manager().get_detail(bot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"message": f"Unknown bot: {bot_id}"}) from exc

    @app.get("/api/bots/{bot_id}/events")
    def bot_events(bot_id: str, limit: int = 100) -> dict:
        try:
            config = manager().registry.get_config(bot_id)
            return {"events": manager().event_store.list_events(config.platform, config.id, limit=limit)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"message": f"Unknown bot: {bot_id}"}) from exc

    @app.get("/api/bots/{bot_id}/messages")
    def bot_messages(bot_id: str, limit: int = 100) -> dict:
        try:
            config = manager().registry.get_config(bot_id)
            return {"messages": manager().event_store.list_messages(config.platform, config.id, limit=limit)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"message": f"Unknown bot: {bot_id}"}) from exc

    @app.get("/api/bots/{bot_id}/runs")
    def bot_runs(bot_id: str, limit: int = 50) -> dict:
        try:
            config = manager().registry.get_config(bot_id)
            return {"runs": manager().event_store.list_runs(config.platform, config.id, limit=limit)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"message": f"Unknown bot: {bot_id}"}) from exc

    @app.get("/api/bots/{bot_id}/traces")
    def bot_traces(bot_id: str, limit: int = 50) -> dict:
        try:
            config = manager().registry.get_config(bot_id)
            return {"traces": manager().event_store.list_traces(config.platform, config.id, limit=limit)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"message": f"Unknown bot: {bot_id}"}) from exc

    @app.post("/api/bots/{bot_id}/start")
    def start_bot(bot_id: str) -> dict:
        try:
            return manager().start_bot(bot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"message": f"Unknown bot: {bot_id}"}) from exc

    @app.post("/api/bots/{bot_id}/stop")
    def stop_bot(bot_id: str) -> dict:
        try:
            return manager().stop_bot(bot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"message": f"Unknown bot: {bot_id}"}) from exc

    @app.post("/api/bots/{bot_id}/restart")
    def restart_bot(bot_id: str) -> dict:
        try:
            return manager().restart_bot(bot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"message": f"Unknown bot: {bot_id}"}) from exc

    @app.patch("/api/bots/{bot_id}/config")
    def patch_bot_config(bot_id: str, request: ConfigPatchRequest) -> dict:
        try:
            return manager().update_config(bot_id, request.patch)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"message": f"Unknown bot: {bot_id}"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc

    @app.post("/api/bots/{bot_id}/public-url")
    def set_public_url(bot_id: str, request: PublicUrlRequest) -> dict:
        try:
            return manager().set_public_url(bot_id, request.public_url)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"message": f"Unknown bot: {bot_id}"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc

    @app.get("/api/bots/{bot_id}/webhook-url")
    def webhook_url(bot_id: str) -> dict:
        try:
            return manager().get_webhook_url(bot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"message": f"Unknown bot: {bot_id}"}) from exc

    @app.post("/api/bots/{bot_id}/test-status")
    def test_status(bot_id: str) -> dict:
        try:
            return manager().healthcheck(bot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"message": f"Unknown bot: {bot_id}"}) from exc

    @app.post("/api/bots/{bot_id}/test-webhook-verify")
    def test_webhook_verify(bot_id: str) -> dict:
        try:
            config = manager().registry.get_config(bot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"message": f"Unknown bot: {bot_id}"}) from exc
        qq_config = load_qqbot_config()
        if not qq_config.app_secret:
            raise HTTPException(status_code=400, detail={"message": "QQ AppSecret is not configured."})
        result = sign_callback_validation(app_secret=qq_config.app_secret, plain_token="pp-echo-test", event_ts="1234567890")
        manager().event_store.publish(
            BotEvent(
                bot_id=config.id,
                platform=config.platform,
                type="webhook_verified",
                summary="Webhook verification simulation succeeded.",
                metadata={"simulated": True},
            )
        )
        return result


def _make_manager(app, workspace: Path) -> BotRuntimeManager:
    manager = BotRuntimeManager(workspace)
    app.state.bot_runtime_manager = manager
    return manager
