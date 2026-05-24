from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx


_SENSITIVE_HEADERS = {"authorization", "cookie", "proxy-authorization", "x-api-key"}


@dataclass(frozen=True)
class WebGuardConfig:
    timeout_seconds: int = 10
    allow_private_network: bool = False
    max_redirects: int = 5


class GuardedFetchError(RuntimeError):
    pass


class GuardedHttpClient:
    def __init__(self, config: WebGuardConfig) -> None:
        self.config = config

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
        return self.request("GET", url, headers=headers)

    def post(self, url: str, *, headers: dict[str, str] | None = None, json: Any | None = None) -> httpx.Response:
        return self.request("POST", url, headers=headers, json=json)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
    ) -> httpx.Response:
        current_url = _validate_url(url, allow_private_network=self.config.allow_private_network)
        request_headers = dict(headers or {})
        redirects: list[str] = []
        with httpx.Client(timeout=self.config.timeout_seconds, follow_redirects=False) as client:
            for _ in range(self.config.max_redirects + 1):
                response = client.request(method, current_url, headers=request_headers, json=json)
                if response.status_code not in {301, 302, 303, 307, 308}:
                    response.raise_for_status()
                    response.extensions["pp_echo_redirects"] = redirects
                    return response
                location = response.headers.get("location", "").strip()
                if not location:
                    response.raise_for_status()
                    return response
                next_url = _validate_url(
                    urljoin(current_url, location),
                    allow_private_network=self.config.allow_private_network,
                )
                redirects.append(next_url)
                if _origin(current_url) != _origin(next_url):
                    request_headers = {
                        key: value
                        for key, value in request_headers.items()
                        if key.lower() not in _SENSITIVE_HEADERS
                    }
                    json = None
                    method = "GET" if response.status_code == 303 else method
                current_url = next_url
            raise GuardedFetchError(f"Too many redirects while fetching {url!r}; max_redirects={self.config.max_redirects}")


def _validate_url(url: str, *, allow_private_network: bool) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise GuardedFetchError("Only http and https URLs are allowed.")
    hostname = (parsed.hostname or "").strip()
    if not hostname:
        raise GuardedFetchError("URL must include a hostname.")
    if not allow_private_network:
        for address in _resolve_addresses(hostname):
            if _is_private_or_internal(address):
                raise GuardedFetchError(f"Blocked private/internal network address: {address}")
    return value


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    return (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port)


def _resolve_addresses(hostname: str) -> list[str]:
    try:
        return sorted({item[4][0] for item in socket.getaddrinfo(hostname, None)})
    except socket.gaierror:
        try:
            ipaddress.ip_address(hostname)
            return [hostname]
        except ValueError:
            return []


def _is_private_or_internal(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or str(address) == "169.254.169.254"
    )
