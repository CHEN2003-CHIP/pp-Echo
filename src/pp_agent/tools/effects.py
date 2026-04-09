from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any


CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
CONFIDENCE_UNKNOWN = "unknown"

_WHITESPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r'''"[^"]*"|'[^']*'|\S+''')
_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_UNC_PATH_RE = re.compile(r"^\\\\")
_NETWORK_KEYWORDS = ("fetch", "web", "url", "network", "remote", "http", "https", "curl", "wget", "article", "webpage")
_RISK_ORDER = {
    "inspect": 0,
    "unknown": 1,
    "workspace_mutation": 2,
    "external_mutation": 3,
    "networked": 4,
    "destructive": 5,
}


def content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def normalize_shell_command(command: str) -> str:
    return _WHITESPACE_RE.sub(" ", command.strip())


def summarize_shell_command(command: str, limit: int = 80) -> str:
    normalized = normalize_shell_command(command)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def tokenize_shell_command(command: str) -> list[str]:
    normalized = normalize_shell_command(command)
    if not normalized:
        return []
    return _TOKEN_RE.findall(normalized)


def stable_path_label(workspace: Path, target_path: Path) -> str:
    try:
        return target_path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return str(target_path.resolve())


def payload_digest(permission_domain: str, tool_name: str, normalized_arguments: dict[str, Any], baseline: dict[str, Any] | None) -> str:
    payload = {
        "permission_domain": permission_domain,
        "tool_name": tool_name,
        "normalized_arguments": normalized_arguments,
        "baseline": baseline,
    }
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def canonicalize_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [canonicalize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [canonicalize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): canonicalize_json_value(value[key]) for key in sorted(value, key=lambda item: str(item))}
    raise TypeError(f"Value is not JSON serializable for exact-effect staging: {type(value).__name__}")


def dynamic_tool_declarations(
    *,
    exact_effect_mode: str = "auto",
    non_side_effectful: bool = False,
    known_safe_inspect: bool = False,
    requests_network_hint: bool = False,
    touches_external_hint: bool = False,
) -> dict[str, Any]:
    return {
        "exact_effect_mode": exact_effect_mode,
        "non_side_effectful": non_side_effectful,
        "known_safe_inspect": known_safe_inspect,
        "requests_network_hint": requests_network_hint,
        "touches_external_hint": touches_external_hint,
    }


def summarize_dynamic_tool_effect(*, family: str, tool_name: str, risk_class: str, known_safe_inspect: bool, requests_network: bool) -> str:
    subject = "MCP tool" if family == "mcp" else "extension tool"
    if requests_network or risk_class == "networked":
        return f"Run networked {subject} {tool_name}"
    if risk_class == "destructive":
        return f"Run destructive {subject} {tool_name}"
    if risk_class == "external_mutation":
        return f"Run external-path {subject} {tool_name}"
    if known_safe_inspect and risk_class == "inspect":
        return f"Inspect with {subject} {tool_name}"
    return f"Run {subject} {tool_name}"


def _tighten_risk_class(current: str, candidate: str) -> str:
    current_rank = _RISK_ORDER.get(current, _RISK_ORDER["unknown"])
    candidate_rank = _RISK_ORDER.get(candidate, _RISK_ORDER["unknown"])
    return candidate if candidate_rank > current_rank else current


