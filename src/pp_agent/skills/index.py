from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, PrivateAttr


BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent


class SkillDescriptor(BaseModel):
    """Metadata-only skill descriptor with a lazily materialized body."""

    name: str
    description: str
    path: Path

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


def skill_search_paths(workspace: Path, user_root: Path) -> list[Path]:
    return [
        workspace.resolve() / ".pp-agent" / "skills",
        user_root.resolve() / "skills",
        BUILTIN_SKILLS_DIR,
    ]


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


def _parse_skill_metadata(path: Path) -> SkillDescriptor:
    frontmatter = _read_frontmatter(path)
    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")
    if not name or not description:
        raise ValueError(f"Skill frontmatter must include name and description: {path}")
    return SkillDescriptor(name=name, description=description, path=path)


def load_skills(workspace: Path, user_root: Path) -> dict[str, SkillDescriptor]:
    skills: dict[str, SkillDescriptor] = {}
    for root in reversed(skill_search_paths(workspace, user_root)):
        if not root.exists():
            continue
        for path in sorted(root.glob("**/SKILL.md")):
            descriptor = _parse_skill_metadata(path)
            skills[descriptor.name] = descriptor
    return skills
