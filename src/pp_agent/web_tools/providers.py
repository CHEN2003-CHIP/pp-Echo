from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import quote_plus

from pp_agent.web_tools.guarded_fetch import GuardedHttpClient, WebGuardConfig


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        ...


@dataclass(frozen=True)
class ProviderAttempt:
    provider: str
    status: str
    result_count: int = 0
    error: str | None = None
    error_type: str | None = None


class MockSearchProvider:
    name = "mock"

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        return [{"title": f"Mock result for {query}", "url": "https://example.com/", "snippet": "Mock web.search result."}][:limit]


class DuckDuckGoSearchProvider:
    name = "duckduckgo"

    def __init__(self, *, timeout_seconds: int = 10) -> None:
        self.client = GuardedHttpClient(WebGuardConfig(timeout_seconds=timeout_seconds))

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        response = self.client.get(f"https://duckduckgo.com/html/?q={quote_plus(query)}", headers={"User-Agent": "pp-Echo web.search"})
        results: list[dict[str, str]] = []
        for href, title in re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', response.text, flags=re.I | re.S):
            clean_title = _readable_text(title)
            if clean_title:
                results.append({"title": clean_title, "url": html.unescape(href), "snippet": ""})
            if len(results) >= limit:
                break
        return results


class BingSearchProvider:
    name = "bing"

    def __init__(self, *, timeout_seconds: int = 10) -> None:
        self.client = GuardedHttpClient(WebGuardConfig(timeout_seconds=timeout_seconds))

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        response = self.client.get(
            f"https://cn.bing.com/search?q={quote_plus(query)}&mkt=zh-CN&setlang=zh-Hans&cc=CN",
            headers={
                "User-Agent": "Mozilla/5.0 pp-Echo web.search",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
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
    name = "baidu"

    def __init__(self, *, timeout_seconds: int = 10) -> None:
        self.client = GuardedHttpClient(WebGuardConfig(timeout_seconds=timeout_seconds))

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        response = self.client.get(
            f"https://www.baidu.com/s?wd={quote_plus(query)}",
            headers={
                "User-Agent": "Mozilla/5.0 pp-Echo web.search",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        response_url = str(response.url)
        if "wappass.baidu.com" in response_url or "captcha" in response_url or "百度安全验证" in response.text:
            raise RuntimeError("Baidu search returned a security verification page")
        results: list[dict[str, str]] = []
        for href, title in re.findall(r'(?is)<h3[^>]*class="[^"]*(?:t|c-title)[^"]*"[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?</h3>', response.text):
            clean_title = _readable_text(title)
            if clean_title:
                results.append({"title": clean_title, "url": html.unescape(href), "snippet": ""})
            if len(results) >= limit:
                break
        if results:
            return results
        for href, title in re.findall(r'(?is)<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', response.text):
            clean_title = _readable_text(title)
            if clean_title and len(clean_title) >= 4 and "百度" not in clean_title:
                results.append({"title": clean_title, "url": html.unescape(href), "snippet": ""})
            if len(results) >= limit:
                break
        return results


class ZhipuSearchProvider:
    name = "zhipu"

    def __init__(self, *, api_key_env: str, base_url: str, timeout_seconds: int = 10) -> None:
        self.api_key_env = api_key_env
        self.base_url = base_url.rstrip("/")
        self.client = GuardedHttpClient(WebGuardConfig(timeout_seconds=timeout_seconds))

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
        response = self.client.post(
            self.base_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        return _zhipu_results(response.json(), limit=limit)


class BraveSearchProvider:
    name = "brave"

    def __init__(self, *, api_key_env: str, timeout_seconds: int = 10) -> None:
        self.api_key_env = api_key_env
        self.client = GuardedHttpClient(WebGuardConfig(timeout_seconds=timeout_seconds))

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing Brave search API key in environment variable: {self.api_key_env}")
        response = self.client.get(
            f"https://api.search.brave.com/res/v1/web/search?q={quote_plus(query)}&count={limit}",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        )
        payload = response.json()
        results = []
        for item in payload.get("web", {}).get("results", [])[:limit]:
            results.append(
                {
                    "title": str(item.get("title") or item.get("url") or "").strip(),
                    "url": str(item.get("url") or "").strip(),
                    "snippet": str(item.get("description") or "").strip(),
                }
            )
        return results


class TavilySearchProvider:
    name = "tavily"

    def __init__(self, *, api_key_env: str, timeout_seconds: int = 10) -> None:
        self.api_key_env = api_key_env
        self.client = GuardedHttpClient(WebGuardConfig(timeout_seconds=timeout_seconds))

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing Tavily API key in environment variable: {self.api_key_env}")
        response = self.client.post(
            "https://api.tavily.com/search",
            headers={"Content-Type": "application/json"},
            json={"api_key": api_key, "query": query, "max_results": limit, "include_answer": False},
        )
        payload = response.json()
        return _normalize_results(payload.get("results", []), limit=limit)


class SerpAPISearchProvider:
    name = "serpapi"

    def __init__(self, *, api_key_env: str, timeout_seconds: int = 10) -> None:
        self.api_key_env = api_key_env
        self.client = GuardedHttpClient(WebGuardConfig(timeout_seconds=timeout_seconds))

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing SerpAPI key in environment variable: {self.api_key_env}")
        response = self.client.get(
            f"https://serpapi.com/search.json?engine=google&q={quote_plus(query)}&api_key={api_key}&num={limit}",
        )
        payload = response.json()
        return _normalize_results(payload.get("organic_results", []), limit=limit)


class ExaSearchProvider:
    name = "exa"

    def __init__(self, *, api_key_env: str, timeout_seconds: int = 10) -> None:
        self.api_key_env = api_key_env
        self.client = GuardedHttpClient(WebGuardConfig(timeout_seconds=timeout_seconds))

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing Exa API key in environment variable: {self.api_key_env}")
        response = self.client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={"query": query, "numResults": limit},
        )
        payload = response.json()
        return _normalize_results(payload.get("results", []), limit=limit)


class GitHubSearchClient:
    name = "github"

    def __init__(self, *, token_env: str, timeout_seconds: int = 10) -> None:
        self.token_env = token_env
        self.client = GuardedHttpClient(WebGuardConfig(timeout_seconds=timeout_seconds))

    def search_repositories(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "pp-Echo"}
        token = os.getenv(self.token_env)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = self.client.get(
            f"https://api.github.com/search/repositories?q={quote_plus(query)}&sort=stars&order=desc&per_page={limit}",
            headers=headers,
        )
        payload = response.json()
        results: list[dict[str, str]] = []
        for item in payload.get("items", [])[:limit]:
            results.append(
                {
                    "title": str(item.get("full_name") or item.get("name") or "").strip(),
                    "url": str(item.get("html_url") or "").strip(),
                    "snippet": str(item.get("description") or "").strip(),
                    "stars": str(item.get("stargazers_count") or 0),
                    "language": str(item.get("language") or ""),
                    "updated_at": str(item.get("pushed_at") or item.get("updated_at") or ""),
                }
            )
        return results


def build_search_providers(*, provider_names: list[str], settings: Any) -> list[SearchProvider]:
    providers: list[SearchProvider] = []
    for name in provider_names:
        if name == "mock":
            providers.append(MockSearchProvider())
        elif name == "brave":
            providers.append(BraveSearchProvider(api_key_env=settings.capabilities.web.provider_keys_env.get("brave", "BRAVE_SEARCH_API_KEY"), timeout_seconds=settings.capabilities.web.search_timeout_seconds))
        elif name == "tavily":
            providers.append(TavilySearchProvider(api_key_env=settings.capabilities.web.provider_keys_env.get("tavily", "TAVILY_API_KEY"), timeout_seconds=settings.capabilities.web.search_timeout_seconds))
        elif name == "serpapi":
            providers.append(SerpAPISearchProvider(api_key_env=settings.capabilities.web.provider_keys_env.get("serpapi", "SERPAPI_API_KEY"), timeout_seconds=settings.capabilities.web.search_timeout_seconds))
        elif name == "exa":
            providers.append(ExaSearchProvider(api_key_env=settings.capabilities.web.provider_keys_env.get("exa", "EXA_API_KEY"), timeout_seconds=settings.capabilities.web.search_timeout_seconds))
        elif name == "baidu":
            providers.append(BaiduSearchProvider(timeout_seconds=settings.capabilities.web.search_timeout_seconds))
        elif name == "zhipu":
            providers.append(ZhipuSearchProvider(api_key_env=settings.capabilities.web.zhipu_api_key_env, base_url=settings.capabilities.web.zhipu_base_url, timeout_seconds=settings.capabilities.web.search_timeout_seconds))
        elif name == "bing":
            providers.append(BingSearchProvider(timeout_seconds=settings.capabilities.web.search_timeout_seconds))
        elif name == "duckduckgo":
            providers.append(DuckDuckGoSearchProvider(timeout_seconds=settings.capabilities.web.search_timeout_seconds))
        else:
            raise ValueError(f"Unknown web.search provider: {name}")
    return providers


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


def _normalize_results(items: list[Any], *, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        url = str(item.get("url") or item.get("link") or item.get("html_url") or "").strip()
        snippet = str(item.get("content") or item.get("snippet") or item.get("description") or "").strip()
        if title or url:
            results.append({"title": title or url, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


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
    return _normalize_results(candidates, limit=limit)


def parse_github_since(since: str | None) -> str | None:
    if not since:
        return None
    text = since.strip().lower()
    if text in {"daily", "day"}:
        return _days_ago(1)
    if text in {"weekly", "week"}:
        return _days_ago(7)
    if text in {"monthly", "month"}:
        return _days_ago(30)
    return since


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
