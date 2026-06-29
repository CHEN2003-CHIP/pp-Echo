from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from pp_agent.sandbox.network import split_network_allowlist, validate_network_allowlist


SANDBOX_BACKENDS = {"local", "docker"}
DEFAULT_DOCKER_SANDBOX_IMAGE = "pp-echo-sandbox:base"


@dataclass(frozen=True)
class SandboxConfig:
    """Configure which sandbox executor backend is used for approved shell commands."""

    enabled: bool = False
    backend: str = "local"
    image: str = DEFAULT_DOCKER_SANDBOX_IMAGE
    network_access: bool = False
    network_allowlist: list[str] = field(default_factory=list)
    network_dangerously_allow_all: bool = False
    memory: str = "512m"
    cpus: str = "1"
    timeout_seconds: Optional[int] = None

    def normalized(self) -> "SandboxConfig":
        """Return a validated config with normalized backend and bounded numeric fields."""

        backend = str(self.backend or "local").strip().lower()
        if backend not in SANDBOX_BACKENDS:
            raise ValueError(f"Unsupported sandbox backend: {self.backend}")
        if self.enabled and backend == "local":
            backend = "docker"
        timeout = int(self.timeout_seconds) if self.timeout_seconds is not None else None
        if timeout is not None and timeout < 1:
            raise ValueError("sandbox.timeout_seconds must be >= 1 when set")
        allowlist = validate_network_allowlist(split_network_allowlist(self.network_allowlist))
        dangerously_allow_all = bool(self.network_dangerously_allow_all)
        network_access = bool(self.network_access)
        if network_access and not allowlist and not dangerously_allow_all:
            raise ValueError("network_access=true requires network_allowlist or network_dangerously_allow_all=true")
        return replace(
            self,
            enabled=bool(self.enabled),
            backend=backend,
            image=str(self.image or DEFAULT_DOCKER_SANDBOX_IMAGE),
            network_access=network_access,
            network_allowlist=allowlist,
            network_dangerously_allow_all=dangerously_allow_all,
            memory=str(self.memory or "512m"),
            cpus=str(self.cpus or "1"),
            timeout_seconds=timeout,
        )


def sandbox_config_from_env(env: Optional[dict[str, str]] = None, *, base: Optional[SandboxConfig] = None) -> SandboxConfig:
    """Build SandboxConfig from PP_ECHO_SANDBOX_* environment variables."""

    source = env if env is not None else os.environ
    config = base or SandboxConfig()
    values: dict[str, Any] = {}
    if source.get("PP_ECHO_SANDBOX_BACKEND"):
        values["backend"] = source["PP_ECHO_SANDBOX_BACKEND"]
        values["enabled"] = str(source["PP_ECHO_SANDBOX_BACKEND"]).strip().lower() != "local"
    if source.get("PP_ECHO_SANDBOX_IMAGE"):
        values["image"] = source["PP_ECHO_SANDBOX_IMAGE"]
    if source.get("PP_ECHO_SANDBOX_NETWORK"):
        values["network_access"] = _env_bool(source["PP_ECHO_SANDBOX_NETWORK"])
    if source.get("PP_ECHO_SANDBOX_NETWORK_ALLOWLIST"):
        values["network_allowlist"] = split_network_allowlist(source["PP_ECHO_SANDBOX_NETWORK_ALLOWLIST"])
    if source.get("PP_ECHO_SANDBOX_NETWORK_DANGEROUSLY_ALLOW_ALL"):
        values["network_dangerously_allow_all"] = _env_bool(source["PP_ECHO_SANDBOX_NETWORK_DANGEROUSLY_ALLOW_ALL"])
    if source.get("PP_ECHO_SANDBOX_MEMORY"):
        values["memory"] = source["PP_ECHO_SANDBOX_MEMORY"]
    if source.get("PP_ECHO_SANDBOX_CPUS"):
        values["cpus"] = source["PP_ECHO_SANDBOX_CPUS"]
    if source.get("PP_ECHO_SANDBOX_TIMEOUT_SECONDS"):
        values["timeout_seconds"] = int(source["PP_ECHO_SANDBOX_TIMEOUT_SECONDS"])
    return replace(config, **values).normalized()


def sandbox_config_from_mapping(data: Optional[dict[str, Any]], *, base: Optional[SandboxConfig] = None) -> SandboxConfig:
    """Apply project/session/runtime sandbox config data on top of an existing config."""

    config = base or SandboxConfig()
    if not data:
        return config.normalized()
    values: dict[str, Any] = {}
    for key in (
        "enabled",
        "backend",
        "image",
        "network_access",
        "network_allowlist",
        "network_dangerously_allow_all",
        "memory",
        "cpus",
        "timeout_seconds",
    ):
        if key in data:
            values[key] = data[key]
    if "backend" in values and "enabled" not in values:
        values["enabled"] = str(values["backend"]).strip().lower() != "local"
    return replace(config, **values).normalized()


def apply_sandbox_cli_overrides(
    *,
    backend: Optional[str] = None,
    image: Optional[str] = None,
    network_access: Optional[bool] = None,
    network_allowlist: Optional[str | list[str]] = None,
    network_dangerously_allow_all: Optional[bool] = None,
    memory: Optional[str] = None,
    cpus: Optional[str] = None,
) -> None:
    """Store explicit CLI sandbox options in env so Settings resolves one source of truth."""

    if backend:
        os.environ["PP_ECHO_SANDBOX_BACKEND"] = backend
    if image:
        os.environ["PP_ECHO_SANDBOX_IMAGE"] = image
    if network_access is not None:
        os.environ["PP_ECHO_SANDBOX_NETWORK"] = "1" if network_access else "0"
    if network_allowlist is not None:
        if isinstance(network_allowlist, str):
            os.environ["PP_ECHO_SANDBOX_NETWORK_ALLOWLIST"] = network_allowlist
        else:
            os.environ["PP_ECHO_SANDBOX_NETWORK_ALLOWLIST"] = ",".join(str(item) for item in network_allowlist)
    if network_dangerously_allow_all is not None:
        os.environ["PP_ECHO_SANDBOX_NETWORK_DANGEROUSLY_ALLOW_ALL"] = "1" if network_dangerously_allow_all else "0"
    if memory:
        os.environ["PP_ECHO_SANDBOX_MEMORY"] = memory
    if cpus:
        os.environ["PP_ECHO_SANDBOX_CPUS"] = cpus


def _env_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
