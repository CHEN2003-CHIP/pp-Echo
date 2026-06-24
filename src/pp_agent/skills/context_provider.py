from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any, Optional

from pp_agent.skills.index import SkillDescriptor
from pp_agent.skills.materializer import materialize_skill


ALLOWED_ARTIFACT_DIRS = {"references", "templates", "scripts"}


class SkillArtifactAccessError(ValueError):
    """Raised when a requested skill artifact path is outside the allowed skill tree."""


class SkillContextProvider:
    """Progressively discloses skill context as ContextItems without changing skill loading."""

    def __init__(self, skills: dict[str, SkillDescriptor]) -> None:
        self.skills = dict(skills)

    def list_level0(self) -> list[Any]:
        """Return metadata-only skill cards without materializing SKILL.md bodies."""

        items: list[Any] = []
        for skill in sorted(self.skills.values(), key=lambda item: item.name):
            content = (
                f"Skill: {skill.name}\n"
                f"Description: {skill.description}\n"
                f"Origin: {skill.origin_type}\n"
                f"Root: {skill.root_name or ''}\n"
                f"Discovery mode: {skill.discovery_mode}"
            ).strip()
            items.append(
                _context_item(
                    id=f"skill:{skill.name}:level0",
                    type="skill",
                    title=f"Skill {skill.name}",
                    content=content,
                    source_ref=_source_ref(source_type="skill", source_id=f"skill:{skill.name}", path=str(skill.path)),
                    priority=55,
                    metadata={
                        "context_provider": "skill",
                        "skill_name": skill.name,
                        "level": 0,
                        "origin_type": skill.origin_type,
                        "root_name": skill.root_name,
                        "discovery_mode": skill.discovery_mode,
                        **_safe_metadata(skill.metadata),
                    },
                )
            )
        return items

    def load_level1(self, skill_name: str) -> Any:
        """Materialize one SKILL.md body as an explicit level 1 ContextItem."""

        skill = self._require_skill(skill_name)
        body = materialize_skill(skill)
        return _context_item(
            id=f"skill:{skill.name}:level1",
            type="skill",
            title=f"Skill {skill.name} instructions",
            content=body,
            source_ref=_source_ref(source_type="skill", source_id=f"skill:{skill.name}", path=str(skill.path)),
            priority=80,
            metadata={
                "context_provider": "skill",
                "skill_name": skill.name,
                "level": 1,
                "body_materialized": True,
                **_safe_metadata(skill.metadata),
            },
        )

    def load_level2(self, skill_name: str, relative_path: str) -> Any:
        """Read one allowed skill artifact under references/, templates/, or scripts/."""

        skill = self._require_skill(skill_name)
        path = self._resolve_artifact_path(skill, relative_path)
        content = path.read_text(encoding="utf-8-sig")
        return _context_item(
            id=f"skill:{skill.name}:level2:{path.relative_to(skill.path.parent).as_posix()}",
            type="skill",
            title=f"Skill {skill.name} artifact {relative_path}",
            content=content,
            source_ref=_source_ref(source_type="skill", source_id=f"skill:{skill.name}", path=str(path)),
            priority=75,
            metadata={
                "context_provider": "skill",
                "skill_name": skill.name,
                "level": 2,
                "relative_path": path.relative_to(skill.path.parent).as_posix(),
                **_safe_metadata(skill.metadata),
            },
        )

    def _require_skill(self, skill_name: str) -> SkillDescriptor:
        """Return a known skill descriptor or raise a stable KeyError."""

        try:
            return self.skills[skill_name]
        except KeyError as exc:
            raise KeyError(f"Unknown skill: {skill_name}") from exc

    def _resolve_artifact_path(self, skill: SkillDescriptor, relative_path: str) -> Path:
        """Resolve and validate a level 2 artifact path inside the skill directory."""

        raw = Path(relative_path)
        if raw.is_absolute() or not raw.parts:
            raise SkillArtifactAccessError("skill_artifact_path_denied")
        first = raw.parts[0]
        if first not in ALLOWED_ARTIFACT_DIRS:
            raise SkillArtifactAccessError("skill_artifact_path_denied")
        root = skill.path.parent.resolve()
        target = (root / raw).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise SkillArtifactAccessError("skill_artifact_path_denied") from exc
        if not target.is_file():
            raise FileNotFoundError(relative_path)
        return target


def _safe_metadata(metadata: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Copy trace-safe metadata while dropping secret-like keys."""

    safe: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if _secret_key(str(key)):
            continue
        if isinstance(value, dict):
            safe[str(key)] = _safe_metadata(value)
        elif isinstance(value, list):
            safe[str(key)] = [_safe_scalar(item) for item in value[:50]]
        else:
            safe[str(key)] = _safe_scalar(value)
    return safe


def _safe_scalar(value: Any) -> Any:
    """Return a JSON-safe scalar representation for ContextItem metadata."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in ("secret", "token", "password", "api_key"))


def _context_item(**kwargs: Any) -> Any:
    """Construct ContextItem lazily to preserve skill module import boundaries."""

    return import_module("pp_agent.context.item").ContextItem(**kwargs)


def _source_ref(**kwargs: Any) -> Any:
    """Construct SourceRef lazily to preserve skill module import boundaries."""

    return import_module("pp_agent.context.source_ref").SourceRef(**kwargs)
