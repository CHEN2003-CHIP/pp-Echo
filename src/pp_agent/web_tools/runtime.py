from __future__ import annotations

import html
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote_plus

import httpx

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.state import AgentState
from pp_agent.storage.settings import Settings, WebCapabilityConfig
from pp_agent.tools.base import ToolExecutionResult
from pp_agent.tools.policy import PermissionDomain
from pp_agent.tools.registry import ToolRegistry

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
        ]
    ),
    re.IGNORECASE,
)


class SearchProvider(Protocol):
    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        ...


class MockSearchProvider:
    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        return [{"title": f"Mock result for {query}", "url": "https://example.com/", "snippet": "Mock web.search result."}][:limit]


class DuckDuckGoSearchProvider:
    def __init__(self, *, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": "pp-Echo web.search"})
            response.raise_for_status()
        results: list[dict[str, str]] = []
        for block in re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', response.text, flags=re.I | re.S):
            href, title = block
            clean_title = _readable_text(title)
            if clean_title:
                results.append({"title": clean_title, "url": html.unescape(href), "snippet": ""})
            if len(results) >= limit:
                break
        return results


class BingSearchProvider:
    def __init__(self, *, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        url = f"https://cn.bing.com/search?q={quote_plus(query)}&mkt=zh-CN&setlang=zh-Hans&cc=CN"
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 pp-Echo web.search",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            response.raise_for_status()
        results: list[dict[str, str]] = []
        required_terms = _required_query_terms(query)
        for block in re.findall(r'(?is)<li class="b_algo[^"]*".*?</li>', response.text):
            title_match = re.search(r'(?is)<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block)
            if title_match is None:
                continue
            snippet_match = re.search(r"(?is)<p[^>]*>(.*?)</p>", block)
            title = _readable_text(title_match.group(2))
            url = html.unescape(title_match.group(1))
            snippet = _readable_text(snippet_match.group(1)) if snippet_match is not None else ""
            if title and url:
                haystack = f"{title} {snippet} {url}".lower()
                if required_terms and not any(term in haystack for term in required_terms):
                    continue
                results.append({"title": title, "url": url, "snippet": snippet})
            if len(results) >= limit:
                break
        return results


class BaiduSearchProvider:
    def __init__(self, *, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        url = f"https://www.baidu.com/s?wd={quote_plus(query)}"
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 pp-Echo web.search",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            response.raise_for_status()
        response_url = str(response.url)
        if "wappass.baidu.com" in response_url or "captcha" in response_url or "\u767e\u5ea6\u5b89\u5168\u9a8c\u8bc1" in response.text:
            raise RuntimeError("Baidu search returned a security verification page")
        results: list[dict[str, str]] = []
        for block in re.findall(r'(?is)<h3[^>]*class="[^"]*(?:t|c-title)[^"]*"[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?</h3>', response.text):
            href, title = block
            clean_title = _readable_text(title)
            if clean_title:
                results.append({"title": clean_title, "url": html.unescape(href), "snippet": ""})
            if len(results) >= limit:
                break
        if results:
            return results
        for block in re.findall(r'(?is)<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', response.text):
            href, title = block
            clean_title = _readable_text(title)
            if clean_title and len(clean_title) >= 4 and "百度" not in clean_title:
                results.append({"title": clean_title, "url": html.unescape(href), "snippet": ""})
            if len(results) >= limit:
                break
        return results


class ZhipuSearchProvider:
    def __init__(self, *, api_key_env: str, base_url: str, timeout_seconds: int = 10) -> None:
        self.api_key_env = api_key_env
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing Zhipu search API key in environment variable: {self.api_key_env}")
        payload = {
            "request_id": "pp-echo-web-search",
            "tool": "web-search-pro",
            "stream": False,
            "messages": [{"role": "user", "content": query}],
        }
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = client.post(
                self.base_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
        return _zhipu_results(response.json(), limit=limit)


@dataclass
class WebRuntime:
    workspace: Path
    tool_registry: ToolRegistry
    settings: Settings | None = None
    search_provider: SearchProvider | None = None
    _registered_tool_names: list[str] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._register_tools()

    def _register_tools(self) -> None:
        self.tool_registry.register_function_tool(
            name="web.search",
            description=(
                "Search the public web without opening a browser. Use provider=auto for current, latest, news, "
                "or static research questions before browser automation; auto records provider fallback attempts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "provider": {"type": "string", "enum": ["auto", "mock", "baidu", "zhipu", "bing", "duckduckgo", "mcp"]},
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
            name="web.fetch",
            description="Fetch a URL with HTTP GET and readable extraction only. Does not execute JavaScript or use browser state.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {"type": "integer"},
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
        self._registered_tool_names = ["web.search", "web.fetch"]

    def transform_context(self, state: AgentState, messages: list[ChatMessage]) -> list[ChatMessage]:
        latest_user_text = self._latest_user_text(state)
        if not latest_user_text or not _WEB_SEARCH_INTENT_RE.search(latest_user_text):
            return messages
        providers = ", ".join(self._web_config().search_providers)
        directive = ChatMessage(
            role="system",
            content=[
                TextPart(
                    text=(
                        "Static web tools are available for this turn.\n"
                        f"- Use web.search with provider=auto before answering current/latest/news/search questions. "
                        f"Configured provider order: {providers}.\n"
                        "- If web.search fails or returns no results, report the provider attempts and concrete error details instead of only saying the internet is unavailable.\n"
                        "- Use web.fetch only after search returns URLs that need article/page extraction."
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
        provider_names = ["custom"] if self.search_provider is not None else ([provider_name] if provider_name != "auto" else self._web_config().search_providers)
        results: list[dict[str, str]] = []
        attempts: list[dict[str, str]] = []
        for candidate in provider_names:
            try:
                provider = self.search_provider if self.search_provider is not None else self._provider(candidate)
                results = provider.search(query, limit=limit)
                attempts.append({"provider": candidate, "status": "ok" if results else "no_results", "result_count": str(len(results))})
                if results:
                    provider_name = candidate
                    break
            except Exception as exc:
                attempts.append({"provider": candidate, "status": "error", "error": str(exc), "error_type": type(exc).__name__})
                continue
        lines = [f"{item.get('title', '')} - {item.get('url', '')}" for item in results]
        return self._result(
            "\n".join(lines) if lines else "No web.search results.",
            {"query": query, "results": results, "routing": "static_search", "provider": provider_name, "attempts": attempts},
            is_error=not bool(results) and any(item.get("status") == "error" for item in attempts),
        )

    def _execute_fetch(self, workspace: Path, arguments: dict[str, Any]) -> ToolExecutionResult:
        url = str(arguments["url"])
        max_chars = max(1, int(arguments.get("max_chars", 4000)))
        with httpx.Client(timeout=self._web_config().fetch_timeout_seconds, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": "pp-Echo web.fetch"})
            response.raise_for_status()
        text = _readable_text(response.text)[:max_chars]
        return self._result(
            f"web.fetch: {response.url}\n{text}",
            {
                "url": str(response.url),
                "status_code": response.status_code,
                "text": text,
                "executed_javascript": False,
                "routing": "static_fetch",
            },
        )

    @staticmethod
    def _result(content: str, details: dict[str, Any], *, is_error: bool = False) -> ToolExecutionResult:
        return ToolExecutionResult(tool_call_id="", tool_name="", content=content, details=details, is_error=is_error)

    def _web_config(self) -> WebCapabilityConfig:
        return self.settings.capabilities.web if self.settings is not None else WebCapabilityConfig()

    def _provider(self, name: str) -> SearchProvider:
        config = self._web_config()
        if name == "mock":
            return MockSearchProvider()
        if name == "baidu":
            return BaiduSearchProvider(timeout_seconds=config.search_timeout_seconds)
        if name == "zhipu":
            return ZhipuSearchProvider(
                api_key_env=config.zhipu_api_key_env,
                base_url=config.zhipu_base_url,
                timeout_seconds=config.search_timeout_seconds,
            )
        if name == "bing":
            return BingSearchProvider(timeout_seconds=config.search_timeout_seconds)
        if name == "duckduckgo":
            return DuckDuckGoSearchProvider(timeout_seconds=config.search_timeout_seconds)
        raise ValueError(f"Unknown web.search provider: {name}")

    @staticmethod
    def _latest_user_text(state: AgentState) -> str:
        for message in reversed(state.messages):
            if message.role != "user":
                continue
            parts = [part.text.strip() for part in message.content if getattr(part, "text", "").strip()]
            if parts:
                return " ".join(parts)
        return ""


def _readable_text(raw: str) -> str:
    value = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", raw)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _required_query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_+-]{1,}", query):
        lowered = token.lower()
        if lowered not in {"today", "latest", "news", "hot", "current", "what", "when", "where"}:
            terms.append(lowered)
    return terms[:3]


def _zhipu_results(payload: dict[str, Any], *, limit: int) -> list[dict[str, str]]:
    candidates: list[Any] = []
    for key in ("search_result", "search_results", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            candidates.extend(value)
    for choice in payload.get("choices", []) if isinstance(payload.get("choices"), list) else []:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
        for call in tool_calls:
            if isinstance(call, dict) and isinstance(call.get("search_result"), list):
                candidates.extend(call["search_result"])
    results: list[dict[str, str]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        url = str(item.get("url") or item.get("link") or "").strip()
        snippet = str(item.get("content") or item.get("snippet") or "").strip()
        if title or url:
            results.append({"title": title or url, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results