def _dynamic_base_analysis(
    *,
    family: str,
    tool_name: str,
    permission_domain: str,
    description: str,
    declarations: dict[str, Any],
    hints: dict[str, Any],
) -> dict[str, Any]:
    lowered = f"{tool_name} {description}".lower()
    declared_requests_network = bool(declarations.get("requests_network_hint"))
    declared_touches_external = bool(declarations.get("touches_external_hint"))
    compat_requests_network = bool(hints.get("requests_network"))
    compat_touches_external = bool(hints.get("touches_external"))
    compat_destructive = bool(hints.get("destructive_hint"))
    compat_protected_path = bool(hints.get("protected_path_hint"))
    compat_touches_workspace = bool(hints.get("touches_workspace"))
    runtime_requests_network = any(keyword in lowered for keyword in _NETWORK_KEYWORDS)

    requests_network = declared_requests_network or compat_requests_network or runtime_requests_network
    touches_external = declared_touches_external or compat_touches_external
    destructive_hint = compat_destructive
    protected_path_hint = compat_protected_path
    touches_workspace = compat_touches_workspace

    declared_non_side_effectful = bool(declarations.get("non_side_effectful"))
    declared_safe_inspect = bool(declarations.get("known_safe_inspect"))
    non_side_effectful = declared_non_side_effectful and not (requests_network or touches_external or destructive_hint)
    known_safe_inspect = declared_safe_inspect and non_side_effectful and not requests_network and not touches_external and not destructive_hint

    risk_class = "unknown"
    if known_safe_inspect:
        risk_class = "inspect"
    if touches_external:
        risk_class = _tighten_risk_class(risk_class, "external_mutation")
    if requests_network:
        risk_class = _tighten_risk_class(risk_class, "networked")
    if destructive_hint:
        risk_class = _tighten_risk_class(risk_class, "destructive")

    score = 0.2
    if known_safe_inspect:
        score = 0.95
    elif risk_class == "unknown":
        score = 0.25 if family == "extension" else 0.2
    elif risk_class == "inspect":
        score = 0.84 if family == "extension" else 0.8
    else:
        score = 0.45 if family == "extension" else 0.4

    return {
        "family": family,
        "permission_domain": permission_domain,
        "tool_name": tool_name,
        "declared_exact_effect_mode": declarations.get("exact_effect_mode", "auto"),
        "declared_requests_network_hint": declared_requests_network,
        "declared_touches_external_hint": declared_touches_external,
        "non_side_effectful": non_side_effectful,
        "known_safe_inspect": known_safe_inspect,
        "requests_network": requests_network,
        "touches_external": touches_external,
        "touches_workspace": touches_workspace,
        "destructive_hint": destructive_hint,
        "protected_path_hint": protected_path_hint,
        "risk_class": risk_class,
        "summary": summarize_dynamic_tool_effect(
            family=family,
            tool_name=tool_name,
            risk_class=risk_class,
            known_safe_inspect=known_safe_inspect,
            requests_network=requests_network,
        ),
        "confidence_score": float(score),
    }


def file_baseline(*, existed: bool, before: str) -> dict[str, Any]:
    if not existed:
        return {"kind": "absent"}
    return {"kind": "present", "content_digest": content_digest(before)}


def classify_confidence_band(score: float | None) -> str:
    if score is None:
        return CONFIDENCE_UNKNOWN
    if score >= 0.9:
        return CONFIDENCE_HIGH
    if score >= 0.65:
        return CONFIDENCE_MEDIUM
    if score > 0:
        return CONFIDENCE_LOW
    return CONFIDENCE_UNKNOWN


def is_protected_path(workspace: Path, target_path: Path) -> bool:
    resolved = target_path.resolve()
    try:
        rel = resolved.relative_to(workspace.resolve()).as_posix().lower()
    except ValueError:
        rel = resolved.name.lower()
    name = resolved.name.lower()
    if rel == ".env" or name == ".env":
        return True
    if name.startswith(".env."):
        return True
    if name.endswith(".pem") or name.endswith(".key"):
        return True
    return rel == ".pp-agent" or rel.startswith(".pp-agent/") or rel == ".git" or rel.startswith(".git/")


def _is_within_workspace(workspace: Path, target_path: Path) -> bool:
    resolved = target_path.resolve()
    workspace = workspace.resolve()
    return resolved == workspace or workspace in resolved.parents


def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        return token[1:-1]
    return token


def _looks_like_absolute_path(token: str) -> bool:
    return token.startswith("/") or bool(_WINDOWS_ABS_PATH_RE.match(token) or _UNC_PATH_RE.match(token))


