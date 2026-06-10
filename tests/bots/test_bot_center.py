from __future__ import annotations

from pathlib import Path

from pp_agent.bots.events import BotEventStore
from pp_agent.bots.manager import BotRuntimeManager
from pp_agent.bots.models import BotEvent, BotSource, NormalizedBotMessage
from pp_agent.bots.paths import (
    get_bot_approvals_dir,
    get_bot_config_path,
    get_bot_events_path,
    get_bot_logs_dir,
    get_bot_messages_path,
    get_bot_root,
    get_bot_runs_dir,
    get_bot_traces_dir,
)
from pp_agent.bots.registry import BotRegistry
from pp_agent.web.server import create_app
from pp_agent.web.session_manager import WebSessionManager

from tests.web.test_session_manager import _factory


def test_bot_paths_are_scoped_to_bot_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    assert get_bot_root(workspace, "qq", "qq-main") == workspace / ".pp-agent" / "bots" / "qq" / "qq-main"
    assert get_bot_config_path(workspace, "qq", "qq-main").name == "config.json"
    assert get_bot_events_path(workspace, "qq", "qq-main").name == "events.jsonl"
    assert get_bot_messages_path(workspace, "qq", "qq-main").name == "messages.jsonl"
    assert get_bot_logs_dir(workspace, "qq", "qq-main").name == "logs"
    assert get_bot_runs_dir(workspace, "qq", "qq-main").name == "runs"
    assert get_bot_traces_dir(workspace, "qq", "qq-main").name == "traces"
    assert get_bot_approvals_dir(workspace, "qq", "qq-main").name == "approvals"


def test_registry_creates_default_and_strips_secrets(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = BotRegistry(workspace)

    config = registry.ensure_default()
    updated = registry.update_config("qq-main", {"ingress": {"public_url": "https://example.test/"}, "adapter": {"app_secret": "nope"}})

    assert config.id == "qq-main"
    assert config.enabled is False
    assert get_bot_config_path(workspace, "qq", "qq-main").exists()
    text = get_bot_config_path(workspace, "qq", "qq-main").read_text(encoding="utf-8")
    assert "app_secret" not in text
    assert updated.ingress["public_url"] == "https://example.test/"


def test_event_store_writes_events_messages_and_status(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = BotEventStore(workspace)
    source = BotSource(bot_id="qq-main", platform="qq", bot_path=".pp-agent/bots/qq/qq-main", conversation_type="group", channel_id="g1", user_id="u1", message_id="m1")

    event = store.publish(BotEvent(bot_id="qq-main", platform="qq", type="message_received", summary="received", metadata={"source": source.model_dump(mode="json")}))
    store.record_message(NormalizedBotMessage(source=source, text="hello", raw={"op": 0}))

    assert get_bot_events_path(workspace, "qq", "qq-main").exists()
    assert store.list_events("qq", "qq-main")[0]["event_id"] == event.event_id
    assert store.list_messages("qq", "qq-main")[0]["text"] == "hello"
    assert store.read_status("qq", "qq-main")["last_message_at"]


def test_manager_start_stop_and_public_url(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = BotRuntimeManager(workspace)

    started = manager.start_bot("qq-main")
    detail = manager.set_public_url("qq-main", "https://abc.example/")
    stopped = manager.stop_bot("qq-main")

    assert started["status"]["process_state"] == "running"
    assert detail["webhook_url"] == "https://abc.example/api/integrations/qqbot/webhook"
    assert stopped["status"]["process_state"] == "stopped"
    assert any(event["type"] == "tunnel_url_updated" for event in manager.event_store.list_events("qq", "qq-main"))


def test_bot_api_lists_controls_and_sets_url(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app = create_app(workspace, manager=WebSessionManager(workspace, runtime_factory=_factory))
    client = TestClient(app)

    listed = client.get("/api/bots")
    started = client.post("/api/bots/qq-main/start")
    public_url = client.post("/api/bots/qq-main/public-url", json={"public_url": "https://bot.example/"})
    stopped = client.post("/api/bots/qq-main/stop")

    assert listed.status_code == 200
    assert listed.json()["bots"][0]["id"] == "qq-main"
    assert started.json()["status"]["process_state"] == "running"
    assert public_url.json()["webhook_url"] == "https://bot.example/api/integrations/qqbot/webhook"
    assert stopped.json()["status"]["process_state"] == "stopped"
