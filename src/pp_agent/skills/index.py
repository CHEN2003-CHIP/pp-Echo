from __future__ import annotations

import fnmatch
from pathlib import Path
import json
from typing import Any, Optional

from pydantic import BaseModel, Field, PrivateAttr


BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent
PP_ECHO_ROOT_SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"


class SkillDescriptor(BaseModel):
    """Metadata-only skill descriptor with a lazily materialized body."""

    name: str
    description: str
    path: Path
    origin_type: str = "project"
    root_name: Optional[str] = None
    precedence: int = 0
    declared_by_manifest: bool = False
    discovery_root: Optional[str] = None
    discovery_mode: str = "workspace_directory"
    metadata: dict[str, Any] = Field(default_factory=dict)

    _body_cache: Optional[str] = PrivateAttr(default=None)

    @property
    def body(self) -> str:
        if self._body_cache is None:
            from pp_agent.skills.materializer import materialize_skill

            self._body_cache = materialize_skill(self)
        return self._body_cache

    def cache_body(self, body: str) -> str:
        self._body_cache = body
        return body


class SkillSearchRoot(BaseModel):
    path: Path
    origin_type: str
    root_name: Optional[str] = None
    # 加载优先级（数字越大，优先级越高）
    precedence: int = 0
    declared_by_manifest: bool = False
    discovery_root: Optional[str] = None
    discovery_mode: str = "workspace_directory"


class _DefaultSkillConfig:
    enable_project = True
    enable_user = True
    enable_builtin = True
    custom_directories: list[str] = []
    ignored: list[str] = []
    include: list[str] = []


DEFAULT_SKILL_CONFIG = _DefaultSkillConfig()


def skill_search_paths(
    workspace: Path,
    user_root: Path,
    config: Any = None,
) -> list[Path]:
    return [root.path for root in skill_search_roots(workspace, user_root, config=config)]


def skill_search_roots(
    workspace: Path,
    user_root: Path,
    config: Any = None,
) -> list[SkillSearchRoot]:
    # 按优先级顺序生成搜索根目录：
    # 自定义目录 → 项目目录 → 用户目录 → 内置目录
    config = config or DEFAULT_SKILL_CONFIG
    resolved_workspace = _safe_resolve(workspace)
    roots: list[SkillSearchRoot] = []
    precedence = 0
    for value in getattr(config, "custom_directories", []):
        path = _resolve_custom_path(value, resolved_workspace)
        roots.append(
            SkillSearchRoot(
                path=path,
                origin_type="custom",
                root_name=path.name,
                precedence=precedence,
                discovery_root=str(path),
                discovery_mode="custom_directory",
            )
        )
        precedence += 1
    if getattr(config, "enable_project", True):
        project_roots = _project_skill_roots(resolved_workspace, precedence_start=precedence)
        roots.extend(project_roots)
        precedence += len(project_roots)
        shared_root = _pp_echo_root_skill_root(resolved_workspace, precedence=precedence)
        if shared_root is not None:
            roots.append(shared_root)
            precedence += 1
    if getattr(config, "enable_user", True):
        resolved_user_root = _safe_resolve(user_root)
        roots.append(
            SkillSearchRoot(
                path=resolved_user_root / "skills",
                origin_type="user",
                root_name="user_skills",
                precedence=precedence,
                discovery_root=str(resolved_user_root),
                discovery_mode="user_directory",
            )
        )
        precedence += 1
    if getattr(config, "enable_builtin", True):
        roots.append(
            SkillSearchRoot(
                path=BUILTIN_SKILLS_DIR,
                origin_type="builtin",
                root_name="builtin_skills",
                precedence=precedence,
                discovery_root=str(BUILTIN_SKILLS_DIR),
                discovery_mode="builtin_directory",
            )
        )
    return roots


