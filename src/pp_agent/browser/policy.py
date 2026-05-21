from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

from pp_agent.browser.models import BrowserActRequest, BrowserNode, BrowserProfileName
from pp_agent.storage.settings import BrowserCapabilityConfig


@dataclass(frozen=True)
class BrowserPolicyDecision:
    allowed: bool
    reason: str = "allowed"
    high_risk: bool = False
    sensitive: bool = False


class BrowserPolicy:
    HIGH_RISK_TERMS = {
        "submit",
        "send",
        "delete",
        "remove",
        "buy",
        "purchase",
        "pay",
        "payment",
        "checkout",
        "order",
        "confirm",
    }
    SENSITIVE_TERMS = {
        "password",
        "token",
        "api-key",
        "apikey",
        "secret",
        "payment",
        "credit",
        "card",
        "email",
        "phone",
        "address",
    }

    def __init__(self, config: BrowserCapabilityConfig) -> None:
        self.config = config

    def check_profile(self, profile: BrowserProfileName) -> BrowserPolicyDecision:
        if profile == "user" and not self.config.allow_user_profile:
            return BrowserPolicyDecision(False, "Browser profile 'user' requires capabilities.browser.allow_user_profile=true.")
        if profile == "remote" and not self.config.allow_remote_profile:
            return BrowserPolicyDecision(False, "Browser profile 'remote' requires capabilities.browser.allow_remote_profile=true.")
        return BrowserPolicyDecision(True)

    def check_url(self, url: str) -> BrowserPolicyDecision:
        value = url.strip()
        if value == "about:blank":
            return BrowserPolicyDecision(True)
        parsed = urlparse(value)
        if parsed.scheme == "data":
            if value.lower().startswith("data:text/html"):
                return BrowserPolicyDecision(True)
            return BrowserPolicyDecision(False, "Only data:text/html URLs are allowed for browser navigation.")
        if parsed.scheme not in {"http", "https"}:
            return BrowserPolicyDecision(False, "Browser navigation only allows http, https, about:blank, and data:text/html URLs.")
        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            return BrowserPolicyDecision(False, "Browser navigation URL must include a hostname.")
        if self._matches(hostname, self.config.deny_hostnames):
            return BrowserPolicyDecision(False, f"Browser navigation to '{hostname}' is denied by browser policy.")
        if self.config.allowed_hostnames and not self._matches(hostname, self.config.allowed_hostnames):
            return BrowserPolicyDecision(False, f"Browser navigation to '{hostname}' is not in capabilities.browser.allowed_hostnames.")
        if self.config.allow_private_network:
            return BrowserPolicyDecision(True)
        for address in self._resolve_addresses(hostname):
            if self._is_private_or_internal(address):
                return BrowserPolicyDecision(False, f"Browser navigation to private/internal address '{address}' is blocked by SSRF policy.")
        return BrowserPolicyDecision(True)

    def check_act(self, request: BrowserActRequest, node: BrowserNode | None) -> BrowserPolicyDecision:
        if request.selector:
            return BrowserPolicyDecision(False, "browser.act requires a snapshot ref; raw selectors are not accepted.")
        if request.kind == "evaluate" and not self.config.evaluate_enabled:
            return BrowserPolicyDecision(False, "browser.act evaluate is disabled by browser policy.")
        if request.kind in {"wait"} and request.expression and not self.config.evaluate_enabled:
            return BrowserPolicyDecision(False, "browser.act wait functions are disabled by browser policy.")
        sensitive = self._request_or_node_sensitive(request, node)
        high_risk = self._node_high_risk(node)
        if request.kind in {"click", "type", "fill", "select", "press"} and (sensitive or high_risk):
            if not self.config.allow_high_risk_actions:
                kind = "sensitive" if sensitive else "high-risk"
                return BrowserPolicyDecision(False, f"browser.act {kind} action requires capabilities.browser.allow_high_risk_actions=true.", high_risk=high_risk, sensitive=sensitive)
        return BrowserPolicyDecision(True, high_risk=high_risk, sensitive=sensitive)

    def _request_or_node_sensitive(self, request: BrowserActRequest, node: BrowserNode | None) -> bool:
        values = [request.text or "", request.key or "", *request.values, *request.fields.keys()]
        if node is not None:
            values.extend([node.role, node.text, node.name, node.label, node.placeholder])
        return self._contains_any(values, self.SENSITIVE_TERMS)

    def _node_high_risk(self, node: BrowserNode | None) -> bool:
        if node is None:
            return False
        return self._contains_any([node.role, node.text, node.name, node.label, node.placeholder], self.HIGH_RISK_TERMS)

    @staticmethod
    def _contains_any(values: Iterable[str], terms: set[str]) -> bool:
        joined = " ".join(value.lower() for value in values if value)
        return any(term in joined for term in terms)

    @staticmethod
    def _matches(hostname: str, patterns: list[str]) -> bool:
        import fnmatch

        return any(fnmatch.fnmatch(hostname, pattern.lower()) for pattern in patterns)

    @staticmethod
    def _resolve_addresses(hostname: str) -> list[str]:
        try:
            return sorted({item[4][0] for item in socket.getaddrinfo(hostname, None)})
        except socket.gaierror:
            try:
                ipaddress.ip_address(hostname)
                return [hostname]
            except ValueError:
                return []

    @staticmethod
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
