# Sandbox Execution Model

## Overview

pp-Echo separates shell safety into complementary layers:

- **Policy gate** decides whether a tool call is allowed, denied, or must be reviewed.
- **Exact-effect approval** binds approval to a concrete effect payload digest.
- **Sandbox executor** runs approved shell commands behind a backend boundary.
- **Patch candidate approval** keeps sandbox command approval separate from real workspace writes.
- **Trace/details** expose bounded metadata for audit and debugging.

The sandbox executor does not replace policy or approval. Approving a shell command approves command execution only. Applying sandbox-produced file changes requires a separate `apply_patch_candidate` approval.

## Backend Modes

### local

`LocalSandboxExecutor` is the compatibility backend and remains the default. It preserves the previous local PowerShell behavior.

It is **not a security sandbox**. It does not isolate filesystem writes, processes, network access, credentials, or host resources. Details report it as local compatibility, not secure isolation.

The default backend remains `local`.

### docker

`DockerSandboxExecutor` is the opt-in sandbox backend. It is selected through config, env, or CLI, for example:

```powershell
$env:PP_ECHO_SANDBOX_BACKEND = "docker"
python -m pp_agent.cli.main run "check this repo"
```

Unknown backends are rejected. Docker is never enabled by default.

## Docker Execution Flow

1. The model stages a `run_shell` action.
2. The user or host approves that shell action.
3. Docker executor copies the real workspace into a temporary workspace.
4. Protected paths are skipped during copy and diff collection.
5. Docker mounts only the temporary workspace at `/workspace`.
6. The command runs in Docker, normally with no network.
7. Docker compares temporary workspace changes against the real workspace.
8. The shell result returns a patch candidate: `changed_files`, display `patch`, and `structured_changes`.
9. No file changes are written back to the real workspace yet.
10. pp-Echo stages `apply_patch_candidate` if the candidate is complete and applyable.
11. A separate patch approval is required.
12. Patch apply obtains the workspace apply lock.
13. Apply snapshots target files, writes changes, runs post-apply validation, and rolls back on failure where possible.

If an `apply_patch_candidate` pending action carries a `write_scope`, pp-Echo checks structured changes against that runtime write boundary before the workspace apply lock is acquired. A blocked write scope prevents snapshotting and file writes. Legacy pending actions without `write_scope` keep their existing apply behavior.

`write_scope` does not replace approval, payload digest checks, structured change digests, rollback, protected path checks, or the workspace apply lock. It is an additional task-level write boundary for candidates that choose to carry it.

For future controlled coding execution flows, `RuntimeExecutionContext` can carry the same `WriteScope` plus guardrail metadata. `attach_runtime_context_to_patch_candidate_args` can copy that `write_scope` into patch candidate args and add minimal execution metadata. When no runtime context is provided, legacy patch candidate behavior is unchanged.

When a runtime patch-candidate guardrail blocks creation, pp-Echo does not create the `apply_patch_candidate` pending action. When creation is allowed, the `write_scope` is attached before the pending action effect and payload digest are built. This preserves the existing approval, digest, rollback, protected-path checks, and workspace apply lock semantics.

During Web execution, pp-Echo emits a `sandbox_preflight` runtime event before the executor starts. Approval failures also include `sandbox_preflight` / `docker_preflight` details so the page can show the exact phase that blocked execution instead of treating sandbox startup as a black box.

Protected paths include:

- `.git/**`
- `.pp-agent/**`
- `.env`
- `.env.*`
- `*.pem`
- `*.key`

Path checks normalize separators and traversal segments. Symlinks are skipped during Docker copy/diff and rejected during apply when they could redirect writes.

## Network Policy

Docker sandbox defaults to no network. The default Docker command includes:

```text
--network none
```

Network policy modes:

- `none`: default. `network_access=false`; Docker runs with `--network none`.
- `allowlist_config_only`: `network_access=true` with `network_allowlist`. pp-Echo validates the allowlist but refuses execution because there is no proxy, firewall, egress gateway, remote sandbox, or Docker network policy enforcement yet. Details report `network_enforced=false`.
- `dangerously_allow_all`: `network_access=true` and `network_dangerously_allow_all=true`; Docker runs with `--network bridge`.

`network_allowlist` is a policy configuration entry point, not full domain-level egress enforcement. It does not prevent DNS rebinding, DNS result drift, IP resolution changes, or direct IP egress. pp-Echo does not provide real domain-level network allowlist enforcement today.

Rejected allowlist examples include:

- `localhost`
- `host.docker.internal`
- `127.0.0.1`
- `127.0.0.0/8`
- `10.0.0.0/8`
- `172.16.0.0/12`
- `192.168.0.0/16`
- `169.254.0.0/16`
- `169.254.169.254`
- `0.0.0.0/0`
- `::/0`
- `*`
- `https://pypi.org`
- `pypi.org/simple`

