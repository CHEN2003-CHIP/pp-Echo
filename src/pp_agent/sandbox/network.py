from __future__ import annotations

import ipaddress
import re


class NetworkPolicyError(ValueError):
    """Raised when sandbox network policy configuration is unsafe or unsupported."""


_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "host.docker.internal",
}
_BLOCKED_IPS = {
    ipaddress.ip_address("127.0.0.1"),
    ipaddress.ip_address("0.0.0.0"),
    ipaddress.ip_address("::1"),
    ipaddress.ip_address("169.254.169.254"),
}
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("0.0.0.0/0"),
    ipaddress.ip_network("::/0"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
]
_DOMAIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
_SHELL_METACHARS_RE = re.compile(r"[;&|`$<>(){}\\\"']")


def split_network_allowlist(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize comma-separated or list-style network allowlist input."""

    if value is None:
        return []
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = list(value)
    return [str(item).strip() for item in items if str(item).strip()]


def validate_network_allowlist(entries: list[str] | tuple[str, ...]) -> list[str]:
    """Validate allowlist entries without claiming egress enforcement exists."""

    validated: list[str] = []
    for raw_entry in entries:
        entry = str(raw_entry).strip()
        lowered = entry.lower()
        if not entry:
            raise NetworkPolicyError("network_allowlist entries must not be empty.")
        if entry == "*":
            raise NetworkPolicyError("network_allowlist must not contain wildcard all (*).")
        if "://" in entry:
            raise NetworkPolicyError(f"network_allowlist entries must be hostnames only, not URLs: {entry}")
        if "/" in entry:
            _validate_network_or_reject(entry)
            raise NetworkPolicyError(f"network_allowlist entries must not include URL paths: {entry}")
        if _SHELL_METACHARS_RE.search(entry):
            raise NetworkPolicyError(f"network_allowlist entry contains shell metacharacters: {entry}")
        if lowered in _BLOCKED_HOSTS:
            raise NetworkPolicyError(f"network_allowlist entry is blocked: {entry}")
        try:
            address = ipaddress.ip_address(entry)
        except ValueError:
            if not _DOMAIN_RE.match(entry):
                raise NetworkPolicyError(f"network_allowlist entry must be a normal domain name: {entry}")
            validated.append(lowered)
            continue
        _reject_blocked_ip(address, entry)
        validated.append(str(address))
    return validated


def resolve_network_policy(
    *,
    network_access: bool,
    network_allowlist: list[str],
    network_dangerously_allow_all: bool,
) -> dict[str, object]:
    """Resolve Docker network policy mode and validate unsafe combinations."""

    allowlist = validate_network_allowlist(network_allowlist)
    if not network_access:
        return {
            "network_access": False,
            "network_allowlist": allowlist,
            "network_policy_mode": "none",
            "network_enforced": True,
            "docker_network": "none",
        }
    if network_dangerously_allow_all:
        return {
            "network_access": True,
            "network_allowlist": allowlist,
            "network_policy_mode": "dangerously_allow_all",
            "network_enforced": True,
            "docker_network": "bridge",
        }
    if allowlist:
        return {
            "network_access": True,
            "network_allowlist": allowlist,
            "network_policy_mode": "allowlist_config_only",
            "network_enforced": False,
            "docker_network": "none",
        }
    raise NetworkPolicyError("network_access=true requires network_allowlist or network_dangerously_allow_all=true")


def _validate_network_or_reject(entry: str) -> None:
    try:
        network = ipaddress.ip_network(entry, strict=False)
    except ValueError:
        return
    for blocked in _BLOCKED_NETWORKS:
        if network.version != blocked.version:
            continue
        if network.subnet_of(blocked) or blocked.subnet_of(network) or network.overlaps(blocked):
            raise NetworkPolicyError(f"network_allowlist network range is blocked: {entry}")
    raise NetworkPolicyError(f"network_allowlist CIDR ranges are not supported yet: {entry}")


def _reject_blocked_ip(address: ipaddress._BaseAddress, entry: str) -> None:
    if address in _BLOCKED_IPS:
        raise NetworkPolicyError(f"network_allowlist IP is blocked: {entry}")
    for network in _BLOCKED_NETWORKS:
        if address in network:
            raise NetworkPolicyError(f"network_allowlist IP is in a blocked range: {entry}")
