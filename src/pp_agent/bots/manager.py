from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4
from urllib.parse import urlparse

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
        self._inflight_tasks: dict[str, set[asyncio.Task]] = {}
        self.registry.ensure_default()

    def list_bots(self) -> list[dict[str, Any]]:
        return [self._summary(config, persist_status=False) for config in self.registry.list_configs()]

    def get_bot(self, bot_id: str) -> dict[str, Any]:
        return self._summary(self.registry.get_config(bot_id), persist_status=False)

    def get_detail(self, bot_id: str) -> dict[str, Any]:
        config = self.registry.get_config(bot_id)
        status = self._status(config)
        return {
            "config": config.model_dump(mode="json", exclude_none=True),
            "status": status.model_dump(mode="json", exclude_none=True),
            "effective_status": self.effective_status(bot_id),
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
        status = self._status(config, process_state="not_managed", bot_state="idle")
        status.started_at = status.started_at or utc_now()
        status.last_heartbeat_at = utc_now()
        self.event_store.write_status(status)
        self._publish(config, "bot_started", "Bot started by Web control plane.")
        return self.get_detail(bot_id)

    def stop_bot(self, bot_id: str, *, force: bool = False) -> dict[str, Any]:
        config = self.registry.disable(bot_id)
        if force:
            for task in list(self._inflight_tasks.get(bot_id, set())):
                task.cancel()
            self._publish(config, "run_cancelled", "Force stop requested; in-flight Bot tasks were cancelled.", metadata={"force": True})
        status = self._status(config, process_state="not_managed", bot_state="idle")
        self.event_store.write_status(status)
        self._publish(config, "bot_stopped", "Bot stopped by Web control plane.", metadata={"force": force, "still_running_count": len(self._inflight_tasks.get(bot_id, set()))})
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

    def effective_status(self, bot_id: str) -> dict[str, Any]:
        config = self.registry.get_config(bot_id)
        return self._status(config).model_dump(mode="json", exclude_none=True)

    def update_config(self, bot_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        config = self.registry.update_config(bot_id, patch)
        self.event_store.write_status(self._status(config))
        self._publish(config, "bot_health_changed", "Bot configuration updated.")
        return self.get_detail(bot_id)

    def set_public_url(self, bot_id: str, public_url: str) -> dict[str, Any]:
        public_url = str(public_url or "").strip().rstrip("/")
        _validate_public_url(public_url)
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
        payload = _normalize_trace(config.id, config.platform, trace_id, trace_info)
        return self.event_store.write_trace(config.platform, config.id, trace_id, payload)

    def register_task(self, bot_id: str, task: asyncio.Task) -> None:
        tasks = self._inflight_tasks.setdefault(bot_id, set())
        tasks.add(task)

        def cleanup(done: asyncio.Task) -> None:
            tasks.discard(done)

        task.add_done_callback(cleanup)

    def _summary(self, config: BotConfig, *, persist_status: bool = True) -> dict[str, Any]:
        status = self._status(config, persist=persist_status)
        return {
            "id": config.id,
            "type": config.type,
            "platform": config.platform,
            "name": config.name,
            "enabled": config.enabled,
            "description": config.description,
            "desired_state": status.desired_state,
            "process_state": status.process_state,
            "agent_state": status.agent_state,
            "bot_state": status.bot_state,
            "ingress_state": status.ingress_state,
            "qq_state": status.qq_state,
            "configured": status.configured,
            "last_event_at": status.last_event_at.isoformat() if status.last_event_at else None,
            "last_message_at": status.last_message_at.isoformat() if status.last_message_at else None,
            "last_error": status.last_error,
            "still_running_count": status.still_running_count,
            "queued_count": status.queued_count,
            "status_text": _status_text(status),
        }

    def _status(
        self,
        config: BotConfig,
        *,
        process_state: str | None = None,
        bot_state: str | None = None,
        persist: bool = True,
    ) -> BotStatus:
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
            desired_state="enabled" if config.enabled else "disabled",
            process_state=process_state or saved.get("process_state") or "not_managed",
            ingress_state=_ingress_state(public_url, saved.get("ingress_state")),
            qq_state=_qq_state(qq_config, saved.get("qq_state")),
            bot_state=bot_state or saved.get("bot_state") or "idle",
            agent_state=saved.get("agent_state") or bot_state or saved.get("bot_state") or "idle",
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
            last_run_at=saved.get("last_run_at"),
            warnings=list(saved.get("warnings") or []),
            still_running_count=len(self._inflight_tasks.get(config.id, set())),
            queued_count=int(saved.get("queued_count") or 0),
            effective_policy=_effective_policy(config),
        )
        if persist:
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
    return "Enabled" if status.desired_state == "enabled" else "Disabled"


def _normalize_trace(bot_id: str, channel: str, trace_id: str, trace_info: dict[str, Any]) -> dict[str, Any]:
    started_at = trace_info.get("started_at") or utc_now().isoformat()
    return {
        "trace_id": trace_id,
        "run_id": trace_info.get("run_id") or f"run_{uuid4().hex}",
        "bot_id": trace_info.get("bot_id") or bot_id,
        "channel": trace_info.get("channel") or channel,
        "conversation_id": trace_info.get("conversation_id"),
        "session_id": trace_info.get("session_id"),
        "message_id": trace_info.get("message_id"),
        "started_at": started_at,
        "finished_at": trace_info.get("finished_at"),
        "status": trace_info.get("status") or "completed",
        "events": list(trace_info.get("events") or []),
        "tool_calls": list(trace_info.get("tool_calls") or []),
        "approval": trace_info.get("approval"),
        "error": trace_info.get("error"),
    }


def _validate_public_url(public_url: str) -> None:
    if not public_url:
        return
    parsed = urlparse(public_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("public_url must be a valid http:// or https:// URL")
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("public_url must use https:// except localhost development URLs")


def _ingress_state(public_url: str | None, saved: Any) -> str:
    if not public_url:
        return "local_only"
    if saved in {"public_reachable", "public_unreachable"}:
        return str(saved)
    return "public_configured"


def _qq_state(qq_config: Any, saved: Any) -> str:
    if qq_config is None:
        return "unknown"
    if not qq_config.configured:
        return "not_configured"
    if saved in {"token_ok", "token_error"}:
        return str(saved)
    return "configured"


def _effective_policy(config: BotConfig) -> dict[str, Any]:
    security = config.security or {}
    routing = config.routing or {}
    return {
        "require_approval_for_tools": bool(security.get("require_approval_for_tools", True)),
        "allow_shell": bool(security.get("allow_shell", False)),
        "allowed_workspace_roots": list(security.get("allowed_workspace_roots") or []),
        "allowlists": {
            "user_count": len(security.get("allowed_user_ids") or []),
            "group_count": len(security.get("allowed_group_ids") or []),
        },
        "group_trigger": routing.get("group_trigger") or "/pp",
    }
