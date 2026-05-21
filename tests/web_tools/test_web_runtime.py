from __future__ import annotations

from pathlib import Path
from typing import Any

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
