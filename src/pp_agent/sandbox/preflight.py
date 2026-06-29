from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pp_agent.sandbox.config import DEFAULT_DOCKER_SANDBOX_IMAGE, SandboxConfig


DOCKER_DESKTOP_INSTALL_URLS = {
    "windows": "https://docs.docker.com/desktop/install/windows-install/",
    "darwin": "https://docs.docker.com/desktop/install/mac-install/",
    "linux": "https://docs.docker.com/engine/install/",
}


@dataclass(frozen=True)
class SandboxPreflightStatus:
    """Describe whether the selected sandbox backend can run before approval time."""

    ok: bool
    enabled: bool
    backend: str
    image: str
    sandbox_isolation: str
    docker_found: bool | None = None
    docker_path: str | None = None
    daemon_available: bool | None = None
    image_available: bool | None = None
    network_policy_mode: str = "none"
    network_enforced: bool = True
    message: str = ""
    install_url: str | None = None
    docs_url: str = "docs/sandbox.md"
    build_command: str | None = None
    pull_command: str | None = None
    next_steps: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe payload for Web/API details and trace metadata."""

        return {
            "ok": self.ok,
            "enabled": self.enabled,
            "backend": self.backend,
            "image": self.image,
            "sandbox_isolation": self.sandbox_isolation,
            "docker_found": self.docker_found,
            "docker_path": self.docker_path,
            "daemon_available": self.daemon_available,
            "image_available": self.image_available,
            "network_policy_mode": self.network_policy_mode,
            "network_enforced": self.network_enforced,
            "message": self.message,
            "install_url": self.install_url,
            "docs_url": self.docs_url,
            "build_command": self.build_command,
            "pull_command": self.pull_command,
            "next_steps": list(self.next_steps),
            "checks": list(self.checks),
        }


class DockerSandboxPreflightError(RuntimeError):
    """Raised when Docker sandbox was selected but host prerequisites are missing."""

    def __init__(self, status: SandboxPreflightStatus) -> None:
        super().__init__(status.message)
        self.status = status
        self.details = {"docker_preflight": status.to_dict(), "sandbox_preflight": status.to_dict()}


def sandbox_preflight_status(
    *,
    config: SandboxConfig,
    workspace: Path | None = None,
    timeout_seconds: float = 3.0,
) -> SandboxPreflightStatus:
    """Check the configured sandbox backend without mutating the workspace."""

    resolved = config.normalized()
    if not resolved.enabled or resolved.backend == "local":
        return SandboxPreflightStatus(
            ok=True,
            enabled=resolved.enabled,
            backend="local",
            image=resolved.image,
            sandbox_isolation="none-local-compat",
            network_policy_mode="local",
            network_enforced=False,
            message="Local backend is compatibility mode; it is not secure isolation.",
            next_steps=["Enable the docker backend to run shell commands in the Docker sandbox."],
        )
    if resolved.backend != "docker":
        raise ValueError(f"Unsupported sandbox backend: {resolved.backend}")
    return docker_preflight_status(image=resolved.image, workspace=workspace, timeout_seconds=timeout_seconds)


def docker_preflight_status(
    *,
    image: str = DEFAULT_DOCKER_SANDBOX_IMAGE,
    workspace: Path | None = None,
    timeout_seconds: float = 3.0,
) -> SandboxPreflightStatus:
    """Check Docker CLI, daemon, and configured image availability."""

    docker_path = shutil.which("docker")
    install_url = _docker_install_url()
    build_command = "docker build -t pp-echo-sandbox:base -f docker/sandbox-base/Dockerfile ."
    pull_command = f"docker pull {image}" if image and image != DEFAULT_DOCKER_SANDBOX_IMAGE else None
    checks: list[dict[str, Any]] = []
    if not docker_path:
        checks.append({"name": "docker_cli", "ok": False, "message": "docker executable was not found on PATH"})
        return SandboxPreflightStatus(
            ok=False,
            enabled=True,
            backend="docker",
            image=image,
            sandbox_isolation="docker",
            docker_found=False,
            docker_path=None,
            daemon_available=None,
            image_available=None,
            message="Docker sandbox backend requested, but the docker executable was not found.",
            install_url=install_url,
            build_command=build_command,
            pull_command=pull_command,
            next_steps=[
                "Install Docker Desktop or Docker Engine, then restart the pp-Echo Web process.",
                "Confirm `docker version` works in the same terminal used to start pp-Echo.",
                f"Build the base image: {build_command}",
            ],
            checks=checks,
        )

    checks.append({"name": "docker_cli", "ok": True, "message": docker_path})
    daemon = _run_check([docker_path, "info", "--format", "{{.ServerVersion}}"], timeout_seconds=timeout_seconds)
    checks.append({"name": "docker_daemon", **daemon})
    if not daemon["ok"]:
        return SandboxPreflightStatus(
            ok=False,
            enabled=True,
            backend="docker",
            image=image,
            sandbox_isolation="docker",
            docker_found=True,
            docker_path=docker_path,
            daemon_available=False,
            image_available=None,
            message="Docker CLI was found, but the Docker daemon is not available.",
            install_url=install_url,
            build_command=build_command,
            pull_command=pull_command,
            next_steps=[
                "Start Docker Desktop or the Docker daemon.",
                "Confirm `docker info` works in the same terminal used to start pp-Echo.",
                f"Build the base image if needed: {build_command}",
            ],
            checks=checks,
        )

    image_check = _run_check([docker_path, "image", "inspect", image], timeout_seconds=timeout_seconds)
    checks.append({"name": "docker_image", **image_check})
    if not image_check["ok"]:
        image_step = (
            f"Build the pp-Echo base image: {build_command}"
            if image == DEFAULT_DOCKER_SANDBOX_IMAGE
            else f"Build or pull the configured sandbox image `{image}` before running sandbox commands."
        )
        return SandboxPreflightStatus(
            ok=False,
            enabled=True,
            backend="docker",
            image=image,
            sandbox_isolation="docker",
            docker_found=True,
            docker_path=docker_path,
            daemon_available=True,
            image_available=False,
            message=f"Docker is available, but sandbox image `{image}` was not found.",
            install_url=install_url,
            build_command=build_command,
            pull_command=pull_command,
            next_steps=[image_step, "Re-run sandbox status after the image exists locally."],
            checks=checks,
        )

    return SandboxPreflightStatus(
        ok=True,
        enabled=True,
        backend="docker",
        image=image,
        sandbox_isolation="docker",
        docker_found=True,
        docker_path=docker_path,
        daemon_available=True,
        image_available=True,
        message="Docker sandbox prerequisites are ready.",
        install_url=install_url,
        build_command=build_command,
        pull_command=pull_command,
        next_steps=["Approve shell commands normally; file changes still require a separate patch apply approval."],
        checks=checks,
    )


def ensure_docker_preflight_ok(*, image: str, workspace: Path | None = None) -> SandboxPreflightStatus:
    """Raise a structured error if Docker sandbox prerequisites are not ready."""

    status = docker_preflight_status(image=image, workspace=workspace)
    if not status.ok:
        raise DockerSandboxPreflightError(status)
    return status


def _run_check(args: list[str], *, timeout_seconds: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc)}
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "").strip(),
        "stderr": (completed.stderr or "").strip(),
    }


def _docker_install_url() -> str:
    return DOCKER_DESKTOP_INSTALL_URLS.get(platform.system().lower(), DOCKER_DESKTOP_INSTALL_URLS["linux"])
