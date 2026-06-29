from __future__ import annotations

from pp_agent.sandbox.base import SandboxExecutor
from pp_agent.sandbox.config import SandboxConfig
from pp_agent.sandbox.docker import DockerSandboxExecutor
from pp_agent.sandbox.local import LocalSandboxExecutor


def get_sandbox_executor(
    *,
    backend: str | None = None,
    image: str | None = None,
    memory: str | None = None,
    cpus: str | None = None,
    network_access: bool | None = None,
    network_allowlist: list[str] | None = None,
    network_dangerously_allow_all: bool | None = None,
    config: SandboxConfig | None = None,
) -> SandboxExecutor:
    """Resolve the configured sandbox executor for shell command execution."""

    resolved = config.normalized() if config is not None else SandboxConfig()
    if backend is not None:
        resolved = SandboxConfig(
            enabled=backend.strip().lower() != "local",
            backend=backend,
            image=image if image is not None else resolved.image,
            network_access=network_access if network_access is not None else resolved.network_access,
            network_allowlist=network_allowlist if network_allowlist is not None else resolved.network_allowlist,
            network_dangerously_allow_all=(
                network_dangerously_allow_all
                if network_dangerously_allow_all is not None
                else resolved.network_dangerously_allow_all
            ),
            memory=memory if memory is not None else resolved.memory,
            cpus=cpus if cpus is not None else resolved.cpus,
            timeout_seconds=resolved.timeout_seconds,
        ).normalized()
    else:
        updates = {}
        if image is not None:
            updates["image"] = image
        if memory is not None:
            updates["memory"] = memory
        if cpus is not None:
            updates["cpus"] = cpus
        if network_access is not None:
            updates["network_access"] = network_access
        if network_allowlist is not None:
            updates["network_allowlist"] = network_allowlist
        if network_dangerously_allow_all is not None:
            updates["network_dangerously_allow_all"] = network_dangerously_allow_all
        if updates:
            resolved = SandboxConfig(**{**resolved.__dict__, **updates}).normalized()

    if not resolved.enabled or resolved.backend == "local":
        return LocalSandboxExecutor()
    if resolved.backend == "docker":
        return DockerSandboxExecutor(
            image=resolved.image,
            memory=resolved.memory,
            cpus=resolved.cpus,
            network_access=resolved.network_access,
            network_allowlist=resolved.network_allowlist,
            network_dangerously_allow_all=resolved.network_dangerously_allow_all,
        )
    raise ValueError(f"Unsupported sandbox backend: {resolved.backend}")
