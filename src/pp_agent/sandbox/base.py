from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SandboxRunRequest:
    """Describe one shell command execution request for a sandbox backend."""

    command: str
    cwd: Path
    timeout_seconds: int
    env: dict[str, str] | None = None


@dataclass(frozen=True)
class SandboxRunResult:
    """Capture process output and audit metadata returned by a sandbox backend."""

    stdout: str
    stderr: str
    returncode: int
    timed_out: bool
    backend: str
    sandbox_mode: str
    network_access: bool
    writable_roots: list[str]
    network_allowlist: list[str] | None = None
    network_policy_mode: str = "none"
    network_enforced: bool = True
    changed_files: list[dict[str, str | int | bool]] | None = None
    patch_summary: str | None = None
    patch: str | None = None
    patch_truncated: bool = False
    structured_changes: list[dict] | None = None
    structured_changes_digest: str | None = None
    structured_changes_truncated: bool = False


class SandboxExecutor(Protocol):
    """Run shell commands behind a stable executor boundary."""

    def run(self, request: SandboxRunRequest) -> SandboxRunResult:
        """Execute the request and return normalized output metadata."""

        ...
