from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from pp_agent.bots.events import BotEventStore
from pp_agent.bots.models import BotConfig, BotEvent, BotStatus, utc_now
from pp_agent.bots.paths import ensure_bot_dirs, get_bot_root
from pp_agent.bots.registry import BotRegistry
from pp_agent.integrations.qqbot.config import load_qqbot_config

WEBHOOK_PATH = "/api/integrations/qqbot/webhook"


class BotRuntimeManager:
    def __init__(self, workspace: Path, *, registry: BotRegistry | None = None, event_store: BotEventStore | None = None) -> None:
        self.workspace = Path(workspace)
        self.registry = registry or BotRegistry(workspace)
        self.event_store = event_store or BotEventStore(workspace)
        self.registry.ensure_default()

    def list_bots(self) -> list[dict[str, Any]]:
        return [self._summary(config) for config in self.registry.list_configs()]

    def get_bot(self, bot_id: str) -> dict[str, Any]:
        return self._summary(self.registry.get_config(bot_id))

    def get_detail(self, bot_id: str) -> dict[str, Any]:
        config = self.registry.get_config(bot_id)
        status = self._status(config)
        return {
            "config": config.model_dump(mode="json", exclude_none=True),
            "status": status.model_dump(mode="json", exclude_none=True),
            "webhook_url": self.get_webhook_url(bot_id)["webhook_url"],
            "paths": self._paths(config),
            "events": self.event_store.list_events(config.platform, config.id, limit=50),
            "messages": self.event_store.list_messages(config.platform, config.id, limit=50),
            "runs": self.event_store.list_runs(config.platform, config.id, limit=50),
            "traces": self.event_store.list_traces(config.platform, config.id, limit=50),
            "logs": self.event_store.read_logs(config.platform, config.id, limit=120),
        }

    def start_bot(self, bot_id: str) -> dict[str, Any]:
        config = self.registry.enable(bot_id)
        status = self._status(config, process_state="running", bot_state="idle")
        status.started_at = status.started_at or utc_now()
        status.last_heartbeat_at = utc_now()
        self.event_store.write_status(status)
        self._publish(config, "bot_started", "Bot started by Web control plane.")
        return self.get_detail(bot_id)

    def stop_bot(self, bot_id: str) -> dict[str, Any]:
        config = self.registry.disable(bot_id)
        status = self._status(config, process_state="stopped", bot_state="idle")
        self.event_store.write_status(status)
        self._publish(config, "bot_stopped", "Bot stopped by Web control plane.")
        return self.get_detail(bot_id)

    def restart_bot(self, bot_id: str) -> dict[str, Any]:
        self.stop_bot(bot_id)
        return self.start_bot(bot_id)

    def healthcheck(self, bot_id: str) -> dict[str, Any]:
        config = self.registry.get_config(bot_id)
        status = self._status(config)
        status.last_heartbeat_at = utc_now()
        self.event_store.write_status(status)
        return {"ok": True, "status": status.model_dump(mode="json", exclude_none=True)}

    def update_config(self, bot_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        config = self.registry.update_config(bot_id, patch)
        self.event_store.write_status(self._status(config))
        self._publish(config, "bot_health_changed", "Bot configuration updated.")
        return self.get_detail(bot_id)

    def set_public_url(self, bot_id: str, public_url: str) -> dict[str, Any]:
        public_url = str(public_url or "").strip().rstrip("/")
        if public_url and not public_url.startswith(("http://", "https://")):
            raise ValueError("public_url must start with http:// or https://")
        detail = self.update_config(bot_id, {"ingress": {"public_url": public_url}})
        config = self.registry.get_config(bot_id)
        self._publish(
            config,
            "tunnel_url_updated",
            "Public URL updated." if public_url else "Public URL cleared.",
            metadata={"public_url": public_url, "webhook_url": self.get_webhook_url(bot_id)["webhook_url"]},
        )
        return detail

    def get_webhook_url(self, bot_id: str) -> dict[str, Any]:
        config = self.registry.get_config(bot_id)
        public_url = str(config.ingress.get("public_url") or "").strip().rstrip("/")
        return {"bot_id": bot_id, "public_url": public_url, "webhook_url": f"{public_url}{WEBHOOK_PATH}" if public_url else ""}

    def record_message(self, bot_id: str, message) -> None:
        self.event_store.record_message(message)

    def record_run(self, bot_id: str, run_info: dict[str, Any]) -> Path:
        config = self.registry.get_config(bot_id)
        run_id = str(run_info.get("run_id") or f"run_{uuid4().hex}")
        return self.event_store.write_run(config.platform, config.id, run_id, run_info)

    def record_trace(self, bot_id: str, trace_info: dict[str, Any]) -> Path:
        config = self.registry.get_config(bot_id)
        trace_id = str(trace_info.get("trace_id") or f"trace_{uuid4().hex}")
        trace_dir = get_bot_root(self.workspace, config.platform, config.id) / "traces" / date.today().isoformat()
        trace_dir.mkdir(parents=True, exist_ok=True)
        path = trace_dir / f"{trace_id}.json"
        path.write_text(str(trace_info), encoding="utf-8")
        return path

    def _summary(self, config: BotConfig) -> dict[str, Any]:
        status = self._status(config)
        return {
            "id": config.id,
            "type": config.type,
            "platform": config.platform,
            "name": config.name,
            "enabled": config.enabled,
            "description": config.description,
            "process_state": status.process_state,
            "bot_state": status.bot_state,
            "ingress_state": status.ingress_state,
            "configured": status.configured,
            "last_event_at": status.last_event_at.isoformat() if status.last_event_at else None,
            "last_message_at": status.last_message_at.isoformat() if status.last_message_at else None,
            "last_error": status.last_error,
            "status_text": _status_text(status),
        }

    def _status(self, config: BotConfig, *, process_state: str | None = None, bot_state: str | None = None) -> BotStatus:
        saved = self.event_store.read_status(config.platform, config.id) or {}
        qq_config = load_qqbot_config() if config.platform == "qq" else None
        local_host = str(config.ingress.get("local_host") or "127.0.0.1")
        local_port = int(config.ingress.get("local_port") or 8788)
        public_url = str(config.ingress.get("public_url") or "").strip().rstrip("/") or None
        status = BotStatus(
            bot_id=config.id,
            type=config.type,
            platform=config.platform,
            name=config.name,
            enabled=config.enabled,
            configured=bool(qq_config.configured) if qq_config is not None else True,
            process_state=process_state or ("running" if config.enabled else "stopped"),
            ingress_state="public_reachable" if public_url else "local_only",
            bot_state=bot_state or saved.get("bot_state") or "idle",
            local_url=f"http://{local_host}:{local_port}",
            public_url=public_url,
            webhook_url=f"{public_url}{WEBHOOK_PATH}" if public_url else None,
            bot_path=str(get_bot_root(self.workspace, config.platform, config.id)),
            started_at=saved.get("started_at"),
            last_heartbeat_at=saved.get("last_heartbeat_at"),
            last_event_at=saved.get("last_event_at"),
            last_message_at=saved.get("last_message_at"),
            last_reply_at=saved.get("last_reply_at"),
            last_error=saved.get("last_error"),
        )
        self.event_store.write_status(status)
        return status

    def _publish(self, config: BotConfig, event_type: str, summary: str, *, level: str = "info", metadata: dict[str, Any] | None = None) -> None:
        event = BotEvent(bot_id=config.id, platform=config.platform, type=event_type, level=level, summary=summary, metadata=metadata or {})
        self.event_store.publish(event)
        status = self._status(config)
        status.last_event_at = event.timestamp
        if level == "error":
            status.last_error = summary
            status.bot_state = "error"
        self.event_store.write_status(status)

    def _paths(self, config: BotConfig) -> dict[str, str]:
        root = ensure_bot_dirs(self.workspace, config.platform, config.id)
        return {
            "bot_root": str(root),
            "events": str(root / "events.jsonl"),
            "messages": str(root / "messages.jsonl"),
            "logs": str(root / "logs"),
            "runs": str(root / "runs"),
            "traces": str(root / "traces"),
            "approvals": str(root / "approvals"),
        }


def _status_text(status: BotStatus) -> str:
    if status.last_error:
        return f"Error: {status.last_error}"
    if status.bot_state == "running_agent":
        return "Working"
    if status.bot_state == "waiting_approval":
        return "Waiting approval"
    if status.process_state == "running":
        return "Idle"
    return "Stopped"
