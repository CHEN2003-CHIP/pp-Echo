from __future__ import annotations

from pp_agent.skills.index import SkillDescriptor


def materialize_skill(descriptor: SkillDescriptor) -> str:
    """Load and cache a skill body only when a caller explicitly needs it."""

    cached = descriptor._body_cache
    if cached is not None:
        return cached

    text = descriptor.path.read_text(encoding="utf-8-sig")
    body = text
    rows = text.splitlines()
    if rows and rows[0].strip() == "---":
        for index, row in enumerate(rows[1:], start=1):
            if row.strip() == "---":
                body = "\n".join(rows[index + 1 :])
                break
    return descriptor.cache_body(body.strip())
