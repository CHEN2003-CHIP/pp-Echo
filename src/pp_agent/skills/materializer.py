from __future__ import annotations

from pp_agent.skills.index import SkillDescriptor


def materialize_skill(descriptor: SkillDescriptor) -> str:
    """Load and cache a skill body only when a caller explicitly needs it."""

    cached = descriptor._body_cache
    if cached is not None:
        return cached

    text = descriptor.path.read_text(encoding="utf-8")
    body = text
    if text.startswith("---\n"):
        parts = text.split("---\n", 2)
        if len(parts) == 3:
            _, _, body = parts
    return descriptor.cache_body(body.strip())
