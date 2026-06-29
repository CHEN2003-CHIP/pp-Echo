from __future__ import annotations

import difflib
import filecmp
import shutil
import subprocess
import tempfile
from pathlib import Path

from pp_agent.sandbox.base import SandboxRunRequest, SandboxRunResult
from pp_agent.sandbox.changes import (
    StructuredFileChange,
    bytes_digest,
    content_digest,
    is_protected_path,
    structured_changes_digest,
)
from pp_agent.sandbox.config import DEFAULT_DOCKER_SANDBOX_IMAGE
from pp_agent.sandbox.network import resolve_network_policy, split_network_allowlist
from pp_agent.sandbox.preflight import DockerSandboxPreflightError, docker_preflight_status, ensure_docker_preflight_ok


MAX_DIFF_FILE_BYTES = 1024 * 1024
MAX_PATCH_BYTES = 64 * 1024


class DockerSandboxExecutor:
    """Execute shell commands inside a Docker container with a locked-down MVP profile."""

    backend = "docker"
    sandbox_mode = "docker"

    def __init__(
        self,
        *,
        image: str = DEFAULT_DOCKER_SANDBOX_IMAGE,
        network_access: bool = False,
        network_allowlist: list[str] | None = None,
        network_dangerously_allow_all: bool = False,
        memory: str = "512m",
        cpus: str = "1",
        max_diff_file_bytes: int = MAX_DIFF_FILE_BYTES,
        max_patch_bytes: int = MAX_PATCH_BYTES,
    ) -> None:
        """Configure the Docker image and basic resource limits used for sandbox runs."""

        self.image = image
        self.network_access = bool(network_access)
        self.network_allowlist = split_network_allowlist(network_allowlist)
        self.network_dangerously_allow_all = bool(network_dangerously_allow_all)
        self.network_policy = resolve_network_policy(
            network_access=self.network_access,
            network_allowlist=self.network_allowlist,
            network_dangerously_allow_all=self.network_dangerously_allow_all,
        )
        self.network_access = bool(self.network_policy["network_access"])
        self.network_allowlist = list(self.network_policy["network_allowlist"])
        self.network_policy_mode = str(self.network_policy["network_policy_mode"])
        self.network_enforced = bool(self.network_policy["network_enforced"])
        self.docker_network = str(self.network_policy["docker_network"])
        self.memory = memory
        self.cpus = cpus
        self.max_diff_file_bytes = max_diff_file_bytes
        self.max_patch_bytes = max_patch_bytes

    def run(self, request: SandboxRunRequest) -> SandboxRunResult:
        """Run the command in a temporary workspace and return candidate file changes."""

        if self.network_policy_mode == "allowlist_config_only" and not self.network_enforced:
            raise RuntimeError(
                "network allowlist enforcement is not implemented yet; "
                "use network_dangerously_allow_all=true only if you accept full network risk"
            )
        source_workspace = request.cwd.resolve()
        with tempfile.TemporaryDirectory(prefix="pp-agent-docker-sandbox-") as temp_root:
            temp_workspace = Path(temp_root) / "workspace"
            copied_files = self.prepare_workspace(source_workspace, temp_workspace)
            docker_request = SandboxRunRequest(
                command=request.command,
                cwd=temp_workspace,
                timeout_seconds=request.timeout_seconds,
                env=request.env,
            )
            completed = self._run_docker(docker_request)
            diff = self.collect_workspace_diff(
                source_workspace=source_workspace,
                sandbox_workspace=temp_workspace,
                copied_files=copied_files,
            )
            return SandboxRunResult(
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
                returncode=completed.returncode,
                timed_out=completed.timed_out,
                backend=self.backend,
                sandbox_mode=self.sandbox_mode,
                network_access=self.network_access,
                network_allowlist=self.network_allowlist,
                network_policy_mode=self.network_policy_mode,
                network_enforced=self.network_enforced,
                writable_roots=[str(source_workspace)],
                changed_files=diff["changed_files"],
                patch_summary=diff["patch_summary"],
                patch=diff["patch"],
                patch_truncated=bool(diff["patch_truncated"]),
                structured_changes=diff["structured_changes"],
                structured_changes_digest=str(diff["structured_changes_digest"]),
                structured_changes_truncated=bool(diff["structured_changes_truncated"]),
            )

    def build_command(self, request: SandboxRunRequest) -> list[str]:
        """Build the Docker CLI invocation for a sandboxed shell command."""

        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            self.docker_network,
            "--read-only",
            "--memory",
            self.memory,
            "--cpus",
            self.cpus,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
        ]
        for key, value in sorted((request.env or {}).items()):
            command.extend(["-e", f"{key}={value}"])
        command.extend(
            [
                "-v",
                f"{request.cwd}:/workspace:rw",
                "-w",
                "/workspace",
                self.image,
                "bash",
                "-lc",
                request.command,
            ]
        )
        return command

    def prepare_workspace(self, source_workspace: Path, sandbox_workspace: Path) -> set[str]:
        """Copy non-protected workspace files into the sandbox directory."""

        source_workspace = source_workspace.resolve()
        sandbox_workspace.mkdir(parents=True, exist_ok=True)
        copied_files: set[str] = set()
        for source_path in source_workspace.rglob("*"):
            if source_path.is_symlink():
                continue
            if self._is_protected(source_workspace, source_path):
                continue
            relative = source_path.relative_to(source_workspace).as_posix()
            target_path = sandbox_workspace / relative
            if source_path.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue
            if source_path.is_file():
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
                copied_files.add(relative)
        return copied_files

    def collect_workspace_diff(
        self,
        *,
        source_workspace: Path,
        sandbox_workspace: Path,
        copied_files: set[str],
    ) -> dict[str, object]:
        """Compare the sandbox workspace with the source and summarize candidate changes."""

        source_workspace = source_workspace.resolve()
        sandbox_workspace = sandbox_workspace.resolve()
        sandbox_files = self._workspace_files(sandbox_workspace)
        candidate_files = sorted(copied_files | sandbox_files)
        changed_files: list[dict[str, str | int | bool]] = []
        patches: list[str] = []
        structured_changes: list[dict] = []
        truncated = False
        structured_truncated = False
        patch_size = 0

        for relative in candidate_files:
            source_path = source_workspace / relative
            sandbox_path = sandbox_workspace / relative
            if self._is_protected(source_workspace, source_path):
                continue
            if self._is_protected(sandbox_workspace, sandbox_path):
                continue
            before_exists = relative in copied_files and source_path.exists()
            after_exists = relative in sandbox_files and sandbox_path.exists()
            if before_exists and after_exists and filecmp.cmp(source_path, sandbox_path, shallow=False):
                continue
            status = "modified" if before_exists and after_exists else "added" if after_exists else "deleted"
            before_size = source_path.stat().st_size if before_exists else 0
            after_size = sandbox_path.stat().st_size if after_exists else 0
            before_bytes = source_path.read_bytes() if before_exists and before_size <= self.max_diff_file_bytes else b""
            after_bytes = sandbox_path.read_bytes() if after_exists and after_size <= self.max_diff_file_bytes else b""
            change_truncated = before_size > self.max_diff_file_bytes or after_size > self.max_diff_file_bytes
            change = {
                "path": relative,
                "status": status,
                "before_size": before_size,
                "after_size": after_size,
                "before_digest": bytes_digest(before_bytes) if before_exists and not change_truncated else "",
                "after_digest": bytes_digest(after_bytes) if after_exists and not change_truncated else "",
                "truncated": change_truncated,
            }
            changed_files.append(change)
            structured_change = self._structured_change(
                relative,
                change_type=status,
                before_exists=before_exists,
                after_exists=after_exists,
                before_size=before_size,
                after_size=after_size,
                before_bytes=before_bytes,
                after_bytes=after_bytes,
                truncated=change_truncated,
            )
            structured_changes.append(structured_change.to_dict())
            if structured_change.binary or structured_change.truncated:
                structured_truncated = True
            file_patch = self._file_patch(relative, source_path, sandbox_path, before_exists=before_exists, after_exists=after_exists)
            if file_patch:
                encoded_len = len(file_patch.encode("utf-8"))
                if patch_size + encoded_len <= self.max_patch_bytes:
                    patches.append(file_patch)
                    patch_size += encoded_len
                else:
                    truncated = True
            elif change["truncated"]:
                truncated = True

        summary = self._patch_summary(changed_files, truncated=truncated)
        return {
            "changed_files": changed_files,
            "patch_summary": summary,
            "patch": "\n".join(patches),
            "patch_truncated": truncated,
            "structured_changes": structured_changes,
            "structured_changes_digest": structured_changes_digest(structured_changes),
            "structured_changes_truncated": structured_truncated,
        }

    def _structured_change(
        self,
        relative: str,
        *,
        change_type: str,
        before_exists: bool,
        after_exists: bool,
        before_size: int,
        after_size: int,
        before_bytes: bytes,
        after_bytes: bytes,
        truncated: bool,
    ) -> StructuredFileChange:
        """Build a structured file change from collected sandbox diff bytes."""

        binary = False
        content_text = None
        if after_exists and not truncated:
            try:
                content_text = after_bytes.decode("utf-8")
            except UnicodeDecodeError:
                binary = True
        return StructuredFileChange(
            path=relative,
            change_type=change_type,
            old_digest=bytes_digest(before_bytes) if before_exists and not truncated else None,
            new_digest=bytes_digest(after_bytes) if after_exists and not truncated else None,
            content_text=content_text,
            content_encoding="utf-8",
            binary=binary,
            truncated=truncated,
            size_bytes=after_size if after_exists else before_size,
        )

    def _run_docker(self, request: SandboxRunRequest) -> SandboxRunResult:
        """Run Docker against an already prepared temporary workspace."""

        preflight = ensure_docker_preflight_ok(image=self.image, workspace=request.cwd)
        command = self.build_command(request)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise DockerSandboxPreflightError(docker_preflight_status(image=self.image, workspace=request.cwd)) from exc
        except OSError as exc:
            raise RuntimeError(f"Docker sandbox backend failed to start: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            return SandboxRunResult(
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                returncode=124,
                timed_out=True,
                backend=self.backend,
                sandbox_mode=self.sandbox_mode,
                network_access=self.network_access,
                network_allowlist=self.network_allowlist,
                network_policy_mode=self.network_policy_mode,
                network_enforced=self.network_enforced,
                writable_roots=[str(request.cwd)],
            )
        return SandboxRunResult(
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
            timed_out=False,
            backend=self.backend,
            sandbox_mode=self.sandbox_mode,
            network_access=self.network_access,
            network_allowlist=self.network_allowlist,
            network_policy_mode=self.network_policy_mode,
            network_enforced=self.network_enforced,
            writable_roots=[str(request.cwd)],
        )

    def _workspace_files(self, workspace: Path) -> set[str]:
        """Return all non-protected file paths relative to a workspace."""

        files: set[str] = set()
        for path in workspace.rglob("*"):
            if path.is_symlink():
                continue
            if self._is_protected(workspace, path):
                continue
            if path.is_file():
                files.add(path.relative_to(workspace).as_posix())
        return files

    def _file_patch(
        self,
        relative: str,
        before_path: Path,
        after_path: Path,
        *,
        before_exists: bool,
        after_exists: bool,
    ) -> str:
        """Generate a bounded unified diff for one text-like file change."""

        before_size = before_path.stat().st_size if before_exists else 0
        after_size = after_path.stat().st_size if after_exists else 0
        if before_size > self.max_diff_file_bytes or after_size > self.max_diff_file_bytes:
            return ""
        before_lines = before_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if before_exists else []
        after_lines = after_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if after_exists else []
        return "".join(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
            )
        )

    @staticmethod
    def _patch_summary(changed_files: list[dict[str, str | int | bool]], *, truncated: bool) -> str:
        """Render a compact summary of candidate sandbox changes."""

        counts = {"added": 0, "modified": 0, "deleted": 0}
        for change in changed_files:
            status = str(change.get("status") or "")
            if status in counts:
                counts[status] += 1
        parts = [
            f"{counts['added']} added",
            f"{counts['modified']} modified",
            f"{counts['deleted']} deleted",
        ]
        if truncated:
            parts.append("patch truncated")
        return ", ".join(parts)

    @staticmethod
    def _is_protected(workspace: Path, path: Path) -> bool:
        """Return whether a path should be excluded from sandbox copy or diff."""

        if path.is_symlink():
            return True
        normalized = str(path).replace("\\", "/").lower()
        parts = [part for part in normalized.split("/") if part not in {"", "."}]
        collapsed: list[str] = []
        for part in parts:
            if part == "..":
                if collapsed:
                    collapsed.pop()
                continue
            collapsed.append(part)
        name = collapsed[-1] if collapsed else ""
        if name == ".env" or name.startswith(".env.") or name.endswith(".pem") or name.endswith(".key"):
            return True
        if ".git" in collapsed or ".pp-agent" in collapsed:
            return True
        return is_protected_path(workspace, path)