def _is_outside_workspace(token: str, workspace: Path | None) -> bool:
    if workspace is None:
        return _looks_like_absolute_path(token)
    candidate = _unquote(token)
    if not _looks_like_absolute_path(candidate):
        return False
    try:
        resolved = Path(candidate).resolve()
    except OSError:
        return True
    workspace = workspace.resolve()
    return resolved != workspace and workspace not in resolved.parents


def _analysis(
    *,
    family: str,
    permission_domain: str,
    risk_class: str,
    summary: str,
    confidence_score: float | None,
    touches_workspace: bool,
    touches_external: bool,
    requests_network: bool,
    destructive_hint: bool,
    protected_path_hint: bool,
    known_safe_inspect: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "family": family,
        "permission_domain": permission_domain,
        "risk_class": risk_class,
        "summary": summary,
        "confidence_band": classify_confidence_band(confidence_score),
        "confidence_score": confidence_score,
        "touches_workspace": touches_workspace,
        "touches_external": touches_external,
        "requests_network": requests_network,
        "destructive_hint": destructive_hint,
        "protected_path_hint": protected_path_hint,
        "known_safe_inspect": known_safe_inspect,
    }
    if extra:
        payload.update(extra)
    return payload


def analyze_file_call(*, workspace: Path, tool_name: str, permission_domain: str, target_path: Path) -> dict[str, Any]:
    path_label = stable_path_label(workspace, target_path)
    touches_external = not _is_within_workspace(workspace, target_path)
    protected_path_hint = is_protected_path(workspace, target_path) if not touches_external else False
    if permission_domain == "read" or tool_name == "read_file":
        summary = f"Read file {path_label}"
        risk_class = "inspect"
    elif tool_name == "write_file":
        summary = f"Write file {path_label}"
        risk_class = "workspace_mutation"
    else:
        summary = f"Edit file {path_label}"
        risk_class = "workspace_mutation"
    score = 0.98 if not touches_external else 0.92
    return _analysis(
        family="file",
        permission_domain=permission_domain,
        risk_class=risk_class,
        summary=summary,
        confidence_score=score,
        touches_workspace=not touches_external,
        touches_external=touches_external,
        requests_network=False,
        destructive_hint=False,
        protected_path_hint=protected_path_hint,
        extra={"path": path_label},
    )


