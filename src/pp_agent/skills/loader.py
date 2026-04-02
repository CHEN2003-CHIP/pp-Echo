from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class SkillDescriptor(BaseModel):
    name: str
    description: str
    path: Path
    body: str


BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent


def skill_search_paths(workspace: Path, user_root: Path) -> list[Path]:
    return [
        workspace.resolve() / '.pp-agent' / 'skills',
        user_root.resolve() / 'skills',
        BUILTIN_SKILLS_DIR,
    ]


def _parse_frontmatter(raw: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in raw.splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        data[key.strip()] = value.strip()
    return data


def _parse_skill(path: Path) -> SkillDescriptor:
    text = path.read_text(encoding='utf-8')
    frontmatter: dict[str, str] = {}
    body = text
    if text.startswith('---\n'):
        parts = text.split('---\n', 2)
        if len(parts) == 3:
            _, raw_frontmatter, body = parts
            frontmatter = _parse_frontmatter(raw_frontmatter)
    name = frontmatter.get('name', '')
    description = frontmatter.get('description', '')
    if not name or not description:
        raise ValueError(f'Skill frontmatter must include name and description: {path}')
    return SkillDescriptor(name=name, description=description, path=path, body=body.strip())


def load_skills(workspace: Path, user_root: Path) -> dict[str, SkillDescriptor]:
    skills: dict[str, SkillDescriptor] = {}
    for root in reversed(skill_search_paths(workspace, user_root)):
        if not root.exists():
            continue
        for path in sorted(root.glob('**/SKILL.md')):
            descriptor = _parse_skill(path)
            skills[descriptor.name] = descriptor
    return skills
