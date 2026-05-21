from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from pp_agent.app.extensions_runtime import load_executable_extensions
from pp_agent.browser.controller import BrowserSnapshot, FakeBrowserController, LocalCDPBrowserController
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
                    {"id": "call-1", "name": "browser.navigate", "arguments_chunk": '{"url":"https://example.com"}'},
                    {"id": "call-2", "name": "browser.read_state", "arguments_chunk": "{}"},
                ],
                "finish_reason": "tool_calls",
                "raw": {},
            }
        else:
            yield {"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class FailingBrowserLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {
            "text": "",
            "tool_calls": [{"id": "call-1", "name": "browser.read_state", "arguments_chunk": "{}"}],
            "finish_reason": "tool_calls",
            "raw": {},
        }


class FailingBrowserController(FakeBrowserController):
    def read_state(self) -> BrowserSnapshot:
        raise RuntimeError("browser unavailable")


def test_browser_tools_register_and_run_directly_in_isolated_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "config.json").write_text(
        json.dumps({"capabilities": {"browser": {"enable": True}}}),
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)
    tool_registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    runtime_hooks = RuntimeHooks()
    controller = FakeBrowserController()

    loaded = load_executable_extensions(
        tmp_path,
        settings=settings,
        tool_registry=tool_registry,
        runtime_hooks=runtime_hooks,
        browser_controller_factory=lambda _workspace, _config: controller,
    )

    assert loaded.browser_runtime is not None
    assert tool_registry.get_spec("browser.navigate").requires_confirmation is False
    assert tool_registry.metadata()["browser.navigate"].tool_family == "browser"
    assert tool_registry.metadata()["browser.navigate"].exact_effect_mode == "none"
    assert tool_registry.metadata()["browser.read_state"].requests_network_hint is False

    navigate = tool_registry.execute("browser.navigate", {"url": "https://example.com"})
    assert controller.url == "https://example.com"
    assert "Navigated:" in navigate.content
    assert navigate.details["title"] == "Page: https://example.com"

    type_call = tool_registry.execute("browser.type", {"selector": "#query", "text": "hello"})
    assert controller.types[-1] == ("#query", "hello", False)
    assert "Typed:" in type_call.content

    click_call = tool_registry.execute("browser.click", {"selector": "#submit"})
    assert controller.clicks[-1] == "#submit"
    assert "Clicked:" in click_call.content

    screenshot_call = tool_registry.execute("browser.screenshot", {"filename": "shot.png"})
    assert controller.screenshots[-1] == "shot.png"
    assert "Captured screenshot" in screenshot_call.content
    assert screenshot_call.details["path"].endswith("shot.png")
    assert screenshot_call.details["bytes"] == 1

    state_call = tool_registry.execute("browser.read_state", {})
    assert "Browser state:" in state_call.content
    assert state_call.details["body_text"] == controller.body_text
    assert PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list() == []


def _browser_agent(tmp_path: Path, monkeypatch, llm_client, controller) -> AgentRuntime:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "user-home"))
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "config.json").write_text(
        json.dumps({"capabilities": {"browser": {"enable": True}}}),
        encoding="utf-8",
    )
    settings = Settings.load(tmp_path)
    registry = ToolRegistry(tmp_path, policy=settings.tool_policy)
    runtime_hooks = RuntimeHooks()
    load_executable_extensions(
        tmp_path,
        settings=settings,
        tool_registry=registry,
        runtime_hooks=runtime_hooks,
        browser_controller_factory=lambda _workspace, _config: controller,
    )
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentRuntime(
        llm_client=llm_client,
        tool_registry=registry,
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        require_plan_approval=True,
        runtime_hooks=runtime_hooks,
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
    assert [event.tool_name for event in events if event.type == "tool_end"] == ["browser.navigate", "browser.read_state"]
    assert controller.url == "https://example.com"
    assert PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list() == []


def test_browser_failure_surfaces_tool_error_without_pending_approval(tmp_path: Path, monkeypatch) -> None:
    agent = _browser_agent(tmp_path, monkeypatch, FailingBrowserLLMClient(), FailingBrowserController())

    events = agent.prompt("inspect browser")

    assert agent.state.pending_plan_token is None
    assert any(event.type == "tool_error" and event.tool_name == "browser.read_state" for event in events)
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