def classify_shell_effect(command: str, *, workspace: Path | None = None) -> dict[str, Any]:
    normalized_command = normalize_shell_command(command)
    tokens = tokenize_shell_command(normalized_command)
    lower_tokens = [_unquote(token).lower() for token in tokens]
    command_head = lower_tokens[0] if lower_tokens else ""
    second = lower_tokens[1] if len(lower_tokens) > 1 else ""

    flags: list[str] = []
    requests_network = False
    destructive_hint = False
    touches_external_paths = any(_is_outside_workspace(token, workspace) for token in tokens)

    inspect_heads = {"rg", "grep", "ls", "dir", "get-childitem"}
    vcs_read_pairs = {("git", "status"), ("git", "diff"), ("git", "show"), ("git", "log")}
    destructive_heads = {"rm", "del", "erase", "remove-item", "rmdir"}
    fetch_heads = {"curl", "wget", "invoke-webrequest", "irm", "invoke-restmethod", "iwr"}
    formatter_heads = {"black", "isort", "prettier", "clang-format"}
    test_heads = {"pytest", "tox", "nox"}
    package_manager_heads = {"pip", "pip3", "python", "python3", "uv", "npm", "pnpm", "yarn", "poetry"}
    workspace_mutation_heads = {
        "pytest",
        "tox",
        "nox",
        "black",
        "ruff",
        "isort",
        "prettier",
        "npm",
        "pnpm",
        "yarn",
        "poetry",
        "make",
        "cmake",
        "msbuild",
        "dotnet",
    }
    write_heads = {
        "set-content",
        "add-content",
        "out-file",
        "copy-item",
        "move-item",
        "new-item",
        "set-itemproperty",
    }

    if (command_head, second) in vcs_read_pairs:
        flags.append("vcs_read")
    if command_head == "git" and second in {"add", "commit", "push", "pull", "checkout", "switch", "restore", "reset", "clean"}:
        flags.append("vcs_write")
    if command_head in formatter_heads or (command_head == "ruff" and second == "format"):
        flags.append("formatter")
    if command_head in test_heads or (command_head in {"python", "python3"} and second == "-m" and len(lower_tokens) > 2 and lower_tokens[2] == "pytest"):
        flags.append("test_runner")
    if command_head in package_manager_heads:
        if (command_head in {"pip", "pip3"} and second in {"install", "uninstall"}) or (
            command_head in {"python", "python3"} and second == "-m" and len(lower_tokens) > 3 and lower_tokens[2] == "pip" and lower_tokens[3] == "install"
        ) or (command_head in {"uv", "poetry"} and second in {"add", "remove", "install", "update"}) or (
            command_head in {"npm", "pnpm", "yarn"} and second in {"install", "add", "update", "upgrade", "remove"}
        ):
            flags.append("package_manager")
            requests_network = True

    if command_head in fetch_heads:
        requests_network = True

    if command_head in destructive_heads:
        destructive_hint = True
    if command_head == "git" and second in {"clean", "reset"}:
        destructive_hint = True

    writes_workspace_files = False
    if command_head in workspace_mutation_heads or command_head in write_heads:
        writes_workspace_files = True
    if "test_runner" in flags or "formatter" in flags or "package_manager" in flags:
        writes_workspace_files = True
    if ">" in normalized_command:
        writes_workspace_files = True
    if command_head == "git" and second in {"apply", "checkout", "restore", "clean", "reset"}:
        writes_workspace_files = True

    if touches_external_paths:
        risk_class = "external_mutation"
    elif destructive_hint:
        risk_class = "destructive"
    elif requests_network:
        risk_class = "networked"
    elif command_head in inspect_heads or (command_head, second) in vcs_read_pairs:
        risk_class = "inspect"
    elif writes_workspace_files:
        risk_class = "workspace_mutation"
    else:
        risk_class = "workspace_mutation"

    has_shell_operators = any(operator in normalized_command for operator in ("|", ";", ">", "<", "&&", "||"))
    known_safe_inspect = (
        risk_class == "inspect"
        and not has_shell_operators
        and not requests_network
        and not destructive_hint
        and not touches_external_paths
        and ((command_head, second) in {("git", "status"), ("git", "diff")} or command_head in {"rg", "grep", "ls", "dir", "get-childitem"})
    )
    confidence_score = 0.96 if known_safe_inspect else 0.84 if risk_class == "inspect" else 0.72

    return {
        "normalized_command": normalized_command,
        "command_head": command_head,
        "risk_class": risk_class,
        "writes_workspace_files": writes_workspace_files,
        "touches_external_paths": touches_external_paths,
        "requests_network": requests_network,
        "destructive_hint": destructive_hint,
        "flags": sorted(set(flags)),
        "known_safe_inspect": known_safe_inspect,
        "confidence_score": confidence_score,
    }


def summarize_shell_effect(classification: dict[str, Any]) -> str:
    normalized_command = classification["normalized_command"]
    snippet = summarize_shell_command(normalized_command)
    head = classification.get("command_head") or "shell"
    flags = set(classification.get("flags") or [])
    risk_class = classification["risk_class"]

    if risk_class == "inspect":
        if head == "git" and normalized_command.startswith("git status"):
            return "Inspect repository status with git status"
        if head == "git" and normalized_command.startswith("git diff"):
            return "Inspect repository changes with git diff"
        if head in {"rg", "grep"}:
            return f"Inspect files with {snippet}"
        return f"Inspect workspace with {snippet}"
    if risk_class == "destructive":
        return f"Delete files with {snippet}"
    if risk_class == "external_mutation":
        return f"Modify paths outside workspace with {snippet}"
    if risk_class == "networked":
        if "package_manager" in flags:
            return f"Install or update packages with {snippet}"
        return f"Fetch remote content with {head}"
    if "test_runner" in flags:
        return f"Run tests with {snippet}"
    if "formatter" in flags:
        return f"Format workspace files with {snippet}"
    return f"Modify workspace with {snippet}"