Normal domain names such as `pypi.org` and `files.pythonhosted.org` may pass validation, but execution is refused until real enforcement exists. If full network access is explicitly accepted:

```powershell
$env:PP_ECHO_SANDBOX_NETWORK = "1"
$env:PP_ECHO_SANDBOX_NETWORK_DANGEROUSLY_ALLOW_ALL = "1"
```

Do not use `network_dangerously_allow_all=true` in environments containing secrets unless you accept full network egress risk.

## Docker Image

The default Docker image is:

```text
pp-echo-sandbox:base
```

Build it from the repository root:

```powershell
docker build -t pp-echo-sandbox:base -f docker/sandbox-base/Dockerfile .
```

When Docker sandbox is enabled, pp-Echo automatically uses `pp-echo-sandbox:base` unless `sandbox.image` or `PP_ECHO_SANDBOX_IMAGE` names a project image. pp-Echo does not silently install Docker Desktop or Docker Engine because installation is host-level software management and may require administrator approval. The Web API exposes a preflight check instead:

```text
GET /api/sandbox/status
GET /api/sandbox/status?session_id=<session-id>
```

The status payload reports whether the selected backend is `local` or `docker`, whether `docker` is on PATH, whether the daemon is reachable, whether the configured image exists, the Docker install URL for the host OS, and the base image build command. The Web settings page uses the same preflight data so a missing Docker CLI, stopped daemon, or missing base image is visible before approving a shell command.

If Docker is missing on Windows:

1. Install Docker Desktop from the URL returned by `/api/sandbox/status`.
2. Restart the terminal or pp-Echo Web process so `docker.exe` is on PATH.
3. Run `docker info` in the same terminal.
4. Build the base image with the command above.

`pp-echo-sandbox:base` is a general execution environment with shell, git, diff, patch, archive, and text-processing tools. It is not a Python, Node.js, Java, C++, or multi-language development image.

pp-Echo does not auto-detect project languages and does not map languages to images. The project owns the language toolchain. Projects should provide their own image when they need specific toolchains:

```dockerfile
FROM pp-echo-sandbox:base
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip nodejs npm \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
```

```powershell
docker build -t my-project-dev:latest -f docker/my-project/Dockerfile .
$env:PP_ECHO_SANDBOX_IMAGE = "my-project-dev:latest"
```

`docker/examples/python/Dockerfile` is an example profile only. Python is not assumed and is not the default.

## Structured Changes

Docker sandbox returns both unified diff and structured changes:

- `patch` is retained for display and legacy compatibility.
- `structured_changes` is the preferred apply format.

Each structured change includes:

- `path`: workspace-relative path.
- `change_type`: `added`, `modified`, or `deleted`.
- `old_digest`: sha256 digest of old file bytes, or `null` for added files.
- `new_digest`: sha256 digest of new file bytes, or `null` for deleted files.
- `content_text`: new UTF-8 content for added or modified text files.
- `binary`: whether the change is binary.
- `truncated`: whether bounded capture limits were exceeded.

`structured_changes_digest` is sha256 over canonical JSON for the structured change list. `apply_patch_candidate` validates this digest before applying anything.

For modified and deleted files, `old_digest` must match the current real workspace bytes. This catches external edits that happen after the candidate was generated. For added and modified files, `new_digest` must match the proposed bytes before and after writing. This catches corrupted or tampered payload content.

Binary or truncated structured changes are not auto-applied. `structured_changes_truncated=true` prevents staging a patch apply action. Legacy candidates without structured changes still use the restricted `internal_unified_diff` fallback.

## Threat Model

pp-Echo helps protect against:

- Accidental direct writeback from Docker sandbox to the real workspace.
- Applying sandbox file changes without a second explicit approval.
- Candidate tampering through payload, patch, or structured digest checks.
- Applying changes to protected paths.
- Path traversal, absolute path writes, and symlink write redirection.
- Concurrent pp-Echo patch applies through the workspace apply lock.
- Partial apply failures through target snapshots, rollback, and post-apply validation where possible.

pp-Echo does **not** protect against:

- Docker escape vulnerabilities.
- Kernel vulnerabilities.
- Malicious or compromised container images.
- A compromised host machine.
- External editors, git commands, or other processes changing files concurrently.
- Full filesystem transaction failure modes.
- Real domain-level network allowlist enforcement.
- DNS rebinding, DNS result drift, or direct IP egress.
- Covert channels or all resource exhaustion attacks.

Network policy does not replace protected paths, structured change validation, patch apply approval, or workspace locking. The sandbox does not replace human review and does not replace patch apply approval.
