from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.state import AgentState
from pp_agent.storage.settings import Settings, WebCapabilityConfig
from pp_agent.tools.base import ToolExecutionResult
from pp_agent.tools.policy import PermissionDomain
from pp_agent.tools.registry import ToolRegistry
from pp_agent.web_tools.guarded_fetch import GuardedHttpClient, WebGuardConfig
from pp_agent.web_tools.providers import (
    BaiduSearchProvider,
    BingSearchProvider,
    BraveSearchProvider,
    DuckDuckGoSearchProvider,
    ExaSearchProvider,
    GitHubSearchClient,
    MockSearchProvider,
    ProviderAttempt,
    SerpAPISearchProvider,
    TavilySearchProvider,
    ZhipuSearchProvider,
    parse_github_since,
)


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        ...


_WEB_SEARCH_INTENT_RE = re.compile(
    "|".join(
        [
            "latest",
            "current",
            "today",
            "news",
            "breaking",
            "hot",
            "trending",
            "search",
            "web",
            "\\u4eca\\u5929",
            "\\u4eca\\u65e5",
            "\\u6700\\u65b0",
            "\\u65b0\\u95fb",
            "\\u70ed\\u95e8",
            "\\u70ed\\u70b9",
            "\\u641c\\u7d22",
            "\\u67e5\\u4e00\\u4e0b",
            "github",
            "repo",
            "repository",
        ]
    ),
    re.IGNORECASE,
)


