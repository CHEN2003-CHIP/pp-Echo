from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, PrivateAttr


BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent


class SkillDescriptor(BaseModel):
    """Metadata-only skill descriptor with a lazily materialized body."""

    name: str
    description: str
    path: Path
    origin_type: str = "project"
    root_name: Optional[str] = None
    precedence: int = 0
    declared_by_manifest: bool = False

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
    precedence: int = 0
    declared_by_manifest: bool = False


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
    config = config or DEFAULT_SKILL_CONFIG
    roots: list[SkillSearchRoot] = []
    precedence = 0
    for value in getattr(config, "custom_directories", []):
        path = Path(value).expanduser()
        roots.append(SkillSearchRoot(path=path, origin_type="custom", root_name=path.name, precedence=precedence))
        precedence += 1
    if getattr(config, "enable_project", True):
        roots.append(
            SkillSearchRoot(
                path=_safe_resolve(workspace) / ".pp-agent" / "skills",
                origin_type="project",
                root_name="project_skills",
                precedence=precedence,
            )
        )
        precedence += 1
    if getattr(config, "enable_user", True):
        roots.append(
            SkillSearchRoot(
                path=_safe_resolve(user_root) / "skills",
                origin_type="user",
                root_name="user_skills",
                precedence=precedence,
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
            )
        )
    return roots


def _parse_frontmatter(raw: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def _read_frontmatter(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8") as handle:
        if handle.readline() != "---\n":
            raise ValueError(f"Skill frontmatter must include name and description: {path}")

        lines: list[str] = []
        for line in handle:
            if line == "---\n":
                break
            lines.append(line)
        else:
            raise ValueError(f"Skill frontmatter must include name and description: {path}")

    return _parse_frontmatter("".join(lines))


def _parse_skill_metadata(path: Path, root: SkillSearchRoot) -> SkillDescriptor:
    frontmatter = _read_frontmatter(path)
    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")
    if not name or not description:
        raise ValueError(f"Skill frontmatter must include name and description: {path}")
    return SkillDescriptor(
        name=name,
        description=description,
        path=path,
        origin_type=root.origin_type,
        root_name=root.root_name,
        precedence=root.precedence,
        declared_by_manifest=root.declared_by_manifest,
    )


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
