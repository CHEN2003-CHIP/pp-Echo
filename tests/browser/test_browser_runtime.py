from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from pp_agent.app.extensions_runtime import load_executable_extensions
from pp_agent.browser.controller import FakeBrowserController, LocalCDPBrowserController
from pp_agent.llm.models import ModelConfig
from pp_agent.runtime.hooks import RuntimeHooks
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.sessions import SessionStore
from pp_agent.storage.settings import Settings
from pp_agent.tools.registry import ToolRegistry


class BrowserOnlyLLMClient:
    def __init__(self) -> None:
        self.calls = 0
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        self.calls += 1
        if self.calls == 1:
            yield {
                "text": "",
                "tool_calls": [
                    {"id": "call-1", "name": "browser", "arguments_chunk": '{"action":"navigate","url":"https://example.com"}'},
                    {"id": "call-2", "name": "browser", "arguments_chunk": '{"action":"snapshot"}'},
                ],
                "finish_reason": "tool_calls",
                "raw": {},
            }
        else:
            yield {"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def _settings(tmp_path: Path, monkeypatch, browser_config: dict[str, Any] | None = None) -> Settings:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    config = {"capabilities": {"browser": {"enable": True, **(browser_config or {})}}}
    (project_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return Settings.load(tmp_path)


def _registry(tmp_path: Path, settings: Settings, controller: FakeBrowserController):
    tool_registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    runtime_hooks = RuntimeHooks()
    loaded = load_executable_extensions(
        tmp_path,
        settings=settings,
        tool_registry=tool_registry,
        runtime_hooks=runtime_hooks,
        browser_controller_factory=lambda _workspace, _config: controller,
    )
    return tool_registry, loaded


def test_browser_tool_schema_actions(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    registry, loaded = _registry(tmp_path, settings, FakeBrowserController())

    assert loaded.browser_runtime is not None
    assert "browser.navigate" not in registry.openapi_specs()[0]["function"]["name"]
    spec = registry.get_spec("browser")
    assert spec.requires_confirmation is False
    assert registry.metadata()["browser"].tool_family == "browser"
    assert spec.parameters["properties"]["action"]["enum"] == [
        "doctor",
        "status",
        "start",
        "stop",
        "profiles",
        "tabs.open",
        "tabs.list",
        "tabs.focus",
        "tabs.close",
        "snapshot",
        "screenshot",
        "navigate",
        "act",
    ]


def test_snapshot_generates_refs(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    registry, _loaded = _registry(tmp_path, settings, FakeBrowserController())

    result = registry.execute("browser", {"action": "snapshot"})

    refs = [node["ref"] for node in result.details["snapshot"]["nodes"]]
    assert refs == ["e1", "e2"]
    assert "selector" not in result.content
    assert result.details["untrusted_web_content"] is True


def test_act_uses_ref_not_raw_selector(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    controller = FakeBrowserController()
    registry, _loaded = _registry(tmp_path, settings, controller)

    registry.execute("browser", {"action": "snapshot"})
    rejected = registry.execute("browser", {"action": "act", "request": {"kind": "click", "selector": "#submit"}})
    clicked = registry.execute("browser", {"action": "act", "request": {"kind": "click", "ref": "e1"}})

    assert rejected.is_error is True
    assert "raw selectors are not accepted" in rejected.content
    assert controller.clicks == ["#query"]
    assert clicked.details["requires_resnapshot"] is True


def test_stale_ref_requires_resnapshot(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    controller = FakeBrowserController()
    registry, _loaded = _registry(tmp_path, settings, controller)

    registry.execute("browser", {"action": "snapshot"})
    controller.stale_targets.add("tab-1")
    result = registry.execute("browser", {"action": "act", "request": {"kind": "type", "ref": "e1", "text": "hello"}})

    assert result.details["stale_ref"] is True
    assert result.details["requires_resnapshot"] is True
    assert controller.types == []


def test_navigate_blocks_private_ip(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    registry, _loaded = _registry(tmp_path, settings, FakeBrowserController())

    result = registry.execute("browser", {"action": "navigate", "url": "http://127.0.0.1:8000"})

    assert result.is_error is True
    assert "private/internal" in result.content


def test_read_state_marks_untrusted(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    registry, _loaded = _registry(tmp_path, settings, FakeBrowserController())

    result = registry.execute("browser", {"action": "snapshot"})

    assert "untrusted_web_content" in result.content
    assert result.details["snapshot"]["untrusted_web_content"] is True


def test_click_submit_requires_policy_gate(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    registry, _loaded = _registry(tmp_path, settings, FakeBrowserController())

    registry.execute("browser", {"action": "snapshot"})
    result = registry.execute("browser", {"action": "act", "request": {"kind": "click", "ref": "e2"}})

    assert result.is_error is True
    assert "high-risk action requires" in result.content


def test_profile_user_requires_explicit_enable(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    registry, _loaded = _registry(tmp_path, settings, FakeBrowserController())

    result = registry.execute("browser", {"action": "status", "profile": "user"})

    assert result.is_error is True
    assert "allow_user_profile" in result.content


def test_browser_error_returns_diagnostics(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)

    class FailingController(FakeBrowserController):
        def snapshot(self, *, target_id=None, options=None):
            raise TimeoutError("timed out waiting for snapshot")

    registry, _loaded = _registry(tmp_path, settings, FailingController())

    result = registry.execute("browser", {"action": "snapshot"})

    assert result.is_error is True
    assert result.details["error_type"] == "TimeoutError"
    assert result.details["action"] == "snapshot"
    assert "diagnostics" in result.details
    assert result.details["diagnostics"]["runtime"]["controller_ready"] is True


def _browser_agent(tmp_path: Path, monkeypatch, llm_client, controller) -> AgentRuntime:
    settings = _settings(tmp_path, monkeypatch)
    registry, _loaded = _registry(tmp_path, settings, controller)
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentRuntime(
        llm_client=llm_client,
        tool_registry=registry,
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        require_plan_approval=True,
        runtime_hooks=RuntimeHooks(),
    )
    agent.restore_session_record(record)
    return agent


def test_browser_only_turn_does_not_pause_for_plan_approval(tmp_path: Path, monkeypatch) -> None:
    controller = FakeBrowserController()
    agent = _browser_agent(tmp_path, monkeypatch, BrowserOnlyLLMClient(), controller)

    events = agent.prompt("use the browser")

    assert agent.state.pending_plan_token is None
    assert agent.state.pending_tool_calls == []
    assert not any(event.type == "planner_gate_pending" for event in events)
    assert [event.tool_name for event in events if event.type == "tool_end"] == ["browser", "browser"]
    assert controller.url == "https://example.com"
    assert PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list() == []


def test_local_controller_creates_page_target_when_list_is_empty(tmp_path: Path, monkeypatch) -> None:
    controller = LocalCDPBrowserController(workspace=tmp_path, connect_timeout_seconds=5)
    controller._browser_ws_url = "ws://127.0.0.1:123/devtools/browser/browser-id"

    class FakeResponse:
        def __init__(self, payload: Any) -> None:
            self.payload = payload

        def json(self) -> Any:
            return self.payload

    class FakeHttpClient:
        list_calls = 0

        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self) -> "FakeHttpClient":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def get(self, url: str) -> FakeResponse:
            if url.endswith("/json/list"):
                FakeHttpClient.list_calls += 1
                if FakeHttpClient.list_calls == 1:
                    return FakeResponse([])
                return FakeResponse(
                    [
                        {
                            "id": "created-page",
                            "type": "page",
                            "url": "about:blank",
                            "webSocketDebuggerUrl": "ws://127.0.0.1:123/devtools/page/created-page",
                        }
                    ]
                )
            return FakeResponse({"webSocketDebuggerUrl": "ws://127.0.0.1:123/devtools/browser/browser-id"})

    class FakeBrowserClient:
        def close(self) -> None:
            return None

    monkeypatch.setattr("pp_agent.browser.controller.httpx.Client", FakeHttpClient)
    monkeypatch.setattr(controller, "_connect_browser_client", lambda _ws_url: FakeBrowserClient())
    monkeypatch.setattr(
        controller,
        "_call",
        lambda _client, method, _params: {"result": {"targetId": "created-page"}} if method == "Target.createTarget" else {},
    )

    assert controller._discover_page_ws_url(123) == "ws://127.0.0.1:123/devtools/page/created-page"


def test_browser_runtime_passes_timeout_config_to_local_controller(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(
        tmp_path,
        monkeypatch,
        {
            "connect_timeout_seconds": 25,
            "navigation_timeout_ms": 8000,
            "cdp_http_timeout_seconds": 4,
            "cdp_response_timeout_seconds": 12,
            "action_timeout_ms": 2200,
            "shutdown_timeout_seconds": 7,
        },
    )
    controller = LocalCDPBrowserController(
        workspace=tmp_path,
        connect_timeout_seconds=settings.capabilities.browser.connect_timeout_seconds,
        navigation_timeout_ms=settings.capabilities.browser.navigation_timeout_ms,
        cdp_http_timeout_seconds=settings.capabilities.browser.cdp_http_timeout_seconds,
        cdp_response_timeout_seconds=settings.capabilities.browser.cdp_response_timeout_seconds,
        action_timeout_ms=settings.capabilities.browser.action_timeout_ms,
        shutdown_timeout_seconds=settings.capabilities.browser.shutdown_timeout_seconds,
    )

    status = controller.status()

    assert status["timeouts"]["connect_timeout_seconds"] == 25
    assert status["timeouts"]["navigation_timeout_ms"] == 8000
    assert status["timeouts"]["cdp_http_timeout_seconds"] == 4
    assert status["timeouts"]["cdp_response_timeout_seconds"] == 12
    assert status["timeouts"]["action_timeout_ms"] == 2200
    assert status["timeouts"]["shutdown_timeout_seconds"] == 7
