from __future__ import annotations

from pathlib import Path
import json

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
    get_bot_status_path,
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


def test_registry_readonly_listing_does_not_create_default_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = BotRegistry(workspace)

    assert registry.list_configs(readonly=True) == []
    assert not get_bot_config_path(workspace, "qq", "qq-main").exists()

    config = registry.ensure_default()

    assert config.id == "qq-main"
    assert get_bot_config_path(workspace, "qq", "qq-main").exists()


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


def test_event_store_after_id_returns_incremental_events(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = BotEventStore(workspace)

    first = store.publish(BotEvent(bot_id="qq-main", platform="qq", type="one", summary="one"))
    second = store.publish(BotEvent(bot_id="qq-main", platform="qq", type="two", summary="two"))

    assert int(second.event_id) > int(first.event_id)
    assert [event["type"] for event in store.list_events("qq", "qq-main", after_id=first.event_id)] == ["two"]
    assert store.list_events("qq", "qq-main", after_id=second.event_id) == []


def test_manager_start_stop_and_public_url(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = BotRuntimeManager(workspace)

    started = manager.start_bot("qq-main")
    detail = manager.set_public_url("qq-main", "https://abc.example/")
    stopped = manager.stop_bot("qq-main")

    assert started["status"]["desired_state"] == "enabled"
    assert started["status"]["process_state"] == "not_managed"
    assert detail["webhook_url"] == "https://abc.example/api/integrations/qqbot/webhook"
    assert stopped["status"]["desired_state"] == "disabled"
    assert stopped["status"]["process_state"] == "not_managed"
    assert any(event["type"] == "tunnel_url_updated" for event in manager.event_store.list_events("qq", "qq-main"))


def test_manager_list_bots_does_not_write_status_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = BotRuntimeManager(workspace)
    status_path = get_bot_status_path(workspace, "qq", "qq-main")
    if status_path.exists():
        status_path.unlink()

    listed = manager.list_bots()

    assert listed[0]["id"] == "qq-main"
    assert not status_path.exists()


def test_manager_rejects_non_https_public_url_except_localhost(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = BotRuntimeManager(workspace)

    manager.set_public_url("qq-main", "http://localhost:8788")
    try:
        manager.set_public_url("qq-main", "http://example.com")
    except ValueError as exc:
        assert "https" in str(exc)
    else:
        raise AssertionError("non-local http public_url should be rejected")


def test_trace_store_writes_json_and_recovers_corrupted_trace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = BotRuntimeManager(workspace)

    path = manager.record_trace("qq-main", {"trace_id": "trace-1", "run_id": "run-1", "conversation_id": "c1", "session_id": "s1", "message_id": "m1"})
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.with_name("bad.json").write_text("{bad", encoding="utf-8")
    traces = manager.event_store.list_traces("qq", "qq-main")

    assert payload["trace_id"] == "trace-1"
    assert payload["events"] == []
    assert any(trace.get("corrupted") for trace in traces)


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
    assert started.json()["status"]["desired_state"] == "enabled"
    assert started.json()["status"]["process_state"] == "not_managed"
    assert public_url.json()["webhook_url"] == "https://bot.example/api/integrations/qqbot/webhook"
    assert stopped.json()["status"]["desired_state"] == "disabled"


def test_bot_api_health_and_events_cursor(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app = create_app(workspace, manager=WebSessionManager(workspace, runtime_factory=_factory))
    client = TestClient(app)

    first = client.post("/api/bots/qq-main/start").json()["events"][-1]["event_id"]
    client.post("/api/bots/qq-main/stop")
    events = client.get(f"/api/bots/qq-main/events?after_id={first}").json()["events"]
    health = client.get("/api/bots/qq-main/health")

    assert health.status_code == 200
    assert health.json()["effective_status"]["bot_id"] == "qq-main"
    assert [event["type"] for event in events] == ["bot_stopped"]
