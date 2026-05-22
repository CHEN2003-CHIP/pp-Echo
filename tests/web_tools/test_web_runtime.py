from __future__ import annotations

from pathlib import Path
from typing import Any

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.storage.settings import Settings
from pp_agent.web_tools.runtime import WebRuntime
from pp_agent.tools.registry import ToolRegistry


class FakeResponse:
    status_code = 200
    url = "https://example.com/"
    text = "<html><head><script>window.executed=true</script></head><body><h1>Hello</h1><p>Readable</p></body></html>"

    def raise_for_status(self) -> None:
        return None


class FakeHttpClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    def __enter__(self) -> "FakeHttpClient":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def get(self, *_args: Any, **_kwargs: Any) -> FakeResponse:
        return FakeResponse()


def test_web_fetch_does_not_execute_js(tmp_path: Path, monkeypatch) -> None:
    registry = ToolRegistry(tmp_path)
    WebRuntime(tmp_path, registry)
    monkeypatch.setattr("pp_agent.web_tools.runtime.httpx.Client", FakeHttpClient)

    result = registry.execute("web.fetch", {"url": "https://example.com/"})

    assert result.details["executed_javascript"] is False
    assert "Hello" in result.details["text"]
    assert "window.executed" not in result.details["text"]


def test_web_search_fetch_browser_routing(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    WebRuntime(tmp_path, registry)

    search = registry.execute("web.search", {"query": "pp echo", "provider": "mock"})

    assert search.details["routing"] == "static_search"
    assert "Mock result" in search.content
    assert registry.metadata()["web.fetch"].tool_family == "web"
    assert registry.metadata()["web.search"].tool_family == "web"


def test_web_search_auto_falls_back_between_providers(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".pp-agent").mkdir()
    (tmp_path / ".pp-agent" / "config.json").write_text(
        '{"capabilities":{"web":{"search_providers":["baidu","bing","duckduckgo"],"search_timeout_seconds":3}}}',
        encoding="utf-8",
    )
    settings = Settings.load(tmp_path)
    registry = ToolRegistry(tmp_path)
    WebRuntime(tmp_path, registry, settings=settings)

    class FailingBaidu:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        def search(self, query: str, *, limit: int = 5):
            raise TimeoutError("baidu timed out")

    class WorkingDuckDuckGo:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        def search(self, query: str, *, limit: int = 5):
            return [{"title": f"ok {query}", "url": "https://example.com", "snippet": ""}]

    monkeypatch.setattr("pp_agent.web_tools.runtime.BaiduSearchProvider", FailingBaidu)
    monkeypatch.setattr("pp_agent.web_tools.runtime.BingSearchProvider", WorkingDuckDuckGo)

    result = registry.execute("web.search", {"query": "pp echo", "provider": "auto"})

    assert result.is_error is False
    assert result.details["provider"] == "bing"
    assert result.details["attempts"][0]["provider"] == "baidu"
    assert result.details["attempts"][0]["error_type"] == "TimeoutError"


def test_web_runtime_guides_current_news_questions_to_search(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    runtime = WebRuntime(tmp_path, registry)
    state = type(
        "State",
        (),
        {"messages": [ChatMessage(role="user", content=[TextPart(text="\u4eca\u5929 AI \u884c\u4e1a\u6700\u70ed\u95e8\u65b0\u95fb\u662f\u4ec0\u4e48\uff1f")], timestamp=0)]},
    )()

    transformed = runtime.transform_context(
        state,
        [ChatMessage(role="system", content=[TextPart(text="base")], timestamp=0)],
    )

    assert len(transformed) == 2
    assert "Use web.search with provider=auto" in transformed[1].content[0].text
    assert "provider attempts" in transformed[1].content[0].text
