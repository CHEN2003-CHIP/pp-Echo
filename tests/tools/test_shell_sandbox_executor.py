from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from pp_agent.sandbox.docker import DockerSandboxExecutor
from pp_agent.sandbox.base import SandboxRunRequest, SandboxRunResult
from pp_agent.sandbox.changes import bytes_digest, structured_changes_digest
from pp_agent.sandbox.config import DEFAULT_DOCKER_SANDBOX_IMAGE, SandboxConfig, sandbox_config_from_env
from pp_agent.sandbox.local import LocalSandboxExecutor
from pp_agent.sandbox.network import NetworkPolicyError, validate_network_allowlist
from pp_agent.sandbox.preflight import DockerSandboxPreflightError, docker_preflight_status
from pp_agent.sandbox.resolver import get_sandbox_executor
from pp_agent.runtime.workspace_lock import (
    WorkspaceApplyLock,
    WorkspaceApplyLockError,
    WorkspaceApplyLockReleaseError,
    WorkspaceApplyLockTimeout,
)
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.tools.effects import build_patch_candidate_effect, content_digest
from pp_agent.tools.file_tools import ApprovePendingActionTool
from pp_agent.tools.policy import PermissionDomain
from pp_agent.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def _restore_sandbox_env() -> None:
    """Keep sandbox env override tests from leaking backend settings across modules."""

    keys = [
        "PP_ECHO_SANDBOX_BACKEND",
        "PP_ECHO_SANDBOX_IMAGE",
        "PP_ECHO_SANDBOX_NETWORK",
        "PP_ECHO_SANDBOX_NETWORK_ALLOWLIST",
        "PP_ECHO_SANDBOX_NETWORK_DANGEROUSLY_ALLOW_ALL",
        "PP_ECHO_SANDBOX_MEMORY",
        "PP_ECHO_SANDBOX_CPUS",
        "PP_ECHO_SANDBOX_TIMEOUT_SECONDS",
    ]
    snapshot = {key: os.environ.get(key) for key in keys}
    yield
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


class RecordingSandboxExecutor:
    """Test executor that records shell requests and returns a fixed result."""

    def __init__(self, result: SandboxRunResult) -> None:
        self.result = result
        self.requests: list[SandboxRunRequest] = []

    def run(self, request: SandboxRunRequest) -> SandboxRunResult:
        """Record the request so approval tests can assert executor routing."""

        self.requests.append(request)
        return self.result


def test_sandbox_config_defaults_to_local() -> None:
    config = SandboxConfig().normalized()

    assert config.enabled is False
    assert config.backend == "local"
    assert isinstance(get_sandbox_executor(config=config), LocalSandboxExecutor)


def test_sandbox_config_default_image_is_pp_echo_sandbox_base() -> None:
    assert SandboxConfig().normalized().image == "pp-echo-sandbox:base"
    assert SandboxConfig(image="").normalized().image == "pp-echo-sandbox:base"


def test_sandbox_config_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unsupported sandbox backend"):
        SandboxConfig(enabled=True, backend="spaceship").normalized()


def test_network_defaults_to_none(tmp_path: Path) -> None:
    config = SandboxConfig(enabled=True, backend="docker").normalized()
    executor = DockerSandboxExecutor()
    command = executor.build_command(SandboxRunRequest(command="echo ok", cwd=tmp_path, timeout_seconds=5))

    assert config.network_access is False
    assert config.network_allowlist == []
    assert config.network_dangerously_allow_all is False
    assert executor.network_policy_mode == "none"
    assert executor.network_enforced is True
    assert command[command.index("--network") + 1] == "none"


def test_network_access_true_without_allowlist_or_danger_flag_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires network_allowlist or network_dangerously_allow_all"):
        SandboxConfig(enabled=True, backend="docker", network_access=True).normalized()


def test_network_allowlist_rejects_localhost() -> None:
    with pytest.raises(NetworkPolicyError, match="blocked"):
        validate_network_allowlist(["localhost"])


def test_network_allowlist_rejects_host_docker_internal() -> None:
    with pytest.raises(NetworkPolicyError, match="blocked"):
        validate_network_allowlist(["host.docker.internal"])


def test_network_allowlist_rejects_loopback_ip() -> None:
    with pytest.raises(NetworkPolicyError, match="blocked"):
        validate_network_allowlist(["127.0.0.1"])
    with pytest.raises(NetworkPolicyError, match="blocked"):
        validate_network_allowlist(["127.0.0.0/8"])
    with pytest.raises(NetworkPolicyError, match="blocked"):
        validate_network_allowlist(["::1"])


def test_network_allowlist_rejects_private_ranges() -> None:
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
        with pytest.raises(NetworkPolicyError, match="blocked"):
            validate_network_allowlist([value])


def test_network_allowlist_rejects_link_local() -> None:
    with pytest.raises(NetworkPolicyError, match="blocked"):
        validate_network_allowlist(["169.254.0.0/16"])


def test_network_allowlist_rejects_metadata_ip() -> None:
    with pytest.raises(NetworkPolicyError, match="blocked"):
        validate_network_allowlist(["169.254.169.254"])


def test_network_allowlist_rejects_wildcard_all() -> None:
    for value in ("*", "0.0.0.0", "0.0.0.0/0", "::/0"):
        with pytest.raises(NetworkPolicyError, match="blocked|wildcard"):
            validate_network_allowlist([value])


def test_network_allowlist_rejects_urls_with_scheme() -> None:
    with pytest.raises(NetworkPolicyError, match="URLs"):
        validate_network_allowlist(["https://pypi.org"])


def test_network_allowlist_rejects_paths() -> None:
    with pytest.raises(NetworkPolicyError, match="paths"):
        validate_network_allowlist(["pypi.org/simple"])


def test_network_allowlist_accepts_normal_domain_as_config_only(tmp_path: Path) -> None:
    config = SandboxConfig(
        enabled=True,
        backend="docker",
        network_access=True,
        network_allowlist=["pypi.org", "files.pythonhosted.org"],
    ).normalized()
    executor = DockerSandboxExecutor(network_access=True, network_allowlist=config.network_allowlist)
    command = executor.build_command(SandboxRunRequest(command="echo ok", cwd=tmp_path, timeout_seconds=5))

    assert config.network_allowlist == ["pypi.org", "files.pythonhosted.org"]
    assert executor.network_policy_mode == "allowlist_config_only"
    assert executor.network_enforced is False
    assert command[command.index("--network") + 1] == "none"


def test_resolver_uses_docker_when_config_backend_docker() -> None:
    executor = get_sandbox_executor(config=SandboxConfig(enabled=True, backend="docker", image="my-project-dev:latest"))

    assert isinstance(executor, DockerSandboxExecutor)
    assert executor.image == "my-project-dev:latest"


def test_resolver_explicit_backend_overrides_config() -> None:
    executor = get_sandbox_executor(backend="local", config=SandboxConfig(enabled=True, backend="docker"))

    assert isinstance(executor, LocalSandboxExecutor)


def test_env_sandbox_backend_docker_is_parsed() -> None:
    config = sandbox_config_from_env(
        {
            "PP_ECHO_SANDBOX_BACKEND": "docker",
            "PP_ECHO_SANDBOX_IMAGE": "my-project-dev:latest",
            "PP_ECHO_SANDBOX_NETWORK": "1",
            "PP_ECHO_SANDBOX_NETWORK_DANGEROUSLY_ALLOW_ALL": "1",
            "PP_ECHO_SANDBOX_MEMORY": "768m",
            "PP_ECHO_SANDBOX_CPUS": "2",
        }
    )

    assert config.enabled is True
    assert config.backend == "docker"
    assert config.image == "my-project-dev:latest"
    assert config.network_access is True
    assert config.network_dangerously_allow_all is True
    assert config.memory == "768m"
    assert config.cpus == "2"


def test_env_parses_network_allowlist() -> None:
    config = sandbox_config_from_env(
        {
            "PP_ECHO_SANDBOX_BACKEND": "docker",
            "PP_ECHO_SANDBOX_NETWORK": "1",
            "PP_ECHO_SANDBOX_NETWORK_ALLOWLIST": "pypi.org,files.pythonhosted.org",
        }
    )

    assert config.network_access is True
    assert config.network_allowlist == ["pypi.org", "files.pythonhosted.org"]
    assert config.network_dangerously_allow_all is False


def test_env_parses_network_dangerously_allow_all() -> None:
    config = sandbox_config_from_env(
        {
            "PP_ECHO_SANDBOX_BACKEND": "docker",
            "PP_ECHO_SANDBOX_NETWORK": "1",
            "PP_ECHO_SANDBOX_NETWORK_DANGEROUSLY_ALLOW_ALL": "1",
        }
    )

    assert config.network_access is True
    assert config.network_dangerously_allow_all is True


