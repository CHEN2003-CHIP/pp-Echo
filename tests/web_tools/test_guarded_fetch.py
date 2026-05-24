from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from pp_agent.web_tools.guarded_fetch import GuardedFetchError, GuardedHttpClient, WebGuardConfig


@dataclass
class _FakeResponse:
    status_code: int
    url: str
    text: str = ""
    headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        self.headers = self.headers or {}
        self.extensions: dict[str, object] = {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


class _RedirectClient:
    instances: list["_RedirectClient"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.requests: list[dict[str, object]] = []
        _RedirectClient.instances.append(self)

    def __enter__(self) -> "_RedirectClient":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def request(self, method: str, url: str, *, headers=None, json=None):
        headers = dict(headers or {})
        self.requests.append({"method": method, "url": url, "headers": headers, "json": json})
        if len(self.requests) == 1:
            return _FakeResponse(302, url, headers={"location": "https://example.org/final"})
        return _FakeResponse(200, "https://example.org/final", text="<html><body>ok</body></html>")


def test_guarded_fetch_blocks_private_ip() -> None:
    client = GuardedHttpClient(WebGuardConfig(timeout_seconds=1, allow_private_network=False))

    with pytest.raises(GuardedFetchError):
        client.get("http://127.0.0.1:8000")


def test_guarded_fetch_strips_sensitive_headers_on_cross_origin_redirect(monkeypatch) -> None:
    monkeypatch.setattr("pp_agent.web_tools.guarded_fetch.httpx.Client", _RedirectClient)
    _RedirectClient.instances.clear()
    client = GuardedHttpClient(WebGuardConfig(timeout_seconds=1, allow_private_network=True, max_redirects=3))

    response = client.get("https://example.com/start", headers={"Authorization": "Bearer secret", "Cookie": "a=b", "X-Other": "keep"})

    assert response.status_code == 200
    assert len(_RedirectClient.instances) == 1
    requests = _RedirectClient.instances[0].requests
    assert requests[0]["headers"]["Authorization"] == "Bearer secret"
    assert requests[1]["headers"].get("Authorization") is None
    assert requests[1]["headers"].get("Cookie") is None
    assert requests[1]["headers"]["X-Other"] == "keep"
