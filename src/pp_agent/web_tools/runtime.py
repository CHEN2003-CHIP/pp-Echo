from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote_plus

import httpx

from pp_agent.tools.base import ToolExecutionResult
from pp_agent.tools.policy import PermissionDomain
from pp_agent.tools.registry import ToolRegistry


class SearchProvider(Protocol):
    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        ...


class MockSearchProvider:
    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        return [{"title": f"Mock result for {query}", "url": "https://example.com/", "snippet": "Mock web.search result."}][:limit]


class DuckDuckGoSearchProvider:
    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        with httpx.Client(timeout=10, follow_redirects=True) as client:
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


@dataclass
class WebRuntime:
    workspace: Path
    tool_registry: ToolRegistry
    search_provider: SearchProvider | None = None
    _registered_tool_names: list[str] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._register_tools()

    def _register_tools(self) -> None:
        self.tool_registry.register_function_tool(
            name="web.search",
            description="Search the public web without opening a browser. Use this for static research before browser automation.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "provider": {"type": "string", "enum": ["mock", "duckduckgo", "mcp"]},
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

    def _execute_search(self, workspace: Path, arguments: dict[str, Any]) -> ToolExecutionResult:
        query = str(arguments["query"])
        limit = max(1, min(10, int(arguments.get("limit", 5))))
        provider_name = str(arguments.get("provider") or "mock")
        if provider_name == "mcp":
            return self._result("web.search provider 'mcp' is reserved.", {"reserved": True}, is_error=True)
        provider = self.search_provider or (DuckDuckGoSearchProvider() if provider_name == "duckduckgo" else MockSearchProvider())
        results = provider.search(query, limit=limit)
        lines = [f"{item.get('title', '')} - {item.get('url', '')}" for item in results]
        return self._result("\n".join(lines) if lines else "No web.search results.", {"query": query, "results": results, "routing": "static_search"})

    def _execute_fetch(self, workspace: Path, arguments: dict[str, Any]) -> ToolExecutionResult:
        url = str(arguments["url"])
        max_chars = max(1, int(arguments.get("max_chars", 4000)))
        with httpx.Client(timeout=10, follow_redirects=True) as client:
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


def _readable_text(raw: str) -> str:
    value = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", raw)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value