def test_cli_sandbox_backend_overrides_env(monkeypatch) -> None:
    from pp_agent.sandbox.config import apply_sandbox_cli_overrides

    monkeypatch.setenv("PP_ECHO_SANDBOX_BACKEND", "docker")
    apply_sandbox_cli_overrides(backend="local")

    assert sandbox_config_from_env().backend == "local"
    assert sandbox_config_from_env().enabled is False


def test_cli_parses_network_allowlist_if_cli_supported(monkeypatch) -> None:
    from pp_agent.sandbox.config import apply_sandbox_cli_overrides

    monkeypatch.delenv("PP_ECHO_SANDBOX_NETWORK_ALLOWLIST", raising=False)
    apply_sandbox_cli_overrides(
        backend="docker",
        network_access=True,
        network_allowlist="pypi.org,files.pythonhosted.org",
    )

    assert sandbox_config_from_env().network_allowlist == ["pypi.org", "files.pythonhosted.org"]


def test_shell_uses_configured_sandbox_executor(monkeypatch, tmp_path: Path) -> None:
    from pp_agent.app.bootstrap import create_tool_registry

    monkeypatch.setenv("PP_ECHO_SANDBOX_BACKEND", "docker")
    registry = create_tool_registry(tmp_path)

    assert isinstance(registry.sandbox_executor, DockerSandboxExecutor)
    assert registry._get_tool("run_shell").sandbox_executor is registry.sandbox_executor
    assert registry._get_tool("approve_pending_action").sandbox_executor is registry.sandbox_executor


def test_tool_registry_uses_injected_sandbox_executor(tmp_path: Path) -> None:
    fake = RecordingSandboxExecutor(
        SandboxRunResult(
            stdout="",
            stderr="",
            returncode=0,
            timed_out=False,
            backend="fake",
            sandbox_mode="test",
            network_access=False,
            writable_roots=[str(tmp_path)],
        )
    )

    registry = ToolRegistry(tmp_path, sandbox_executor=fake)

    assert registry.sandbox_executor is fake
    assert registry._get_tool("run_shell").sandbox_executor is fake
    assert registry._get_tool("approve_pending_action").sandbox_executor is fake


def test_local_backend_is_reported_as_non_secure_or_compat() -> None:
    result = SandboxRunResult(
        stdout="",
        stderr="",
        returncode=0,
        timed_out=False,
        backend="local",
        sandbox_mode="danger-full-access",
        network_access=True,
        writable_roots=["."],
    )

    from pp_agent.tools.shell_tool import sandbox_result_details

    assert sandbox_result_details(result)["sandbox_isolation"] == "none-local-compat"


def test_sandbox_base_dockerfile_exists() -> None:
    assert Path("docker/sandbox-base/Dockerfile").is_file()


def test_sandbox_base_dockerfile_includes_core_tools() -> None:
    dockerfile = Path("docker/sandbox-base/Dockerfile").read_text(encoding="utf-8")

    assert "FROM debian:bookworm-slim" in dockerfile or "FROM ubuntu:22.04" in dockerfile
    for package in (
        "bash",
        "git",
        "ca-certificates",
        "coreutils",
        "findutils",
        "grep",
        "sed",
        "gawk",
        "diffutils",
        "patch",
        "tar",
        "gzip",
        "xz-utils",
    ):
        assert package in dockerfile
    assert "WORKDIR /workspace" in dockerfile
    assert "rm -rf /var/lib/apt/lists/*" in dockerfile


def test_sandbox_base_dockerfile_does_not_copy_project_or_secrets() -> None:
    dockerfile = Path("docker/sandbox-base/Dockerfile").read_text(encoding="utf-8").lower()

    assert "copy " not in dockerfile
    assert "add " not in dockerfile
    assert "secret" not in dockerfile
    assert ".env" not in dockerfile
    assert "token" not in dockerfile


