from __future__ import annotations

import os
import subprocess

from pp_agent.sandbox.base import SandboxRunRequest, SandboxRunResult


class LocalSandboxExecutor:
    """Execute commands on the local host while preserving current shell behavior."""

    backend = "local"
    sandbox_mode = "danger-full-access"

    def run(self, request: SandboxRunRequest) -> SandboxRunResult:
        """Run the requested command with PowerShell and normalize timeout results."""

        env = os.environ.copy()
        if request.env:
            env.update(request.env)
        try:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    request.command,
                ],
                cwd=str(request.cwd),
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            return SandboxRunResult(
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                returncode=124,
                timed_out=True,
                backend=self.backend,
                sandbox_mode=self.sandbox_mode,
                network_access=True,
                network_allowlist=[],
                network_policy_mode="dangerously_allow_all",
                network_enforced=True,
                writable_roots=[str(request.cwd)],
            )
        return SandboxRunResult(
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
            timed_out=False,
            backend=self.backend,
            sandbox_mode=self.sandbox_mode,
            network_access=True,
            network_allowlist=[],
            network_policy_mode="dangerously_allow_all",
            network_enforced=True,
            writable_roots=[str(request.cwd)],
        )
