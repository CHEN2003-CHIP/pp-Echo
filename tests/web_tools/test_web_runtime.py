from __future__ import annotations

from pathlib import Path
from typing import Any

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.storage.settings import Settings
from pp_agent.web_tools.runtime import WebRuntime
from pp_agent.web_tools.providers import _normalize_results
from pp_agent.tools.registry import ToolRegistry


class FakeResponse:
    status_code = 200
    url = "https://example.com/"
    text = "<html><head><script>window.executed=true</script></head><body><h1>Hello</h1><p>Readable</p></body></html>"
    extensions: dict[str, object] = {}

    def raise_for_status(self) -> None:
        return None


class FakeHttpClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    def __enter__(self) -> "FakeHttpClient":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def request(self, *_args: Any, **_kwargs: Any) -> FakeResponse:
        return FakeResponse()


def test_web_fetch_does_not_execute_js(tmp_path: Path, monkeypatch) -> None:
    registry = ToolRegistry(tmp_path)
    WebRuntime(tmp_path, registry)
    monkeypatch.setattr("pp_agent.web_tools.guarded_fetch.httpx.Client", FakeHttpClient)

    result = registry.execute("web.fetch", {"url": "https://example.com/"})

    assert result.details["executed_javascript"] is False
    assert "Hello" in result.details["text"]
    assert "window.executed" not in result.details["text"]


def test_web_fetch_converts_github_readme_blob_to_raw_preview(tmp_path: Path, monkeypatch) -> None:
    seen: list[str] = []

    class LongReadmeResponse:
        status_code = 200
        url = "https://raw.githubusercontent.com/org/repo/main/README.md"
        encoding = "utf-8"
        content = ("# README\n" + "a" * 80).encode("utf-8")
        extensions: dict[str, object] = {}

        def raise_for_status(self) -> None:
            return None

    class CapturingHttpClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        def __enter__(self) -> "CapturingHttpClient":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def request(self, _method: str, url: str, **_kwargs: Any) -> LongReadmeResponse:
            seen.append(url)
            return LongReadmeResponse()

    registry = ToolRegistry(tmp_path)
    WebRuntime(tmp_path, registry)
    monkeypatch.setattr("pp_agent.web_tools.guarded_fetch.httpx.Client", CapturingHttpClient)

    result = registry.execute("web.fetch", {"url": "https://github.com/org/repo/blob/main/README.md", "max_chars": 20})

    assert seen == ["https://raw.githubusercontent.com/org/repo/main/README.md"]
    assert result.details["raw_url"] == "https://raw.githubusercontent.com/org/repo/main/README.md"
    assert result.details["truncated"] is True
    assert result.details["text_length"] > 20
    assert "# README" in result.details["text"]


def test_web_fetch_extracts_page_images_from_html(tmp_path: Path, monkeypatch) -> None:
    class ImagePageResponse:
        status_code = 200
        url = "https://news.example.com/article"
        encoding = "utf-8"
        content = b"""
        <html>
          <head>
            <meta property="og:image" content="/hero.jpg">
            <meta name="twitter:image" content="https://cdn.example.com/twitter.jpg">
          </head>
          <body><img src="/inline.jpg" alt="Inline"><p>Readable</p></body>
        </html>
        """
        extensions: dict[str, object] = {}

        def raise_for_status(self) -> None:
            return None

    class ImageHttpClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        def __enter__(self) -> "ImageHttpClient":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def request(self, *_args: Any, **_kwargs: Any) -> ImagePageResponse:
            return ImagePageResponse()

    registry = ToolRegistry(tmp_path)
    WebRuntime(tmp_path, registry)
    monkeypatch.setattr("pp_agent.web_tools.guarded_fetch.httpx.Client", ImageHttpClient)

    result = registry.execute("web.fetch", {"url": "https://news.example.com/article"})

    assert result.details["images"][0]["url"] == "https://news.example.com/hero.jpg"
    assert {"url": "https://cdn.example.com/twitter.jpg", "title": "page image"} in result.details["images"]
    assert any(item["url"] == "https://news.example.com/inline.jpg" for item in result.details["images"])
    assert "Readable" in result.details["text"]


def test_normalize_results_preserves_image_url_candidates() -> None:
    results = _normalize_results(
        [
            {"title": "A", "url": "https://example.com/a", "thumbnail": "https://example.com/a.png"},
            {"title": "B", "url": "https://example.com/b", "pagemap": {"cse_thumbnail": [{"src": "https://example.com/b.png"}]}},
        ],
        limit=5,
    )

    assert results[0]["image_url"] == "https://example.com/a.png"
    assert results[1]["image_url"] == "https://example.com/b.png"


def test_web_search_fetch_browser_routing(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    WebRuntime(tmp_path, registry)

    search = registry.execute("web.search", {"query": "pp echo", "provider": "mock"})

    assert search.details["routing"] == "provider_first"
    assert "Mock result" in search.content
    assert registry.metadata()["web.fetch"].tool_family == "web"
    assert registry.metadata()["web.search"].tool_family == "web"


def test_web_search_auto_falls_back_between_providers(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".pp-agent").mkdir()
    (tmp_path / ".pp-agent" / "config.json").write_text(
        '{"capabilities":{"web":{"primary_providers":[],"search_providers":["baidu","bing","duckduckgo"],"search_timeout_seconds":3}}}',
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

    monkeypatch.setattr("pp_agent.web_tools.runtime_impl.BaiduSearchProvider", FailingBaidu)
    monkeypatch.setattr("pp_agent.web_tools.runtime_impl.BingSearchProvider", WorkingDuckDuckGo)

    result = registry.execute("web.search", {"query": "pp echo", "provider": "auto"})

    assert result.is_error is False
    assert result.details["provider"] == "bing"
    assert result.details["attempts"][0]["provider"] == "baidu"
    assert result.details["attempts"][0]["error_type"] == "TimeoutError"


def test_web_search_cache_avoids_repeated_provider_calls(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    calls: list[str] = []

    class CountingProvider:
        name = "custom"

        def search(self, query: str, *, limit: int = 5):
            calls.append(query)
            return [{"title": "cached", "url": "https://example.com", "snippet": ""}]

    WebRuntime(tmp_path, registry, search_provider=CountingProvider())

    first = registry.execute("web.search", {"query": "pp echo", "limit": 1})
    second = registry.execute("web.search", {"query": "pp echo", "limit": 1})

    assert "cached" not in first.details
    assert second.details["cached"] is True
    assert calls == ["pp echo"]


def test_web_github_trending_uses_github_api_shape(tmp_path: Path, monkeypatch) -> None:
    registry = ToolRegistry(tmp_path)
    WebRuntime(tmp_path, registry)

    def fake_search(self, query: str, *, limit: int = 5):
        return [
            {"title": "org/repo", "url": "https://github.com/org/repo", "snippet": "Repo", "stars": "1234", "language": "Python", "updated_at": "2026-05-23T00:00:00Z"}
        ]

    monkeypatch.setattr("pp_agent.web_tools.providers.GitHubSearchClient.search_repositories", fake_search)

    result = registry.execute("web.github_trending", {"topic": "ai", "language": "Python", "since": "weekly", "limit": 1})

    assert result.is_error is False
    assert result.details["provider"] == "github"
    assert result.details["results"][0]["stars"] == "1234"
    assert result.details["freshness"] == "approximate_trending"


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
    assert "Use web.search or web.news with provider=auto" in transformed[1].content[0].text
    assert "provider attempts" in transformed[1].content[0].text