def test_docs_include_base_image_build_command() -> None:
    docs = Path("docs/sandbox.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    command = "docker build -t pp-echo-sandbox:base -f docker/sandbox-base/Dockerfile ."
    assert command in docs
    assert command in readme


def test_docs_explain_project_specific_image_for_multilang_projects() -> None:
    docs = Path("docs/sandbox.md").read_text(encoding="utf-8")

    assert "my-project-dev:latest" in docs
    assert "project owns the language toolchain" in docs
    assert "multi-language development image" in docs


def test_docs_do_not_claim_language_auto_detection() -> None:
    docs = Path("docs/sandbox.md").read_text(encoding="utf-8")

    assert "does not auto-detect" in docs
    assert "does not map languages to images" in docs
    assert "Python is not assumed and is not the default" in docs


def test_docs_do_not_claim_full_network_allowlist_enforcement() -> None:
    docs = Path("docs/sandbox.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "`network_allowlist` is a policy configuration entry point, not full domain-level egress enforcement" in docs
    assert "does not prevent DNS rebinding" in docs
    assert "network_enforced=false" in docs
    assert "不代表完整域名级 allowlist enforcement 已实现" in readme


def test_docs_warn_about_dangerously_allow_all() -> None:
    docs = Path("docs/sandbox.md").read_text(encoding="utf-8")

    assert "dangerously_allow_all" in docs
    assert "--network bridge" in docs
    assert "full network egress risk" in docs


def _patch(from_path: str, to_path: str, before: list[str], after: list[str]) -> str:
    """Build a small unified diff for patch candidate tests."""

    import difflib

    return "".join(difflib.unified_diff(before, after, fromfile=from_path, tofile=to_path))


def _stage_patch_candidate(tmp_path: Path, *, patch: str, changed_files: list[dict], patch_summary: str = "candidate") -> str:
    """Stage an apply_patch_candidate action directly for approval tests."""

    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    patch_digest = content_digest(patch)
    effect = build_patch_candidate_effect(
        tool_name="apply_patch_candidate",
        permission_domain=PermissionDomain.EDIT,
        patch=patch,
        changed_files=changed_files,
        patch_summary=patch_summary,
        source_shell_command_digest="source-digest",
        sandbox_backend="docker",
        sandbox_mode="docker",
    )
    payload = store.stage(
        action_type="apply_patch_candidate",
        details={
            "patch": patch,
            "changed_files": changed_files,
            "patch_summary": patch_summary,
            "patch_digest": patch_digest,
            "source_shell_command_digest": "source-digest",
            "source_shell_action_token": "shell-token",
            "sandbox_backend": "docker",
            "sandbox_mode": "docker",
            "patch_truncated": False,
        },
        effect=effect,
    )
    return payload["token"]


def _structured(path: str, change_type: str, *, old: bytes | None, new: str | None, binary: bool = False, truncated: bool = False) -> dict:
    """Build one structured change test payload."""

    new_bytes = new.encode("utf-8") if new is not None else None
    return {
        "path": path,
        "change_type": change_type,
        "old_digest": bytes_digest(old) if old is not None else None,
        "new_digest": bytes_digest(new_bytes) if new_bytes is not None else None,
        "content_text": new,
        "content_encoding": "utf-8",
        "binary": binary,
        "truncated": truncated,
        "size_bytes": len(new_bytes) if new_bytes is not None else (len(old) if old is not None else 0),
    }


def _stage_structured_candidate(
    tmp_path: Path,
    *,
    structured_changes: list[dict],
    changed_files: list[dict],
    patch: str = "--- a/ignored.txt\n+++ b/ignored.txt\n@@ -0,0 +1 @@\n+ignored\n",
    structured_changes_truncated: bool = False,
) -> str:
    """Stage an apply_patch_candidate action with structured changes."""

    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    patch_digest = content_digest(patch)
    structured_digest = structured_changes_digest(structured_changes)
    effect = build_patch_candidate_effect(
        tool_name="apply_patch_candidate",
        permission_domain=PermissionDomain.EDIT,
        patch=patch,
        changed_files=changed_files,
        patch_summary="structured candidate",
        source_shell_command_digest="source-digest",
        sandbox_backend="docker",
        sandbox_mode="docker",
        structured_changes=structured_changes,
        structured_changes_digest=structured_digest,
        structured_changes_truncated=structured_changes_truncated,
    )
    payload = store.stage(
        action_type="apply_patch_candidate",
        details={
            "patch": patch,
            "changed_files": changed_files,
            "patch_summary": "structured candidate",
            "patch_digest": patch_digest,
            "source_shell_command_digest": "source-digest",
            "source_shell_action_token": "shell-token",
            "sandbox_backend": "docker",
            "sandbox_mode": "docker",
            "patch_truncated": False,
            "structured_changes": structured_changes,
            "structured_changes_digest": structured_digest,
            "structured_changes_truncated": structured_changes_truncated,
        },
        effect=effect,
    )
    return payload["token"]


def test_local_sandbox_executor_executes_simple_command(tmp_path: Path) -> None:
    executor = LocalSandboxExecutor()

    result = executor.run(SandboxRunRequest(command="Write-Output sandbox-ok", cwd=tmp_path, timeout_seconds=5))

    assert result.returncode == 0
    assert result.timed_out is False
    assert "sandbox-ok" in result.stdout
    assert result.backend == "local"
    assert result.sandbox_mode == "danger-full-access"
    assert result.network_access is True
    assert result.writable_roots == [str(tmp_path)]


def test_local_sandbox_executor_timeout_is_reported(tmp_path: Path) -> None:
    executor = LocalSandboxExecutor()

    result = executor.run(SandboxRunRequest(command="Start-Sleep -Seconds 2", cwd=tmp_path, timeout_seconds=1))

    assert result.returncode == 124
    assert result.timed_out is True
    assert result.backend == "local"


def test_local_executor_is_documented_as_non_sandbox_or_unsafe_backend() -> None:
    docs = Path("docs/sandbox.md").read_text(encoding="utf-8")

    assert "LocalSandboxExecutor" in docs
    assert "not a security sandbox" in docs
    assert "default backend remains `local`" in docs


def test_sandbox_resolver_defaults_to_local_backend() -> None:
    executor = get_sandbox_executor()

    assert isinstance(executor, LocalSandboxExecutor)


def test_sandbox_resolver_can_select_local_backend() -> None:
    executor = get_sandbox_executor(backend="local")

    assert isinstance(executor, LocalSandboxExecutor)


def test_sandbox_resolver_can_select_docker_backend() -> None:
    executor = get_sandbox_executor(backend="docker", image="my-project-dev:latest", memory="256m", cpus="0.5")

    assert isinstance(executor, DockerSandboxExecutor)
    assert executor.image == "my-project-dev:latest"
    assert executor.memory == "256m"
    assert executor.cpus == "0.5"


def test_docker_executor_default_image_is_pp_echo_sandbox_base() -> None:
    assert DEFAULT_DOCKER_SANDBOX_IMAGE == "pp-echo-sandbox:base"
    assert DockerSandboxExecutor().image == "pp-echo-sandbox:base"


def test_docker_sandbox_command_uses_locked_down_flags(tmp_path: Path) -> None:
    executor = DockerSandboxExecutor(image="my-project-dev:latest")

    command = executor.build_command(SandboxRunRequest(command="python --version", cwd=tmp_path, timeout_seconds=5))

    assert command[:3] == ["docker", "run", "--rm"]
    assert "--network" in command
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert "--cap-drop" in command
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert "--security-opt" in command
    assert command[command.index("--security-opt") + 1] == "no-new-privileges"
    assert "--memory" in command
    assert command[command.index("--memory") + 1] == "512m"
    assert "--cpus" in command
    assert command[command.index("--cpus") + 1] == "1"
    assert "-v" in command
    assert command[command.index("-v") + 1] == f"{tmp_path}:/workspace:rw"
    assert command[command.index("-w") + 1] == "/workspace"
    assert command[-4:] == ["my-project-dev:latest", "bash", "-lc", "python --version"]


def test_docker_command_uses_network_none_by_default(tmp_path: Path) -> None:
    command = DockerSandboxExecutor().build_command(SandboxRunRequest(command="echo ok", cwd=tmp_path, timeout_seconds=5))

    assert command[command.index("--network") + 1] == "none"


def test_docker_command_uses_bridge_only_for_dangerously_allow_all(tmp_path: Path) -> None:
    executor = DockerSandboxExecutor(network_access=True, network_dangerously_allow_all=True)
    command = executor.build_command(SandboxRunRequest(command="echo ok", cwd=tmp_path, timeout_seconds=5))

    assert command[command.index("--network") + 1] == "bridge"
    assert executor.network_policy_mode == "dangerously_allow_all"
    assert executor.network_enforced is True


def test_allowlist_config_without_enforcement_does_not_open_bridge_network(tmp_path: Path) -> None:
    executor = DockerSandboxExecutor(network_access=True, network_allowlist=["pypi.org"])
    command = executor.build_command(SandboxRunRequest(command="echo ok", cwd=tmp_path, timeout_seconds=5))

    assert command[command.index("--network") + 1] == "none"
    assert executor.network_policy_mode == "allowlist_config_only"
    assert executor.network_enforced is False


def test_network_policy_details_mark_allowlist_as_not_enforced(monkeypatch, tmp_path: Path) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called for unenforced allowlist mode")

    monkeypatch.setattr("pp_agent.sandbox.docker.subprocess.run", fail_if_called)
    executor = DockerSandboxExecutor(network_access=True, network_allowlist=["pypi.org"])

    with pytest.raises(RuntimeError, match="network allowlist enforcement is not implemented yet"):
        executor.run(SandboxRunRequest(command="echo ok", cwd=tmp_path, timeout_seconds=5))

    result = SandboxRunResult(
        stdout="",
        stderr="",
        returncode=1,
        timed_out=False,
        backend="docker",
        sandbox_mode="docker",
        network_access=True,
        network_allowlist=["pypi.org"],
        network_policy_mode="allowlist_config_only",
        network_enforced=False,
        writable_roots=[str(tmp_path)],
    )

    from pp_agent.tools.shell_tool import sandbox_result_details

    details = sandbox_result_details(result)
    assert details["network_policy_mode"] == "allowlist_config_only"
    assert details["network_enforced"] is False
    assert details["network_allowlist"] == ["pypi.org"]


def test_docker_sandbox_run_uses_subprocess_without_real_docker(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        if command[:2] == ["docker.exe", "info"] or command[:3] == ["docker.exe", "image", "inspect"]:
            return SimpleNamespace(stdout="ok\n", stderr="", returncode=0)
        return SimpleNamespace(stdout="docker-ok\n", stderr="", returncode=0)

    monkeypatch.setattr("pp_agent.sandbox.docker.subprocess.run", fake_run)
    monkeypatch.setattr("pp_agent.sandbox.preflight.shutil.which", lambda name: "docker.exe")

    result = DockerSandboxExecutor(image="my-project-dev:latest").run(
        SandboxRunRequest(command="echo docker-ok", cwd=tmp_path, timeout_seconds=9)
    )

    assert result.stdout == "docker-ok\n"
    assert result.returncode == 0
    assert result.timed_out is False
    assert result.backend == "docker"
    assert result.sandbox_mode == "docker"
    assert result.network_access is False
    assert result.writable_roots == [str(tmp_path)]
    assert seen["command"][-4:] == ["my-project-dev:latest", "bash", "-lc", "echo docker-ok"]
    assert seen["kwargs"]["timeout"] == 9
    assert seen["kwargs"]["capture_output"] is True
    assert seen["kwargs"]["text"] is True
    assert seen["kwargs"]["check"] is False


def test_docker_preflight_reports_missing_docker(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("pp_agent.sandbox.preflight.shutil.which", lambda name: None)

    status = docker_preflight_status(image=DEFAULT_DOCKER_SANDBOX_IMAGE, workspace=tmp_path)

    assert status.ok is False
    assert status.backend == "docker"
    assert status.docker_found is False
    assert status.daemon_available is None
    assert status.image_available is None
    assert "docker executable was not found" in status.message
    assert status.install_url
    assert "docker build -t pp-echo-sandbox:base" in (status.build_command or "")


def test_docker_preflight_error_details_are_structured(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("pp_agent.sandbox.preflight.shutil.which", lambda name: None)
    status = docker_preflight_status(image=DEFAULT_DOCKER_SANDBOX_IMAGE, workspace=tmp_path)

    error = DockerSandboxPreflightError(status)

    assert error.details["docker_preflight"]["docker_found"] is False
    assert error.details["sandbox_preflight"]["backend"] == "docker"


def test_shell_approval_failure_includes_docker_preflight_details(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("pp_agent.sandbox.preflight.shutil.which", lambda name: None)
    registry = ToolRegistry(tmp_path, sandbox_executor=DockerSandboxExecutor())
    staged = registry.execute("run_shell", {"command": "echo hi"})

    result = registry.host_execute("approve_pending_action", {"token": staged.details["token"]})

    assert result.is_error is True
    assert "Docker sandbox backend requested" in result.content
    assert result.details["docker_preflight"]["docker_found"] is False
    assert result.details["sandbox_preflight"]["backend"] == "docker"


def test_docker_sandbox_skips_protected_paths_when_copying_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sandbox = tmp_path / "sandbox"
    workspace.mkdir()
    (workspace / "subdir").mkdir()
    (workspace / "safe.txt").write_text("safe", encoding="utf-8")
    (workspace / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (workspace / ".env.local").write_text("TOKEN=local", encoding="utf-8")
    (workspace / "subdir" / ".env").write_text("TOKEN=nested", encoding="utf-8")
    (workspace / "secret.pem").write_text("pem", encoding="utf-8")
    (workspace / "secret.key").write_text("key", encoding="utf-8")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "config").write_text("git", encoding="utf-8")
    (workspace / ".pp-agent").mkdir()
    (workspace / ".pp-agent" / "state.json").write_text("{}", encoding="utf-8")

    copied = DockerSandboxExecutor().prepare_workspace(workspace, sandbox)

    assert copied == {"safe.txt"}
    assert (sandbox / "safe.txt").exists()
    assert not (sandbox / ".env").exists()
    assert not (sandbox / ".env.local").exists()
    assert not (sandbox / "subdir" / ".env").exists()
    assert not (sandbox / "secret.pem").exists()
    assert not (sandbox / "secret.key").exists()
    assert not (sandbox / ".git").exists()
    assert not (sandbox / ".pp-agent").exists()


def test_docker_sandbox_detects_added_modified_deleted_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sandbox = tmp_path / "sandbox"
    workspace.mkdir()
    (workspace / "modified.txt").write_text("before\n", encoding="utf-8")
    (workspace / "deleted.txt").write_text("delete me\n", encoding="utf-8")
    executor = DockerSandboxExecutor()
    copied = executor.prepare_workspace(workspace, sandbox)
    (sandbox / "added.txt").write_text("created\n", encoding="utf-8")
    (sandbox / "modified.txt").write_text("after\n", encoding="utf-8")
    (sandbox / "deleted.txt").unlink()

    diff = executor.collect_workspace_diff(source_workspace=workspace, sandbox_workspace=sandbox, copied_files=copied)

    statuses = {item["path"]: item["status"] for item in diff["changed_files"]}
    assert statuses == {"added.txt": "added", "deleted.txt": "deleted", "modified.txt": "modified"}
    assert "1 added" in diff["patch_summary"]
    assert "1 modified" in diff["patch_summary"]
    assert "1 deleted" in diff["patch_summary"]
    assert "created" in diff["patch"]
    assert "-before" in diff["patch"]
    assert "+after" in diff["patch"]
    assert "-delete me" in diff["patch"]


def test_docker_result_includes_structured_changes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sandbox = tmp_path / "sandbox"
    workspace.mkdir()
    (workspace / "modified.txt").write_bytes(b"before\n")
    executor = DockerSandboxExecutor()
    copied = executor.prepare_workspace(workspace, sandbox)
    (sandbox / "added.txt").write_bytes(b"created\n")
    (sandbox / "modified.txt").write_bytes(b"after\n")

    diff = executor.collect_workspace_diff(source_workspace=workspace, sandbox_workspace=sandbox, copied_files=copied)

    changes = {item["path"]: item for item in diff["structured_changes"]}
    assert changes["added.txt"]["change_type"] == "added"
    assert changes["added.txt"]["old_digest"] is None
    assert changes["added.txt"]["content_text"] == "created\n"
    assert changes["modified.txt"]["change_type"] == "modified"
    assert changes["modified.txt"]["old_digest"] == bytes_digest(b"before\n")
    assert changes["modified.txt"]["new_digest"] == bytes_digest(b"after\n")
    assert diff["structured_changes_digest"] == structured_changes_digest(diff["structured_changes"])
    assert diff["structured_changes_truncated"] is False


def test_docker_sandbox_does_not_report_protected_path_changes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sandbox = tmp_path / "sandbox"
    workspace.mkdir()
    (sandbox / "subdir").mkdir(parents=True, exist_ok=True)
    executor = DockerSandboxExecutor()
    copied = executor.prepare_workspace(workspace, sandbox)
    (sandbox / ".env").write_text("TOKEN=changed", encoding="utf-8")
    (sandbox / ".ENV.LOCAL").write_text("TOKEN=changed-local", encoding="utf-8")
    (sandbox / "subdir" / ".env").write_text("TOKEN=changed-nested", encoding="utf-8")
    (sandbox / "private.pem").write_text("changed", encoding="utf-8")
    (sandbox / "PRIVATE.KEY").write_text("changed", encoding="utf-8")
    (sandbox / ".git").mkdir()
    (sandbox / ".git" / "config").write_text("changed", encoding="utf-8")

    diff = executor.collect_workspace_diff(source_workspace=workspace, sandbox_workspace=sandbox, copied_files=copied)

    assert diff["changed_files"] == []
    assert diff["patch"] == ""
    assert diff["patch_summary"] == "0 added, 0 modified, 0 deleted"
    assert diff["patch_truncated"] is False


def test_docker_sandbox_does_not_include_protected_content_in_patch(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sandbox = tmp_path / "sandbox"
    workspace.mkdir()
    (workspace / "visible.txt").write_text("old\n", encoding="utf-8")
    executor = DockerSandboxExecutor()
    copied = executor.prepare_workspace(workspace, sandbox)
    (sandbox / "visible.txt").write_text("new\n", encoding="utf-8")
    (sandbox / ".env").write_text("SUPER_SECRET_TOKEN", encoding="utf-8")
    (sandbox / "nested").mkdir()
    (sandbox / "nested" / ".." / ".env.local").write_text("LOCAL_SECRET", encoding="utf-8")
    (sandbox / "private.pem").write_text("PEM_SECRET", encoding="utf-8")

    diff = executor.collect_workspace_diff(source_workspace=workspace, sandbox_workspace=sandbox, copied_files=copied)

    assert [item["path"] for item in diff["changed_files"]] == ["visible.txt"]
    assert "SUPER_SECRET_TOKEN" not in diff["patch"]
    assert "LOCAL_SECRET" not in diff["patch"]
    assert "PEM_SECRET" not in diff["patch"]
    assert ".env" not in diff["patch"]
    assert "private.pem" not in diff["patch"]


def test_docker_sandbox_truncates_large_patch(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sandbox = tmp_path / "sandbox"
    workspace.mkdir()
    executor = DockerSandboxExecutor(max_diff_file_bytes=8, max_patch_bytes=128)
    copied = executor.prepare_workspace(workspace, sandbox)
    (sandbox / "large.txt").write_text("0123456789abcdef", encoding="utf-8")

    diff = executor.collect_workspace_diff(source_workspace=workspace, sandbox_workspace=sandbox, copied_files=copied)

    assert diff["changed_files"][0]["path"] == "large.txt"
    assert diff["changed_files"][0]["truncated"] is True
    assert diff["patch"] == ""
    assert diff["patch_truncated"] is True
    assert "patch truncated" in diff["patch_summary"]


def test_docker_sandbox_symlink_cannot_expose_protected_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sandbox = tmp_path / "sandbox"
    workspace.mkdir()
    secret = workspace / ".env"
    secret.write_text("TOKEN=secret", encoding="utf-8")
    link = workspace / "env-link"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        return

    copied = DockerSandboxExecutor().prepare_workspace(workspace, sandbox)

    assert "env-link" not in copied
    assert not (sandbox / "env-link").exists()


def test_docker_sandbox_windows_separators_do_not_bypass_protected_matching(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    nested = workspace / "subdir" / ".." / ".env"

    assert DockerSandboxExecutor._is_protected(workspace, nested)
    assert DockerSandboxExecutor._is_protected(workspace, Path(str(workspace / "subdir" / ".." / ".ENV.LOCAL").replace("/", "\\")))
    assert DockerSandboxExecutor._is_protected(workspace, Path(str(workspace / "private.PEM").replace("/", "\\")))


def test_approve_pending_action_runs_shell_through_executor(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("run_shell", {"command": "Write-Output routed", "timeout_seconds": 7})
    fake = RecordingSandboxExecutor(
        SandboxRunResult(
            stdout="routed\n",
            stderr="",
            returncode=0,
            timed_out=False,
            backend="fake",
            sandbox_mode="local",
            network_access=True,
            writable_roots=[str(tmp_path)],
        )
    )

    result = ApprovePendingActionTool(tmp_path, registry.policy_evaluator, tool_registry=registry, sandbox_executor=fake).execute(
        {"token": staged.details["token"]}
    )

    assert result.content == "routed"
    assert result.details["returncode"] == 0
    assert len(fake.requests) == 1
    assert fake.requests[0].command == "Write-Output routed"
    assert fake.requests[0].cwd == tmp_path.resolve()
    assert fake.requests[0].timeout_seconds == 7


def test_shell_approval_failure_still_records_execution_failed(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("run_shell", {"command": "Write-Error boom; exit 1", "timeout_seconds": 5})
    fake = RecordingSandboxExecutor(
        SandboxRunResult(
            stdout="",
            stderr="boom\n",
            returncode=1,
            timed_out=False,
            backend="fake",
            sandbox_mode="local",
            network_access=True,
            writable_roots=[str(tmp_path)],
        )
    )

    result = ApprovePendingActionTool(tmp_path, registry.policy_evaluator, tool_registry=registry, sandbox_executor=fake).execute(
        {"token": staged.details["token"]}
    )

    assert result.is_error is True
    assert result.details["failure_kind"] == "execution_failed"
    assert result.details["command_failed"] is True
    assert result.details["returncode"] == 1
    assert result.details["stderr"] == "boom"


def test_shell_details_include_patch_candidate_fields(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("run_shell", {"command": "Write-Output patch", "timeout_seconds": 7})
    fake = RecordingSandboxExecutor(
        SandboxRunResult(
            stdout="patch\n",
            stderr="",
            returncode=0,
            timed_out=False,
            backend="docker",
            sandbox_mode="docker",
            network_access=False,
            writable_roots=[str(tmp_path)],
            changed_files=[{"path": "notes.txt", "status": "modified", "before_size": 3, "after_size": 4, "before_digest": "a", "after_digest": "b", "truncated": False}],
            patch_summary="0 added, 1 modified, 0 deleted",
            patch="--- a/notes.txt\n+++ b/notes.txt\n",
            patch_truncated=False,
            structured_changes=[_structured("notes.txt", "modified", old=b"old", new="new\n")],
            structured_changes_digest=structured_changes_digest([_structured("notes.txt", "modified", old=b"old", new="new\n")]),
            structured_changes_truncated=False,
        )
    )

    result = ApprovePendingActionTool(tmp_path, registry.policy_evaluator, tool_registry=registry, sandbox_executor=fake).execute(
        {"token": staged.details["token"]}
    )

    assert result.details["changed_files"] == fake.result.changed_files
    assert result.details["patch_summary"] == "0 added, 1 modified, 0 deleted"
    assert result.details["patch"] == "--- a/notes.txt\n+++ b/notes.txt\n"
    assert result.details["patch_truncated"] is False
    assert result.details["structured_changes_count"] == 1
    assert result.details["structured_changes_truncated"] is False


def test_shell_details_include_patch_truncated_marker(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("run_shell", {"command": "Write-Output patch", "timeout_seconds": 7})
    fake = RecordingSandboxExecutor(
        SandboxRunResult(
            stdout="patch\n",
            stderr="",
            returncode=0,
            timed_out=False,
            backend="docker",
            sandbox_mode="docker",
            network_access=False,
            writable_roots=[str(tmp_path)],
            changed_files=[{"path": "large.txt", "status": "added", "before_size": 0, "after_size": 999, "before_digest": "", "after_digest": "", "truncated": True}],
            patch_summary="1 added, 0 modified, 0 deleted, patch truncated",
            patch="",
            patch_truncated=True,
        )
    )

    result = ApprovePendingActionTool(tmp_path, registry.policy_evaluator, tool_registry=registry, sandbox_executor=fake).execute(
        {"token": staged.details["token"]}
    )

    assert result.details["patch_truncated"] is True
    assert result.details["patch"] == ""


def test_shell_docker_result_stages_patch_candidate_when_files_changed(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("run_shell", {"command": "Write-Output patch", "timeout_seconds": 7})
    patch = _patch("a/notes.txt", "b/notes.txt", [], ["hello\n"])
    fake = RecordingSandboxExecutor(
        SandboxRunResult(
            stdout="patch\n",
            stderr="",
            returncode=0,
            timed_out=False,
            backend="docker",
            sandbox_mode="docker",
            network_access=False,
            writable_roots=[str(tmp_path)],
            changed_files=[{"path": "notes.txt", "status": "added", "before_size": 0, "after_size": 6, "before_digest": "", "after_digest": "x", "truncated": False}],
            patch_summary="1 added, 0 modified, 0 deleted",
            patch=patch,
            patch_truncated=False,
        )
    )

    result = ApprovePendingActionTool(tmp_path, registry.policy_evaluator, tool_registry=registry, sandbox_executor=fake).execute(
        {"token": staged.details["token"]}
    )

    candidate = result.details["patch_candidate"]
    assert candidate["staged"] is True
    assert candidate["token"]
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").load(candidate["token"])
    assert pending["action_type"] == "apply_patch_candidate"
    assert pending["effect"]["effect_type"] == "patch_apply"
    assert "Approve patch token" in result.content
    assert not (tmp_path / "notes.txt").exists()


def test_shell_docker_result_does_not_stage_patch_candidate_when_no_changes(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("run_shell", {"command": "Write-Output noop", "timeout_seconds": 7})
    fake = RecordingSandboxExecutor(
        SandboxRunResult(
            stdout="noop\n",
            stderr="",
            returncode=0,
            timed_out=False,
            backend="docker",
            sandbox_mode="docker",
            network_access=False,
            writable_roots=[str(tmp_path)],
            changed_files=[],
            patch_summary="0 added, 0 modified, 0 deleted",
            patch="",
            patch_truncated=False,
        )
    )

    result = ApprovePendingActionTool(tmp_path, registry.policy_evaluator, tool_registry=registry, sandbox_executor=fake).execute(
        {"token": staged.details["token"]}
    )

    assert result.details["patch_candidate"]["staged"] is False
    assert result.details["patch_candidate"]["reason"] == "no changed files"
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert not any(item["action_type"] == "apply_patch_candidate" for item in pending)


def test_truncated_patch_is_not_applyable(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("run_shell", {"command": "Write-Output patch", "timeout_seconds": 7})
    fake = RecordingSandboxExecutor(
        SandboxRunResult(
            stdout="patch\n",
            stderr="",
            returncode=0,
            timed_out=False,
            backend="docker",
            sandbox_mode="docker",
            network_access=False,
            writable_roots=[str(tmp_path)],
            changed_files=[{"path": "large.txt", "status": "added", "before_size": 0, "after_size": 999, "before_digest": "", "after_digest": "", "truncated": True}],
            patch_summary="1 added, 0 modified, 0 deleted, patch truncated",
            patch="",
            patch_truncated=True,
        )
    )

    result = ApprovePendingActionTool(tmp_path, registry.policy_evaluator, tool_registry=registry, sandbox_executor=fake).execute(
        {"token": staged.details["token"]}
    )

    assert result.details["patch_candidate"]["staged"] is False
    assert result.details["patch_candidate"]["patch_truncated"] is True
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert not any(item["action_type"] == "apply_patch_candidate" for item in pending)


def test_structured_changes_truncated_does_not_stage_apply_action(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged = registry.execute("run_shell", {"command": "Write-Output patch", "timeout_seconds": 7})
    changes = [_structured("large.txt", "added", old=None, new="large\n", truncated=True)]
    fake = RecordingSandboxExecutor(
        SandboxRunResult(
            stdout="patch\n",
            stderr="",
            returncode=0,
            timed_out=False,
            backend="docker",
            sandbox_mode="docker",
            network_access=False,
            writable_roots=[str(tmp_path)],
            changed_files=[{"path": "large.txt", "status": "added", "before_size": 0, "after_size": 6, "before_digest": "", "after_digest": "", "truncated": True}],
            patch_summary="1 added, 0 modified, 0 deleted",
            patch="--- a/large.txt\n+++ b/large.txt\n@@ -0,0 +1 @@\n+large\n",
            patch_truncated=False,
            structured_changes=changes,
            structured_changes_digest=structured_changes_digest(changes),
            structured_changes_truncated=True,
        )
    )

    result = ApprovePendingActionTool(tmp_path, registry.policy_evaluator, tool_registry=registry, sandbox_executor=fake).execute(
        {"token": staged.details["token"]}
    )

    assert result.details["patch_candidate"]["staged"] is False
    assert result.details["patch_candidate"]["structured_changes_truncated"] is True
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert not any(item["action_type"] == "apply_patch_candidate" for item in pending)


def test_apply_patch_candidate_requires_approval(tmp_path: Path) -> None:
    patch = _patch("a/new.txt", "b/new.txt", [], ["hello\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "new.txt", "status": "added", "before_size": 0, "after_size": 6, "before_digest": "", "after_digest": "x", "truncated": False}],
    )

    assert not (tmp_path / "new.txt").exists()
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").load(token)
    assert pending["lifecycle"]["state"] == "staged_not_granted"


def test_structured_changes_digest_is_bound_to_payload(tmp_path: Path) -> None:
    changes = [_structured("new.txt", "added", old=None, new="hello\n")]
    token = _stage_structured_candidate(
        tmp_path,
        structured_changes=changes,
        changed_files=[{"path": "new.txt", "status": "added", "before_size": 0, "after_size": 6, "before_digest": "", "after_digest": bytes_digest(b"hello\n"), "truncated": False}],
    )
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    payload = store.attach_approval_grant(token)
    payload["details"]["structured_changes"][0]["content_text"] = "tampered\n"
    store.save(token, payload)

    with pytest.raises(ValueError, match="structured changes digest changed|payload digest changed"):
        ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})


def test_apply_patch_candidate_rejects_modified_payload_digest(tmp_path: Path) -> None:
    patch = _patch("a/new.txt", "b/new.txt", [], ["hello\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "new.txt", "status": "added", "before_size": 0, "after_size": 6, "before_digest": "", "after_digest": "x", "truncated": False}],
    )
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    payload = store.attach_approval_grant(token)
    payload["details"]["patch"] = payload["details"]["patch"].replace("hello", "tampered")
    store.save(token, payload)

    with pytest.raises(ValueError, match="patch digest changed|payload digest changed"):
        ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})


def test_apply_patch_candidate_applies_added_file(tmp_path: Path) -> None:
    patch = _patch("a/added.txt", "b/added.txt", [], ["hello\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "added.txt", "status": "added", "before_size": 0, "after_size": 6, "before_digest": "", "after_digest": "x", "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert (tmp_path / "added.txt").read_text(encoding="utf-8") == "hello\n"
    assert result.details["applied"] is True
    assert result.details["apply_backend"] == "internal_unified_diff"


def test_apply_structured_added_file(tmp_path: Path) -> None:
    changes = [_structured("added.txt", "added", old=None, new="hello\n")]
    token = _stage_structured_candidate(
        tmp_path,
        structured_changes=changes,
        changed_files=[{"path": "added.txt", "status": "added", "before_size": 0, "after_size": 6, "before_digest": "", "after_digest": bytes_digest(b"hello\n"), "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert (tmp_path / "added.txt").read_text(encoding="utf-8") == "hello\n"
    assert result.details["apply_backend"] == "structured_changes"
    assert result.details["structured_changes_digest"] == structured_changes_digest(changes)


def test_apply_structured_modified_file(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_bytes(b"before\n")
    changes = [_structured("notes.txt", "modified", old=b"before\n", new="after\n")]
    token = _stage_structured_candidate(
        tmp_path,
        structured_changes=changes,
        changed_files=[{"path": "notes.txt", "status": "modified", "before_size": 7, "after_size": 6, "before_digest": bytes_digest(b"before\n"), "after_digest": bytes_digest(b"after\n"), "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "after\n"
    assert result.details["apply_backend"] == "structured_changes"


def test_apply_structured_deleted_file(tmp_path: Path) -> None:
    (tmp_path / "remove.txt").write_bytes(b"delete me\n")
    changes = [_structured("remove.txt", "deleted", old=b"delete me\n", new=None)]
    token = _stage_structured_candidate(
        tmp_path,
        structured_changes=changes,
        changed_files=[{"path": "remove.txt", "status": "deleted", "before_size": 10, "after_size": 0, "before_digest": bytes_digest(b"delete me\n"), "after_digest": "", "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.details["apply_backend"] == "structured_changes"
    assert not (tmp_path / "remove.txt").exists()


def test_apply_structured_rejects_old_digest_mismatch(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("actual\n", encoding="utf-8")
    changes = [_structured("notes.txt", "modified", old=b"expected\n", new="after\n")]
    token = _stage_structured_candidate(
        tmp_path,
        structured_changes=changes,
        changed_files=[{"path": "notes.txt", "status": "modified", "before_size": 7, "after_size": 6, "before_digest": bytes_digest(b"expected\n"), "after_digest": bytes_digest(b"after\n"), "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "actual\n"
    assert "old_digest mismatch" in result.details["reason"]


def test_apply_structured_rejects_new_digest_mismatch(tmp_path: Path) -> None:
    changes = [_structured("bad.txt", "added", old=None, new="hello\n")]
    changes[0]["new_digest"] = bytes_digest(b"other\n")
    token = _stage_structured_candidate(
        tmp_path,
        structured_changes=changes,
        changed_files=[{"path": "bad.txt", "status": "added", "before_size": 0, "after_size": 6, "before_digest": "", "after_digest": bytes_digest(b"other\n"), "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert not (tmp_path / "bad.txt").exists()
    assert "new_digest mismatch" in result.details["reason"]


def test_apply_structured_rejects_binary_change(tmp_path: Path) -> None:
    changes = [_structured("asset.bin", "added", old=None, new="", binary=True)]
    token = _stage_structured_candidate(
        tmp_path,
        structured_changes=changes,
        changed_files=[{"path": "asset.bin", "status": "added", "before_size": 0, "after_size": 1, "before_digest": "", "after_digest": "", "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert "binary or truncated" in result.details["reason"]


def test_apply_structured_rejects_truncated_change(tmp_path: Path) -> None:
    changes = [_structured("large.txt", "added", old=None, new="large\n", truncated=True)]
    token = _stage_structured_candidate(
        tmp_path,
        structured_changes=changes,
        changed_files=[{"path": "large.txt", "status": "added", "before_size": 0, "after_size": 6, "before_digest": "", "after_digest": "", "truncated": True}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert "binary or truncated" in result.details["reason"]


def test_apply_patch_candidate_prefers_structured_changes_over_unified_diff(tmp_path: Path) -> None:
    changes = [_structured("chosen.txt", "added", old=None, new="structured\n")]
    misleading_patch = _patch("a/chosen.txt", "b/chosen.txt", [], ["diff\n"])
    token = _stage_structured_candidate(
        tmp_path,
        structured_changes=changes,
        patch=misleading_patch,
        changed_files=[{"path": "chosen.txt", "status": "added", "before_size": 0, "after_size": 11, "before_digest": "", "after_digest": bytes_digest(b"structured\n"), "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert (tmp_path / "chosen.txt").read_text(encoding="utf-8") == "structured\n"
    assert result.details["apply_backend"] == "structured_changes"


def test_apply_patch_candidate_falls_back_to_unified_diff_for_legacy_payload(tmp_path: Path) -> None:
    patch = _patch("a/legacy.txt", "b/legacy.txt", [], ["legacy\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "legacy.txt", "status": "added", "before_size": 0, "after_size": 7, "before_digest": "", "after_digest": "x", "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert (tmp_path / "legacy.txt").read_text(encoding="utf-8") == "legacy\n"
    assert result.details["apply_backend"] == "internal_unified_diff"


def test_apply_structured_change_rejects_protected_path(tmp_path: Path) -> None:
    changes = [_structured(".env", "added", old=None, new="SECRET=1\n")]
    token = _stage_structured_candidate(
        tmp_path,
        structured_changes=changes,
        changed_files=[{"path": ".env", "status": "added", "before_size": 0, "after_size": 9, "before_digest": "", "after_digest": bytes_digest(b"SECRET=1\n"), "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert "protected" in result.details["reason"]
    assert not (tmp_path / ".env").exists()


def test_apply_structured_change_rejects_path_traversal(tmp_path: Path) -> None:
    changes = [_structured("../escape.txt", "added", old=None, new="escape\n")]
    token = _stage_structured_candidate(
        tmp_path,
        structured_changes=changes,
        changed_files=[{"path": "../escape.txt", "status": "added", "before_size": 0, "after_size": 7, "before_digest": "", "after_digest": bytes_digest(b"escape\n"), "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert "traversal" in result.details["reason"]
    assert not (tmp_path.parent / "escape.txt").exists()


def test_apply_structured_change_rejects_symlink_target(tmp_path: Path) -> None:
    secret = tmp_path / ".env"
    secret.write_text("SECRET=1\n", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        return
    changes = [_structured("link.txt", "modified", old=None, new="changed\n")]
    changes[0]["old_digest"] = bytes_digest(b"")
    token = _stage_structured_candidate(
        tmp_path,
        structured_changes=changes,
        changed_files=[{"path": "link.txt", "status": "modified", "before_size": 0, "after_size": 8, "before_digest": "", "after_digest": bytes_digest(b"changed\n"), "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert "symlink" in result.details["reason"]
    assert secret.read_text(encoding="utf-8") == "SECRET=1\n"


def test_apply_success_details_include_structured_backend(tmp_path: Path) -> None:
    changes = [_structured("detail.txt", "added", old=None, new="detail\n")]
    token = _stage_structured_candidate(
        tmp_path,
        structured_changes=changes,
        changed_files=[{"path": "detail.txt", "status": "added", "before_size": 0, "after_size": 7, "before_digest": "", "after_digest": bytes_digest(b"detail\n"), "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.details["apply_backend"] == "structured_changes"
    assert result.details["structured_changes_digest"] == structured_changes_digest(changes)
    assert result.details["atomic"] is True
    assert result.details["lock_acquired"] is True
    assert result.details["post_apply_validated"] is True


def test_docker_structured_candidate_full_approval_apply_flow(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged_shell = registry.execute("run_shell", {"command": "Write-Output structured", "timeout_seconds": 7})
    changes = [_structured("flow.txt", "added", old=None, new="from sandbox\n")]
    fake = RecordingSandboxExecutor(
        SandboxRunResult(
            stdout="structured\n",
            stderr="",
            returncode=0,
            timed_out=False,
            backend="docker",
            sandbox_mode="docker",
            network_access=False,
            writable_roots=[str(tmp_path)],
            changed_files=[{"path": "flow.txt", "status": "added", "before_size": 0, "after_size": 13, "before_digest": "", "after_digest": bytes_digest(b"from sandbox\n"), "truncated": False}],
            patch_summary="1 added, 0 modified, 0 deleted",
            patch=_patch("a/flow.txt", "b/flow.txt", [], ["from sandbox\n"]),
            patch_truncated=False,
            structured_changes=changes,
            structured_changes_digest=structured_changes_digest(changes),
            structured_changes_truncated=False,
        )
    )

    shell_result = ApprovePendingActionTool(tmp_path, registry.policy_evaluator, tool_registry=registry, sandbox_executor=fake).execute(
        {"token": staged_shell.details["token"]}
    )

    candidate = shell_result.details["patch_candidate"]
    assert candidate["staged"] is True
    assert not (tmp_path / "flow.txt").exists()
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").load(candidate["token"])
    assert pending["action_type"] == "apply_patch_candidate"
    assert pending["lifecycle"]["state"] == "staged_not_granted"
    assert pending["details"]["structured_changes_digest"] == structured_changes_digest(changes)

    apply_result = ApprovePendingActionTool(tmp_path, registry.policy_evaluator, tool_registry=registry).execute(
        {"token": candidate["token"]}
    )

    assert (tmp_path / "flow.txt").read_text(encoding="utf-8") == "from sandbox\n"
    assert apply_result.details["applied"] is True
    assert apply_result.details["apply_backend"] == "structured_changes"
    assert apply_result.details["structured_changes_digest"] == structured_changes_digest(changes)
    assert apply_result.details["lock_acquired"] is True
    assert apply_result.details["lock_released"] is True
    assert apply_result.details["post_apply_validated"] is True


def test_sandbox_details_fields_are_stable_for_shell_and_apply(tmp_path: Path) -> None:
    registry = ToolRegistry(tmp_path)
    staged_shell = registry.execute("run_shell", {"command": "Write-Output fields", "timeout_seconds": 7})
    changes = [_structured("fields.txt", "added", old=None, new="fields\n")]
    fake = RecordingSandboxExecutor(
        SandboxRunResult(
            stdout="fields\n",
            stderr="",
            returncode=0,
            timed_out=False,
            backend="docker",
            sandbox_mode="docker",
            network_access=False,
            network_policy_mode="none",
            network_enforced=True,
            writable_roots=[str(tmp_path)],
            changed_files=[{"path": "fields.txt", "status": "added", "before_size": 0, "after_size": 7, "before_digest": "", "after_digest": bytes_digest(b"fields\n"), "truncated": False}],
            patch_summary="1 added, 0 modified, 0 deleted",
            patch=_patch("a/fields.txt", "b/fields.txt", [], ["fields\n"]),
            patch_truncated=False,
            structured_changes=changes,
            structured_changes_digest=structured_changes_digest(changes),
            structured_changes_truncated=False,
        )
    )

    shell_result = ApprovePendingActionTool(tmp_path, registry.policy_evaluator, tool_registry=registry, sandbox_executor=fake).execute(
        {"token": staged_shell.details["token"]}
    )
    shell_details = shell_result.details
    for field in (
        "sandbox_backend",
        "sandbox_mode",
        "sandbox_isolation",
        "network_access",
        "network_policy_mode",
        "network_enforced",
        "changed_files",
        "patch_summary",
        "patch_truncated",
        "structured_changes_count",
        "structured_changes_digest",
        "structured_changes_truncated",
    ):
        assert field in shell_details

    apply_result = ApprovePendingActionTool(tmp_path, registry.policy_evaluator, tool_registry=registry).execute(
        {"token": shell_details["patch_candidate"]["token"]}
    )
    apply_details = apply_result.details
    for field in (
        "apply_backend",
        "applied",
        "atomic",
        "lock_acquired",
        "lock_released",
        "post_apply_validated",
        "rollback_attempted",
        "changed_files",
        "structured_changes_digest",
    ):
        assert field in apply_details
    assert apply_details["apply_backend"] == "structured_changes"


def test_docs_sandbox_threat_model_mentions_non_goals() -> None:
    docs = Path("docs/sandbox.md").read_text(encoding="utf-8")

    assert "## Threat Model" in docs
    assert "Docker escape" in docs
    assert "does not provide real domain-level network allowlist enforcement" in docs
    assert "does not replace patch apply approval" in docs


def test_apply_patch_candidate_acquires_workspace_lock(tmp_path: Path) -> None:
    patch = _patch("a/locked.txt", "b/locked.txt", [], ["locked\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "locked.txt", "status": "added", "before_size": 0, "after_size": 7, "before_digest": "", "after_digest": "x", "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.details["lock_acquired"] is True
    assert result.details["lock_released"] is True
    assert result.details["lock_path"] == ".pp-agent/locks/apply.lock"
    assert isinstance(result.details["lock_wait_ms"], int)


def test_apply_patch_candidate_releases_lock_on_success(tmp_path: Path) -> None:
    patch = _patch("a/success.txt", "b/success.txt", [], ["success\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "success.txt", "status": "added", "before_size": 0, "after_size": 8, "before_digest": "", "after_digest": "x", "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is False
    assert result.details["lock_released"] is True
    assert not (tmp_path / ".pp-agent" / "locks" / "apply.lock").exists()


def test_apply_patch_candidate_applies_modified_file(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("before\n", encoding="utf-8")
    patch = _patch("a/notes.txt", "b/notes.txt", ["before\n"], ["after\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "notes.txt", "status": "modified", "before_size": 7, "after_size": 6, "before_digest": "a", "after_digest": "b", "truncated": False}],
    )

    ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "after\n"


def test_apply_patch_candidate_applies_deleted_file(tmp_path: Path) -> None:
    (tmp_path / "remove.txt").write_text("delete me\n", encoding="utf-8")
    patch = _patch("a/remove.txt", "b/remove.txt", ["delete me\n"], [])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "remove.txt", "status": "deleted", "before_size": 10, "after_size": 0, "before_digest": "a", "after_digest": "", "truncated": False}],
    )

    ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert not (tmp_path / "remove.txt").exists()


def test_apply_patch_candidate_rejects_protected_path(tmp_path: Path) -> None:
    patch = _patch("a/.env", "b/.env", [], ["SECRET=1\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": ".env", "status": "added", "before_size": 0, "after_size": 9, "before_digest": "", "after_digest": "x", "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert "protected" in result.content
    assert not (tmp_path / ".env").exists()


def test_apply_patch_candidate_rejects_path_traversal(tmp_path: Path) -> None:
    patch = _patch("a/../escape.txt", "b/../escape.txt", [], ["escape\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "../escape.txt", "status": "added", "before_size": 0, "after_size": 7, "before_digest": "", "after_digest": "x", "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert "traversal" in result.content
    assert not (tmp_path.parent / "escape.txt").exists()


def test_apply_patch_candidate_rejects_absolute_path(tmp_path: Path) -> None:
    absolute = str(tmp_path / "absolute.txt").replace("\\", "/")
    patch = _patch(absolute, absolute, [], ["absolute\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": absolute, "status": "added", "before_size": 0, "after_size": 9, "before_digest": "", "after_digest": "x", "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert "relative" in result.content
    assert not (tmp_path / "absolute.txt").exists()


def test_apply_patch_candidate_rejects_symlink_to_protected_target(tmp_path: Path) -> None:
    secret = tmp_path / ".env"
    secret.write_text("SECRET=1\n", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        return
    patch = _patch("a/link.txt", "b/link.txt", [], ["changed\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "link.txt", "status": "modified", "before_size": 0, "after_size": 8, "before_digest": "", "after_digest": "x", "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert "symlink" in result.content
    assert secret.read_text(encoding="utf-8") == "SECRET=1\n"


def test_apply_patch_candidate_records_lifecycle_or_trace(tmp_path: Path) -> None:
    patch = _patch("a/audit.txt", "b/audit.txt", [], ["audit\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "audit.txt", "status": "added", "before_size": 0, "after_size": 6, "before_digest": "", "after_digest": "x", "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.details["lifecycle"]["state"] == "grant_consumed"
    assert result.details["latest_audit"]["lifecycle_state"] == "grant_consumed"
    assert result.details["patch_digest"] == content_digest(patch)


def test_apply_patch_candidate_rolls_back_added_file_on_failure(tmp_path: Path) -> None:
    (tmp_path / "bad.txt").write_text("actual\n", encoding="utf-8")
    patch = _patch("a/created.txt", "b/created.txt", [], ["created\n"])
    patch += _patch("a/bad.txt", "b/bad.txt", ["expected\n"], ["changed\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[
            {"path": "created.txt", "status": "added", "before_size": 0, "after_size": 8, "before_digest": "", "after_digest": "a", "truncated": False},
            {"path": "bad.txt", "status": "modified", "before_size": 7, "after_size": 8, "before_digest": "b", "after_digest": "c", "truncated": False},
        ],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert not (tmp_path / "created.txt").exists()
    assert (tmp_path / "bad.txt").read_text(encoding="utf-8") == "actual\n"
    assert result.details["rollback_attempted"] is True
    assert result.details["rollback_succeeded"] is True
    assert result.details["partial_state_possible"] is False


def test_apply_patch_candidate_releases_lock_on_failure(tmp_path: Path) -> None:
    (tmp_path / "bad.txt").write_text("actual\n", encoding="utf-8")
    patch = _patch("a/bad.txt", "b/bad.txt", ["expected\n"], ["changed\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "bad.txt", "status": "modified", "before_size": 7, "after_size": 8, "before_digest": "a", "after_digest": "b", "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert result.details["lock_acquired"] is True
    assert result.details["lock_released"] is True
    assert not (tmp_path / ".pp-agent" / "locks" / "apply.lock").exists()


def test_apply_patch_candidate_rolls_back_modified_file_on_failure(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("before\n", encoding="utf-8")
    (tmp_path / "bad.txt").write_text("actual\n", encoding="utf-8")
    patch = _patch("a/notes.txt", "b/notes.txt", ["before\n"], ["after\n"])
    patch += _patch("a/bad.txt", "b/bad.txt", ["expected\n"], ["changed\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[
            {"path": "notes.txt", "status": "modified", "before_size": 7, "after_size": 6, "before_digest": "a", "after_digest": "b", "truncated": False},
            {"path": "bad.txt", "status": "modified", "before_size": 7, "after_size": 8, "before_digest": "c", "after_digest": "d", "truncated": False},
        ],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "before\n"
    assert result.details["atomic"] is True
    assert result.details["rollback_succeeded"] is True


def test_apply_patch_candidate_rolls_back_deleted_file_on_failure(tmp_path: Path) -> None:
    (tmp_path / "remove.txt").write_text("delete me\n", encoding="utf-8")
    (tmp_path / "bad.txt").write_text("actual\n", encoding="utf-8")
    patch = _patch("a/remove.txt", "b/remove.txt", ["delete me\n"], [])
    patch += _patch("a/bad.txt", "b/bad.txt", ["expected\n"], ["changed\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[
            {"path": "remove.txt", "status": "deleted", "before_size": 10, "after_size": 0, "before_digest": "a", "after_digest": "", "truncated": False},
            {"path": "bad.txt", "status": "modified", "before_size": 7, "after_size": 8, "before_digest": "b", "after_digest": "c", "truncated": False},
        ],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert (tmp_path / "remove.txt").read_text(encoding="utf-8") == "delete me\n"
    assert result.details["rollback_succeeded"] is True


def test_apply_patch_candidate_reports_partial_state_if_rollback_fails(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("before\n", encoding="utf-8")
    (tmp_path / "bad.txt").write_text("actual\n", encoding="utf-8")
    patch = _patch("a/notes.txt", "b/notes.txt", ["before\n"], ["after\n"])
    patch += _patch("a/bad.txt", "b/bad.txt", ["expected\n"], ["changed\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[
            {"path": "notes.txt", "status": "modified", "before_size": 7, "after_size": 6, "before_digest": "a", "after_digest": "b", "truncated": False},
            {"path": "bad.txt", "status": "modified", "before_size": 7, "after_size": 8, "before_digest": "c", "after_digest": "d", "truncated": False},
        ],
    )

    def fail_restore(self, snapshot):
        raise RuntimeError("rollback storage failed")

    monkeypatch.setattr(ApprovePendingActionTool, "_restore_snapshot", fail_restore)
    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert result.details["atomic"] is False
    assert result.details["rollback_attempted"] is True
    assert result.details["rollback_succeeded"] is False
    assert result.details["partial_state_possible"] is True
    assert result.details["rollback_error"] == "rollback storage failed"


def test_apply_patch_candidate_success_reports_atomic_true(tmp_path: Path) -> None:
    patch = _patch("a/atomic.txt", "b/atomic.txt", [], ["ok\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "atomic.txt", "status": "added", "before_size": 0, "after_size": 3, "before_digest": "", "after_digest": "x", "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is False
    assert result.details["applied"] is True
    assert result.details["atomic"] is True
    assert result.details["rollback_attempted"] is False
    assert result.details["post_apply_validated"] is True


def test_apply_patch_candidate_lock_timeout_reports_clear_error(monkeypatch, tmp_path: Path) -> None:
    class FastTimeoutWorkspaceApplyLock(WorkspaceApplyLock):
        def __init__(self, workspace: Path) -> None:
            super().__init__(workspace, timeout_seconds=0.01, poll_interval_seconds=0.001)

    held = WorkspaceApplyLock(tmp_path).acquire()
    monkeypatch.setattr("pp_agent.tools.file_tools.WorkspaceApplyLock", FastTimeoutWorkspaceApplyLock)
    patch = _patch("a/wait.txt", "b/wait.txt", [], ["wait\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "wait.txt", "status": "added", "before_size": 0, "after_size": 5, "before_digest": "", "after_digest": "x", "truncated": False}],
    )
    try:
        result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})
    finally:
        held.release()

    assert result.is_error is True
    assert result.details["lock_acquired"] is False
    assert result.details["lock_timeout"] is True
    assert result.details["reason"] == "workspace apply lock timeout"
    assert not (tmp_path / "wait.txt").exists()


def test_concurrent_patch_apply_is_serialized_or_rejected(tmp_path: Path) -> None:
    first = WorkspaceApplyLock(tmp_path).acquire()
    try:
        with pytest.raises(WorkspaceApplyLockTimeout):
            WorkspaceApplyLock(tmp_path, timeout_seconds=0.01, poll_interval_seconds=0.001).acquire()
    finally:
        first.release()

    second = WorkspaceApplyLock(tmp_path, timeout_seconds=0.01, poll_interval_seconds=0.001).acquire()
    second.release()


def test_apply_patch_candidate_post_apply_validation_rejects_unexpected_path(monkeypatch, tmp_path: Path) -> None:
    patch = _patch("a/notes.txt", "b/notes.txt", [], ["after\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "notes.txt", "status": "added", "before_size": 0, "after_size": 6, "before_digest": "", "after_digest": "b", "truncated": False}],
    )

    def fail_post_apply(self, files, changed_files, changed_paths):
        raise ValueError("Patch applied unexpected paths: surprise.txt")

    monkeypatch.setattr(ApprovePendingActionTool, "_validate_post_apply_changes", fail_post_apply)
    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert not (tmp_path / "notes.txt").exists()
    assert result.details["rollback_succeeded"] is True
    assert "unexpected paths" in result.details["reason"]


def test_apply_patch_candidate_post_apply_validation_rejects_protected_path(monkeypatch, tmp_path: Path) -> None:
    patch = _patch("a/notes.txt", "b/notes.txt", [], ["after\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "notes.txt", "status": "added", "before_size": 0, "after_size": 6, "before_digest": "", "after_digest": "b", "truncated": False}],
    )

    def fail_post_apply(self, files, changed_files, changed_paths):
        raise ValueError("Patch path is protected: .env")

    monkeypatch.setattr(ApprovePendingActionTool, "_validate_post_apply_changes", fail_post_apply)
    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert not (tmp_path / "notes.txt").exists()
    assert result.details["rollback_succeeded"] is True
    assert "protected" in result.details["reason"]


def test_apply_patch_candidate_refuses_snapshot_too_large_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("pp_agent.tools.file_tools.MAX_PATCH_SNAPSHOT_BYTES", 4)
    (tmp_path / "large.txt").write_text("before\n", encoding="utf-8")
    patch = _patch("a/large.txt", "b/large.txt", ["before\n"], ["after\n"])
    token = _stage_patch_candidate(
        tmp_path,
        patch=patch,
        changed_files=[{"path": "large.txt", "status": "modified", "before_size": 7, "after_size": 6, "before_digest": "a", "after_digest": "b", "truncated": False}],
    )

    result = ApprovePendingActionTool(tmp_path, tool_registry=ToolRegistry(tmp_path)).execute({"token": token})

    assert result.is_error is True
    assert (tmp_path / "large.txt").read_text(encoding="utf-8") == "before\n"
    assert result.details["rollback_attempted"] is False
    assert result.details["partial_state_possible"] is False
    assert "too large to snapshot" in result.details["reason"]


def test_workspace_lock_refuses_symlinked_pp_agent_dir(tmp_path: Path) -> None:
    target = tmp_path / "outside-state"
    target.mkdir()
    link = tmp_path / ".pp-agent"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        return

    with pytest.raises(WorkspaceApplyLockError, match="symlink"):
        WorkspaceApplyLock(tmp_path).acquire()


def test_workspace_lock_refuses_symlinked_lock_dir(tmp_path: Path) -> None:
    (tmp_path / ".pp-agent").mkdir()
    target = tmp_path / "outside-locks"
    target.mkdir()
    link = tmp_path / ".pp-agent" / "locks"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        return

    with pytest.raises(WorkspaceApplyLockError, match="symlink"):
        WorkspaceApplyLock(tmp_path).acquire()


def test_workspace_lock_release_only_own_lock(tmp_path: Path) -> None:
    handle = WorkspaceApplyLock(tmp_path).acquire()
    lock_path = tmp_path / ".pp-agent" / "locks" / "apply.lock"
    lock_path.write_text('{"token":"different"}', encoding="utf-8")

    with pytest.raises(WorkspaceApplyLockReleaseError, match="different token"):
        handle.release()

    assert lock_path.exists()
    lock_path.unlink()