def analyze_shell_call(*, permission_domain: str, command: str, timeout_seconds: int, workspace: Path | None = None) -> dict[str, Any]:
    classification = classify_shell_effect(command, workspace=workspace)
    summary = summarize_shell_effect(classification)
    return _analysis(
        family="shell",
        permission_domain=permission_domain,
        risk_class=classification["risk_class"],
        summary=summary,
        confidence_score=classification["confidence_score"],
        touches_workspace=not classification["touches_external_paths"],
        touches_external=classification["touches_external_paths"],
        requests_network=classification["requests_network"],
        destructive_hint=classification["destructive_hint"],
        protected_path_hint=False,
        known_safe_inspect=classification["known_safe_inspect"],
        extra={
            "normalized_command": classification["normalized_command"],
            "command_head": classification["command_head"],
            "timeout_seconds": int(timeout_seconds),
            "flags": classification["flags"],
            "writes_workspace_files": classification["writes_workspace_files"],
        },
    )


def analyze_extension_call(
    *,
    tool_name: str,
    permission_domain: str,
    description: str = "",
    declarations: dict[str, Any] | None = None,
    hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    declarations = declarations or dynamic_tool_declarations()
    hints = hints or {}
    base = _dynamic_base_analysis(
        family="extension",
        tool_name=tool_name,
        permission_domain=permission_domain,
        description=description,
        declarations=declarations,
        hints=hints,
    )
    return _analysis(
        family="extension",
        permission_domain=permission_domain,
        risk_class=base["risk_class"],
        summary=base["summary"],
        confidence_score=base["confidence_score"],
        touches_workspace=base["touches_workspace"],
        touches_external=base["touches_external"],
        requests_network=base["requests_network"],
        destructive_hint=base["destructive_hint"],
        protected_path_hint=base["protected_path_hint"],
        known_safe_inspect=base["known_safe_inspect"],
        extra={
            "non_side_effectful": base["non_side_effectful"],
            "declared_exact_effect_mode": base["declared_exact_effect_mode"],
            "declared_requests_network_hint": base["declared_requests_network_hint"],
            "declared_touches_external_hint": base["declared_touches_external_hint"],
        },
    )


def analyze_mcp_call(
    *,
    tool_name: str,
    permission_domain: str,
    description: str = "",
    declarations: dict[str, Any] | None = None,
    hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    declarations = declarations or dynamic_tool_declarations()
    hints = hints or {}
    base = _dynamic_base_analysis(
        family="mcp",
        tool_name=tool_name,
        permission_domain=permission_domain,
        description=description,
        declarations=declarations,
        hints=hints,
    )
    return _analysis(
        family="mcp",
        permission_domain=permission_domain,
        risk_class=base["risk_class"],
        summary=base["summary"],
        confidence_score=base["confidence_score"],
        touches_workspace=base["touches_workspace"],
        touches_external=base["touches_external"],
        requests_network=base["requests_network"],
        destructive_hint=base["destructive_hint"],
        protected_path_hint=base["protected_path_hint"],
        known_safe_inspect=base["known_safe_inspect"],
        extra={
            "non_side_effectful": base["non_side_effectful"],
            "declared_exact_effect_mode": base["declared_exact_effect_mode"],
            "declared_requests_network_hint": base["declared_requests_network_hint"],
            "declared_touches_external_hint": base["declared_touches_external_hint"],
        },
    )


def build_dynamic_tool_effect(
    *,
    tool_name: str,
    permission_domain: str,
    family: str,
    arguments: dict[str, Any],
    analysis: dict[str, Any],
    effect_id: str | None = None,
    created_at: float | None = None,
) -> dict[str, Any]:
    canonical_arguments = canonicalize_json_value(arguments)
    normalized_arguments = {
        "family": family,
        "arguments": canonical_arguments,
        "risk_class": analysis["risk_class"],
        "touches_external": bool(analysis.get("touches_external")),
        "requests_network": bool(analysis.get("requests_network")),
        "destructive_hint": bool(analysis.get("destructive_hint")),
        "protected_path_hint": bool(analysis.get("protected_path_hint")),
    }
    return {
        "effect_id": effect_id or str(uuid.uuid4()),
        "permission_domain": permission_domain,
        "tool_name": tool_name,
        "normalized_arguments": normalized_arguments,
        "analysis": analysis,
        "summary": analysis["summary"],
        "payload_digest": payload_digest(permission_domain, tool_name, normalized_arguments, baseline=None),
        "created_at": created_at or time.time(),
        "baseline": None,
    }


def build_file_effect(
    *,
    workspace: Path,
    tool_name: str,
    permission_domain: str,
    target_path: Path,
    after: str,
    baseline: dict[str, Any],
    overwrite: bool = False,
    effect_id: str | None = None,
    created_at: float | None = None,
) -> dict[str, Any]:
    analysis = analyze_file_call(workspace=workspace, tool_name=tool_name, permission_domain=permission_domain, target_path=target_path)
    normalized_arguments = {
        "path": stable_path_label(workspace, target_path),
        "after": after,
        "overwrite": overwrite,
        "risk_class": analysis["risk_class"],
        "protected_path_hint": analysis["protected_path_hint"],
        "touches_external": analysis["touches_external"],
    }
    return {
        "effect_id": effect_id or str(uuid.uuid4()),
        "permission_domain": permission_domain,
        "tool_name": tool_name,
        "normalized_arguments": normalized_arguments,
        "analysis": analysis,
        "summary": analysis["summary"],
        "payload_digest": payload_digest(permission_domain, tool_name, normalized_arguments, baseline),
        "created_at": created_at or time.time(),
        "baseline": baseline,
    }


def build_shell_effect(
    *,
    tool_name: str,
    permission_domain: str,
    command: str,
    timeout_seconds: int,
    workspace: Path | None = None,
    effect_id: str | None = None,
    created_at: float | None = None,
) -> dict[str, Any]:
    analysis = analyze_shell_call(
        permission_domain=permission_domain,
        command=command,
        timeout_seconds=timeout_seconds,
        workspace=workspace,
    )
    normalized_arguments = {
        "command": analysis["normalized_command"],
        "normalized_command": analysis["normalized_command"],
        "command_head": analysis["command_head"],
        "timeout_seconds": int(timeout_seconds),
        "risk_class": analysis["risk_class"],
        "touches_external": analysis["touches_external"],
        "requests_network": analysis["requests_network"],
        "destructive_hint": analysis["destructive_hint"],
    }
    classification = {
        "risk_class": analysis["risk_class"],
        "writes_workspace_files": analysis["writes_workspace_files"],
        "touches_external_paths": analysis["touches_external"],
        "requests_network": analysis["requests_network"],
        "destructive_hint": analysis["destructive_hint"],
        "flags": analysis["flags"],
        "command_head": analysis["command_head"],
        "normalized_command": analysis["normalized_command"],
        "known_safe_inspect": analysis["known_safe_inspect"],
    }
    return {
        "effect_id": effect_id or str(uuid.uuid4()),
        "permission_domain": permission_domain,
        "tool_name": tool_name,
        "normalized_arguments": normalized_arguments,
        "analysis": analysis,
        "classification": classification,
        "summary": analysis["summary"],
        "payload_digest": payload_digest(permission_domain, tool_name, normalized_arguments, baseline=None),
        "created_at": created_at or time.time(),
        "baseline": None,
    }