def _parse_frontmatter(raw: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = _parse_manifest_value(value.strip())
    return data


def _read_frontmatter(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8-sig")
    rows = raw.splitlines()
    if not rows or rows[0].strip() != "---":
        return _fallback_metadata(path, rows)
    lines: list[str] = []
    for line in rows[1:]:
        if line.strip() == "---":
            return _parse_frontmatter("\n".join(lines))
        lines.append(line)
    raise ValueError(f"Skill frontmatter must include name and description: {path}")


def _fallback_metadata(path: Path, rows: list[str]) -> dict[str, Any]:
    description = ""
    for row in rows:
        value = row.strip()
        if not value:
            continue
        if value.startswith("#"):
            description = value.lstrip("#").strip()
            break
        description = value
        break
    return {"name": path.parent.name, "description": description or path.parent.name}


def _parse_skill_metadata(path: Path, root: SkillSearchRoot) -> SkillDescriptor:
    frontmatter = _read_frontmatter(path)
    name = str(frontmatter.get("name", "")).strip()
    description = str(frontmatter.get("description", "")).strip()
    if not name or not description:
        raise ValueError(f"Skill frontmatter must include name and description: {path}")
    manifest_metadata = _manifest_metadata(frontmatter)
    return SkillDescriptor(
        name=name,
        description=description,
        path=path,
        origin_type=root.origin_type,
        root_name=root.root_name,
        precedence=root.precedence,
        declared_by_manifest=root.declared_by_manifest,
        discovery_root=getattr(root, "discovery_root", str(root.path)),
        discovery_mode=getattr(root, "discovery_mode", "workspace_directory"),
        metadata=manifest_metadata,
    )


def _parse_manifest_value(value: str) -> Any:
    """Parse lightweight SKILL.md frontmatter values without requiring YAML."""

    if not value:
        return ""
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            return [item.strip() for item in value.strip("[]").split(",") if item.strip()]
    if "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    try:
        return int(value)
    except ValueError:
        return value


def _manifest_metadata(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """Return trace-safe optional skill manifest metadata."""

    allowed = {
        "version",
        "category",
        "tags",
        "requires_capabilities",
        "optional_capabilities",
        "permissions",
        "context.default_level",
        "context.activation_level",
        "context.max_artifacts",
        "evals",
    }
    metadata: dict[str, Any] = {}
    for key in allowed:
        if key in frontmatter:
            metadata[key] = _safe_manifest_value(frontmatter[key])
    return metadata


def _safe_manifest_value(value: Any) -> Any:
    """Keep manifest metadata JSON-safe and free of secret-like keys."""

    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            if _secret_key(str(key)):
                continue
            safe[str(key)] = _safe_manifest_value(item)
        return safe
    if isinstance(value, list):
        return [_safe_manifest_value(item) for item in value[:50]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in ("secret", "token", "password", "api_key"))


def _skill_is_enabled(name: str, config: Any) -> bool:
    include = getattr(config, "include", [])
    ignored = getattr(config, "ignored", [])
    if include and not any(fnmatch.fnmatch(name, pattern) for pattern in include):
        return False
    if any(fnmatch.fnmatch(name, pattern) for pattern in ignored):
        return False
    return True


def load_skills(
    workspace: Path,
    user_root: Path,
    config: Any = None,
    search_roots: Optional[list[SkillSearchRoot]] = None,
) -> dict[str, SkillDescriptor]:
    config = config or DEFAULT_SKILL_CONFIG
    roots = search_roots or skill_search_roots(workspace, user_root, config=config)
    skills: dict[str, SkillDescriptor] = {}
    for root in reversed(roots):
        if not root.path.exists():
            continue
        for path in sorted(root.path.glob("**/SKILL.md")):
            descriptor = _parse_skill_metadata(path, root)
            if not _skill_is_enabled(descriptor.name, config):
                continue
            skills[descriptor.name] = descriptor
    return skills


def _safe_resolve(path: Path) -> Path:
    candidate = path.expanduser()
    try:
        return candidate.resolve()
    except (OSError, PermissionError):
        return candidate.absolute()


def _resolve_custom_path(value: str, workspace: Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    return _safe_resolve(candidate)


def _project_skill_roots(workspace: Path, *, precedence_start: int = 0) -> list[SkillSearchRoot]:
    roots: list[SkillSearchRoot] = []
    seen_paths: set[Path] = set()
    precedence = precedence_start
    workspace_skills = _safe_resolve(workspace / "skills")
    roots.append(
        SkillSearchRoot(
            path=workspace_skills,
            origin_type="project",
            root_name="workspace_skills",
            precedence=precedence,
            discovery_root=str(workspace),
            discovery_mode="workspace_directory",
        )
    )
    seen_paths.add(workspace_skills)
    precedence += 1
    for directory in _ancestor_directories(workspace):
        for relative_path, root_name in ((".pi/skills", "pi_skills"), (".agents/skills", "agents_skills")):
            candidate = _safe_resolve(directory / relative_path)
            if candidate in seen_paths:
                continue
            seen_paths.add(candidate)
            roots.append(
                SkillSearchRoot(
                    path=candidate,
                    origin_type="project",
                    root_name=root_name,
                    precedence=precedence,
                    discovery_root=str(directory),
                    discovery_mode="ancestor_directory" if directory != workspace else "project_convention",
                )
            )
            precedence += 1
    return roots


def _pp_echo_root_skill_root(workspace: Path, *, precedence: int) -> Optional[SkillSearchRoot]:
    root = _safe_resolve(PP_ECHO_ROOT_SKILLS_DIR)
    workspace_root = _safe_resolve(workspace / "skills")
    if root == workspace_root:
        return None
    return SkillSearchRoot(
        path=root,
        origin_type="shared",
        root_name="pp_echo_root_skills",
        precedence=precedence,
        discovery_root=str(PP_ECHO_ROOT_SKILLS_DIR.parent),
        discovery_mode="pp_echo_root_directory",
    )


def _ancestor_directories(path: Path) -> list[Path]:
    current = _safe_resolve(path)
    ancestors = [current]
    ancestors.extend(current.parents)
    return ancestors