@dataclass
class WebRuntime:
    workspace: Path
    tool_registry: ToolRegistry
    settings: Settings | None = None
    search_provider: SearchProvider | None = None
    _registered_tool_names: list[str] = field(default_factory=list, init=False, repr=False)
    _cache: dict[str, tuple[float, dict[str, Any]]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._register_tools()

    def _register_tools(self) -> None:
        self.tool_registry.register_function_tool(
            name="web.search",
            description=(
                "Search the public web with provider-first routing. Use provider=auto for current/latest/news/search "
                "questions before browser automation; auto records provider fallback attempts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "provider": {"type": "string", "enum": ["auto", "mock", "brave", "tavily", "serpapi", "exa", "baidu", "zhipu", "bing", "duckduckgo", "mcp"]},
                },
                "required": ["query"],
            },
            executor=self._execute_search,
            category="web",
            permission_domain=PermissionDomain.READ,
            tool_family="web",
            exact_effect_mode="none",
            non_side_effectful=True,
            known_safe_inspect=False,
            requests_network_hint=True,
            touches_external_hint=False,
            replace=True,
        )
        self.tool_registry.register_function_tool(
            name="web.news",
            description="Search recent AI/news style web content with freshness bias and provider fallback diagnostics.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "region": {"type": "string"},
                    "language": {"type": "string"},
                    "freshness_hours": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            executor=self._execute_news,
            category="web",
            permission_domain=PermissionDomain.READ,
            tool_family="web",
            exact_effect_mode="none",
            non_side_effectful=True,
            known_safe_inspect=False,
            requests_network_hint=True,
            touches_external_hint=False,
            replace=True,
        )
        self.tool_registry.register_function_tool(
            name="web.github_trending",
            description="Approximate GitHub trending repositories using GitHub search API rather than HTML trending pages.",
            parameters={
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "language": {"type": "string"},
                    "since": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
            executor=self._execute_github_trending,
            category="web",
            permission_domain=PermissionDomain.READ,
            tool_family="web",
            exact_effect_mode="none",
            non_side_effectful=True,
            known_safe_inspect=False,
            requests_network_hint=True,
            touches_external_hint=False,
            replace=True,
        )
        self.tool_registry.register_function_tool(
            name="web.fetch",
            description="Fetch a URL with HTTP GET and readable extraction only. Does not execute JavaScript or use browser state.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {"type": "integer"},
                    "timeout_seconds": {"type": "integer"},
                    "include_decorative_images": {"type": "boolean"},
                },
                "required": ["url"],
            },
            executor=self._execute_fetch,
            category="web",
            permission_domain=PermissionDomain.READ,
            tool_family="web",
            exact_effect_mode="none",
            non_side_effectful=True,
            known_safe_inspect=False,
            requests_network_hint=True,
            touches_external_hint=False,
            replace=True,
        )
        self._registered_tool_names = ["web.search", "web.news", "web.github_trending", "web.fetch"]

    def transform_context(self, state: AgentState, messages: list[ChatMessage]) -> list[ChatMessage]:
        latest_user_text = self._latest_user_text(state)
        if not latest_user_text or not _WEB_SEARCH_INTENT_RE.search(latest_user_text):
            return messages
        providers = ", ".join(self._search_provider_names())
        directive = ChatMessage(
            role="system",
            content=[
                TextPart(
                    text=(
                        "Static web tools are available for this turn.\n"
                        f"- Use web.search or web.news with provider=auto before answering current/latest/news/search questions. "
                        f"Configured provider order: {providers}.\n"
                        "- If web.search fails or returns no results, report the provider attempts and concrete error details instead of only saying the internet is unavailable.\n"
                        "- Use web.fetch only after search returns URLs that need article/page extraction.\n"
                        "- Use web.github_trending for GitHub project popularity questions instead of scraping the trending HTML page."
                    )
                )
            ],
            timestamp=time.time(),
        )
        return [messages[0], directive, *messages[1:]] if messages else [directive]

    def _execute_search(self, workspace: Path, arguments: dict[str, Any]) -> ToolExecutionResult:
        query = str(arguments["query"])
        limit = max(1, min(10, int(arguments.get("limit", 5))))
        provider_name = str(arguments.get("provider") or "auto").lower()
        if provider_name == "mcp":
            return self._result("web.search provider 'mcp' is reserved.", {"reserved": True}, is_error=True)
        cache_key = self._cache_key("search", query=query, limit=limit, provider=provider_name)
        cached = self._cache_get(cache_key)
        if cached is not None:
            cached["details"]["cached"] = True
            return self._result(cached["content"], cached["details"], is_error=bool(cached.get("is_error", False)))
        results, attempts, actual_provider = self._search(query, limit=limit, provider_name=provider_name)
        lines = [f"{item.get('title', '')} - {item.get('url', '')}" for item in results]
        payload = {
            "query": query,
            "results": results,
            "routing": "provider_first",
            "provider": actual_provider,
            "attempts": [attempt.__dict__ for attempt in attempts],
            "result_count": len(results),
            "freshness": "static",
            "confidence": self._confidence_for(provider=actual_provider, result_count=len(results), attempts=attempts),
        }
        content = "\n".join(lines) if lines else "No web.search results."
        is_error = not bool(results) and any(attempt.status == "error" for attempt in attempts)
        result = self._result(content, payload, is_error=is_error)
        self._cache_set(cache_key, result)
        return result

    def _execute_news(self, workspace: Path, arguments: dict[str, Any]) -> ToolExecutionResult:
        query = str(arguments["query"])
        region = str(arguments.get("region") or "").strip()
        language = str(arguments.get("language") or "").strip()
        freshness_hours = max(1, int(arguments.get("freshness_hours") or self._web_config().news_freshness_hours))
        limit = max(1, min(10, int(arguments.get("limit", 5))))
        cache_key = self._cache_key("news", query=query, limit=limit, region=region, language=language, freshness_hours=freshness_hours)
        cached = self._cache_get(cache_key)
        if cached is not None:
            cached["details"]["cached"] = True
            return self._result(cached["content"], cached["details"], is_error=bool(cached.get("is_error", False)))
        enriched_query = f"{query} news latest"
        if region:
            enriched_query += f" region:{region}"
        if language:
            enriched_query += f" language:{language}"
        results, attempts, actual_provider = self._search(enriched_query, limit=limit, provider_name="auto")
        payload = {
            "query": query,
            "region": region or None,
            "language": language or None,
            "freshness_hours": freshness_hours,
            "results": results,
            "routing": "provider_first",
            "provider": actual_provider,
            "attempts": [attempt.__dict__ for attempt in attempts],
            "result_count": len(results),
            "freshness": f"last_{freshness_hours}_hours",
            "confidence": self._confidence_for(provider=actual_provider, result_count=len(results), attempts=attempts, freshness_hours=freshness_hours),
        }
        content = "\n".join(f"{item.get('title', '')} - {item.get('url', '')}" for item in results) if results else "No web.news results."
        is_error = not bool(results) and any(attempt.status == "error" for attempt in attempts)
        result = self._result(content, payload, is_error=is_error)
        self._cache_set(cache_key, result)
        return result

    def _execute_github_trending(self, workspace: Path, arguments: dict[str, Any]) -> ToolExecutionResult:
        topic = str(arguments.get("topic") or "").strip()
        language = str(arguments.get("language") or "").strip()
        since = parse_github_since(str(arguments.get("since") or "").strip() or "weekly")
        limit = max(1, min(10, int(arguments.get("limit", 5))))
        cache_key = self._cache_key("github_trending", topic=topic, language=language, since=since or "", limit=limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            cached["details"]["cached"] = True
            return self._result(cached["content"], cached["details"], is_error=bool(cached.get("is_error", False)))
        client = GitHubSearchClient(
            token_env=self._web_config().github_token_env,
            timeout_seconds=self._web_config().search_timeout_seconds,
        )
        query_terms = ["is:public"]
        if topic:
            query_terms.append(f"topic:{topic}")
        if language:
            query_terms.append(f"language:{language}")
        if since:
            query_terms.append(f"pushed:>={since}")
        query = " ".join(query_terms)
        attempts = [ProviderAttempt(provider="github", status="ok")]
        try:
            results = client.search_repositories(query, limit=limit)
        except Exception as exc:
            attempts = [ProviderAttempt(provider="github", status="error", error=str(exc), error_type=type(exc).__name__)]
            results = []
        payload = {
            "query": query,
            "topic": topic or None,
            "language": language or None,
            "since": since,
            "results": results,
            "routing": "github_search_api",
            "provider": "github",
            "attempts": [attempt.__dict__ for attempt in attempts],
            "result_count": len(results),
            "freshness": "approximate_trending",
            "confidence": "high" if results else "low",
        }
        content = "\n".join(f"{item.get('title', '')} - {item.get('url', '')}" for item in results) if results else "No web.github_trending results."
        result = self._result(content, payload, is_error=not bool(results))
        self._cache_set(cache_key, result)
        return result

    def _execute_fetch(self, workspace: Path, arguments: dict[str, Any]) -> ToolExecutionResult:
        source_url = str(arguments["url"])
        url = _github_raw_readme_url(source_url) or source_url
        max_chars = max(1, int(arguments.get("max_chars", 4000)))
        offset = max(0, int(arguments.get("offset", 0)))
        timeout_seconds = self._fetch_timeout(arguments.get("timeout_seconds"))
        include_decorative_images = bool(arguments.get("include_decorative_images", False))
        client = GuardedHttpClient(self._guard_config(timeout_seconds=timeout_seconds))
        try:
            response = client.get(url, headers={"User-Agent": "pp-Echo web.fetch"})
            decoded, encoding = _decode_response_text(response)
            response_url = str(response.url)
            plain_text = _looks_like_plain_text_url(response_url)
            images = [] if plain_text else _extract_page_images(
                decoded,
                base_url=response_url,
                include_decorative=include_decorative_images,
            )
            raw_text = decoded if plain_text else _readable_text(decoded)
            text, truncated = _slice_text_preview(raw_text, offset=offset, max_chars=max_chars)
            details = {
                "url": response_url,
                "source_url": source_url,
                "raw_url": url if url != source_url else None,
                "status_code": response.status_code,
                "text": text,
                "images": images,
                "text_length": len(raw_text),
                "truncated": truncated,
                "offset": offset,
                "max_chars": max_chars,
                "timeout_seconds": timeout_seconds,
                "encoding": encoding,
                "executed_javascript": False,
                "routing": "guarded_static_fetch",
                "redirects": list(response.extensions.get("pp_echo_redirects", [])),
            }
            return self._result(f"web.fetch: {response.url}\n{text}", details)
        except Exception as exc:
            return self._result(
                f"web.fetch error: {exc}",
                {
                    "url": url,
                    "source_url": source_url,
                    "raw_url": url if url != source_url else None,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "timeout_seconds": timeout_seconds,
                    "executed_javascript": False,
                    "routing": "guarded_static_fetch",
                },
                is_error=True,
            )

    def _search(self, query: str, *, limit: int, provider_name: str) -> tuple[list[dict[str, str]], list[ProviderAttempt], str]:
        if self.search_provider is not None:
            try:
                results = self.search_provider.search(query, limit=limit)
                return results, [ProviderAttempt(provider="custom", status="ok", result_count=len(results))], "custom"
            except Exception as exc:
                return [], [ProviderAttempt(provider="custom", status="error", error=str(exc), error_type=type(exc).__name__)], "custom"

        candidate_names = [provider_name] if provider_name != "auto" else self._search_provider_names()
        attempts: list[ProviderAttempt] = []
        results: list[dict[str, str]] = []
        actual_provider = candidate_names[0] if candidate_names else "unknown"
        for candidate in candidate_names:
            provider = self._provider(candidate)
            try:
                results = provider.search(query, limit=limit)
                attempts.append(ProviderAttempt(provider=candidate, status="ok" if results else "no_results", result_count=len(results)))
                actual_provider = candidate
                if results:
                    break
            except Exception as exc:
                attempts.append(ProviderAttempt(provider=candidate, status="error", error=str(exc), error_type=type(exc).__name__))
                continue
        return results, attempts, actual_provider

    def _provider(self, name: str) -> SearchProvider:
        config = self._web_config()
        if name == "mock":
            return MockSearchProvider()
        if name == "brave":
            return BraveSearchProvider(api_key_env=config.provider_keys_env.get("brave", "BRAVE_SEARCH_API_KEY"), timeout_seconds=config.search_timeout_seconds)
        if name == "tavily":
            return TavilySearchProvider(api_key_env=config.provider_keys_env.get("tavily", "TAVILY_API_KEY"), timeout_seconds=config.search_timeout_seconds)
        if name == "serpapi":
            return SerpAPISearchProvider(api_key_env=config.provider_keys_env.get("serpapi", "SERPAPI_API_KEY"), timeout_seconds=config.search_timeout_seconds)
        if name == "exa":
            return ExaSearchProvider(api_key_env=config.provider_keys_env.get("exa", "EXA_API_KEY"), timeout_seconds=config.search_timeout_seconds)
        if name == "baidu":
            return BaiduSearchProvider(timeout_seconds=config.search_timeout_seconds)
        if name == "zhipu":
            return ZhipuSearchProvider(api_key_env=config.zhipu_api_key_env, base_url=config.zhipu_base_url, timeout_seconds=config.search_timeout_seconds)
        if name == "bing":
            return BingSearchProvider(timeout_seconds=config.search_timeout_seconds)
        if name == "duckduckgo":
            return DuckDuckGoSearchProvider(timeout_seconds=config.search_timeout_seconds)
        raise ValueError(f"Unknown web.search provider: {name}")

    def _search_provider_names(self) -> list[str]:
        config = self._web_config()
        ordered: list[str] = []
        for name in [*config.primary_providers, *config.search_providers]:
            lowered = str(name).lower()
            if lowered not in ordered:
                ordered.append(lowered)
        return ordered

    def _web_config(self) -> WebCapabilityConfig:
        return self.settings.capabilities.web if self.settings is not None else WebCapabilityConfig()

    def _fetch_timeout(self, value: Any) -> int:
        configured = self._web_config().fetch_timeout_seconds
        timeout = configured if value is None else int(value)
        return max(1, min(30, timeout))

    def _guard_config(self, *, timeout_seconds: int | None = None) -> WebGuardConfig:
        config = self._web_config()
        return WebGuardConfig(
            timeout_seconds=timeout_seconds or config.fetch_timeout_seconds,
            allow_private_network=config.guard_allow_private_network,
            max_redirects=config.guard_max_redirects,
        )

    def _confidence_for(
        self,
        *,
        provider: str,
        result_count: int,
        attempts: list[ProviderAttempt],
        freshness_hours: int | None = None,
    ) -> str:
        if result_count <= 0:
            return "low"
        if provider in {"brave", "tavily", "serpapi", "exa", "github"}:
            return "high" if freshness_hours is None or freshness_hours <= 72 else "medium"
        if provider in {"bing", "duckduckgo", "baidu", "zhipu"}:
            return "medium"
        if any(attempt.status == "error" for attempt in attempts):
            return "medium"
        return "low"

    def _latest_user_text(self, state: AgentState) -> str:
        for message in reversed(state.messages):
            if message.role != "user":
                continue
            parts = [part.text.strip() for part in message.content if getattr(part, "text", "").strip()]
            if parts:
                return " ".join(parts)
        return ""

    def _cache_key(self, kind: str, **payload: Any) -> str:
        normalized = "|".join(f"{key}={payload[key]!r}" for key in sorted(payload))
        return f"{kind}:{normalized}"

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        item = self._cache.get(key)
        if item is None:
            return None
        expires_at, payload = item
        if expires_at < time.time():
            self._cache.pop(key, None)
            return None
        return payload

    def _cache_set(self, key: str, result: ToolExecutionResult) -> None:
        ttl = self._web_config().cache_ttl_seconds
        self._cache[key] = (
            time.time() + ttl,
            {
                "content": result.content,
                "details": dict(result.details or {}),
                "is_error": bool(result.is_error),
            },
        )

    @staticmethod
    def _result(content: str, details: dict[str, Any], *, is_error: bool = False) -> ToolExecutionResult:
        return ToolExecutionResult(tool_call_id="", tool_name="", content=content, details=details, is_error=is_error)


def _readable_text(raw: str) -> str:
    value = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", raw)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _extract_page_images(raw: str, *, base_url: str, limit: int = 6, include_decorative: bool = False) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(raw_url: str, *, title: str = "") -> None:
        if len(images) >= limit:
            return
        value = html.unescape(raw_url or "").strip()
        if not value:
            return
        absolute = urljoin(base_url, value)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or absolute in seen:
            return
        if not include_decorative and _looks_like_decorative_image(absolute, title):
            return
        seen.add(absolute)
        payload = {"url": absolute}
        if title:
            payload["title"] = html.unescape(title).strip()
        images.append(payload)

    meta_patterns = [
        r'<meta[^>]+(?:property|name)=["\'](?:og:image|og:image:url|twitter:image|twitter:image:src)["\'][^>]+content=["\']([^"\']+)["\'][^>]*>',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|og:image:url|twitter:image|twitter:image:src)["\'][^>]*>',
        r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\'][^>]*>',
        r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']image_src["\'][^>]*>',
    ]
    for pattern in meta_patterns:
        for match in re.finditer(pattern, raw, flags=re.I | re.S):
            add(match.group(1), title="page image")

    for match in re.finditer(r'<img\b[^>]+(?:src|data-src)=["\']([^"\']+)["\'][^>]*>', raw, flags=re.I | re.S):
        tag = match.group(0)
        alt_match = re.search(r'\balt=["\']([^"\']*)["\']', tag, flags=re.I | re.S)
        add(match.group(1), title=alt_match.group(1) if alt_match else "")
        if len(images) >= limit:
            break
    return images


def _looks_like_decorative_image(url: str, title: str = "") -> bool:
    parsed = urlparse(url)
    haystack = " ".join(
        part.lower()
        for part in [
            parsed.path,
            parsed.query,
            title,
        ]
        if part
    )
    decorative_words = (
        "logo",
        "favicon",
        "icon",
        "sprite",
        "placeholder",
        "blank",
        "loading",
        "avatar",
        "qrcode",
        "qr-code",
        "wechat",
        "weixin",
        "广告",
        "二维码",
        "图标",
    )
    if any(word in haystack for word in decorative_words):
        return True
    return bool(re.search(r"(^|[/_.-])(ad|ads|advert|banner|sponsor|promo)([/_.-]|$)", haystack))


def _decode_response_text(response) -> tuple[str, str]:
    encoding = getattr(response, "encoding", None) or "utf-8"
    if not hasattr(response, "content"):
        return str(getattr(response, "text", "")), encoding
    try:
        return response.content.decode(encoding), encoding
    except Exception:
        try:
            return response.content.decode("utf-8-sig"), "utf-8-sig"
        except Exception:
            return response.content.decode("utf-8", errors="replace"), "utf-8-replace"


def _slice_text_preview(text: str, *, offset: int, max_chars: int) -> tuple[str, bool]:
    start = min(max(0, offset), len(text))
    end = min(len(text), start + max_chars)
    preview = text[start:end]
    truncated = start > 0 or end < len(text)
    if truncated:
        remaining = max(0, len(text) - end)
        preview = (
            f"{preview}\n\n"
            f"[Preview truncated. offset={start}, max_chars={max_chars}, remaining_chars={remaining}. "
            "Fetch again with offset/max_chars to continue.]"
        )
    return preview, truncated


def _looks_like_plain_text_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    return (
        parsed.hostname == "raw.githubusercontent.com"
        or path.endswith((".md", ".markdown", ".txt", ".rst"))
        or "/raw/" in path
    )


def _github_raw_readme_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.hostname not in {"github.com", "www.github.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 5 or parts[2] != "blob":
        return None
    filename = parts[-1].lower()
    if not filename.startswith("readme"):
        return None
    owner, repo, branch = parts[0], parts[1], parts[3]
    tail = "/".join(parts[4:])
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{tail}"
