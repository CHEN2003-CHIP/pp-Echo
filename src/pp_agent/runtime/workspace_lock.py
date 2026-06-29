from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class WorkspaceApplyLockError(RuntimeError):
    """Base error for workspace apply lock failures."""


class WorkspaceApplyLockTimeout(WorkspaceApplyLockError):
    """Raised when the workspace apply lock cannot be acquired in time."""


class WorkspaceApplyLockReleaseError(WorkspaceApplyLockError):
    """Raised when a lock handle cannot safely release its lock file."""


@dataclass
class WorkspaceApplyLockHandle:
    """Handle for a held workspace apply lock.

    The handle deletes the lock file only when the on-disk token still matches
    the token created by this process. This prevents one process from removing
    another process' lock after a timeout or stale-handle race.
    """

    lock_path: Path
    wait_ms: int
    token: str
    _released: bool = field(default=False, init=False, repr=False)

    def __enter__(self) -> "WorkspaceApplyLockHandle":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()

    def release(self) -> None:
        """Release this handle if it still owns the lock file."""

        if self._released:
            return
        try:
            payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._released = True
            return
        except Exception as exc:  # noqa: BLE001
            raise WorkspaceApplyLockReleaseError(f"Could not read workspace apply lock: {exc}") from exc
        if payload.get("token") != self.token:
            raise WorkspaceApplyLockReleaseError("Workspace apply lock is owned by a different token.")
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001
            raise WorkspaceApplyLockReleaseError(f"Could not remove workspace apply lock: {exc}") from exc
        self._released = True


class WorkspaceApplyLock:
    """Workspace-scoped lock for serialized patch candidate application.

    The lock is implemented with an atomic `O_CREAT | O_EXCL` lock file at
    `.pp-agent/locks/apply.lock`. It protects pp-Echo's own
    `apply_patch_candidate` writers from each other; it is not a filesystem
    transaction and does not block external editors, git, or shell commands.
    """

    RELATIVE_LOCK_PATH = Path(".pp-agent") / "locks" / "apply.lock"

    def __init__(
        self,
        workspace: Path,
        timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    def acquire(self) -> WorkspaceApplyLockHandle:
        """Acquire the workspace apply lock or raise on timeout."""

        lock_path = self._prepare_lock_path()
        token = uuid.uuid4().hex
        started = time.monotonic()
        deadline = started + self.timeout_seconds
        payload = {
            "pid": os.getpid(),
            "timestamp": time.time(),
            "token": token,
            "workspace": str(self.workspace),
        }
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise WorkspaceApplyLockTimeout("workspace apply lock timeout")
                time.sleep(self.poll_interval_seconds)
                continue
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(encoded)
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                raise
            wait_ms = int((time.monotonic() - started) * 1000)
            return WorkspaceApplyLockHandle(lock_path=lock_path, wait_ms=wait_ms, token=token)

    def _prepare_lock_path(self) -> Path:
        """Create and validate the internal lock directory without following symlinks."""

        pp_agent_dir = self.workspace / ".pp-agent"
        if pp_agent_dir.exists() and pp_agent_dir.is_symlink():
            raise WorkspaceApplyLockError("Refusing workspace apply lock because .pp-agent is a symlink.")
        pp_agent_dir.mkdir(mode=0o700, exist_ok=True)
        if pp_agent_dir.is_symlink():
            raise WorkspaceApplyLockError("Refusing workspace apply lock because .pp-agent is a symlink.")

        locks_dir = pp_agent_dir / "locks"
        if locks_dir.exists() and locks_dir.is_symlink():
            raise WorkspaceApplyLockError("Refusing workspace apply lock because .pp-agent/locks is a symlink.")
        locks_dir.mkdir(mode=0o700, exist_ok=True)
        if locks_dir.is_symlink():
            raise WorkspaceApplyLockError("Refusing workspace apply lock because .pp-agent/locks is a symlink.")

        lock_path = locks_dir / "apply.lock"
        if lock_path.exists() and lock_path.is_symlink():
            raise WorkspaceApplyLockError("Refusing workspace apply lock because apply.lock is a symlink.")
        return lock_path

