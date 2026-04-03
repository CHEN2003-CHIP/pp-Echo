from __future__ import annotations

from importlib import import_module
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.state import AgentState


@dataclass
class ActiveSkill:
    name: str
    description: str
    source: str
    body_loaded: bool
    origin_type: str
    discovery_root: str | None
    discovery_mode: str


@dataclass
class SkillRuntime:
    workspace: Path
    user_root: Path
    config: object
    search_roots: Optional[list[object]] = None
    _skills: Optional[dict[str, object]] = field(default=None, init=False, repr=False)
    _manual_active: list[str] = field(default_factory=list, init=False, repr=False)
    _last_auto_active: list[str] = field(default_factory=list, init=False, repr=False)
    _last_match_sources: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def available_skills(self) -> dict[str, object]:
        if self._skills is None:
            self._skills = _load_skills(
                self.workspace,
                self.user_root,
                config=self.config,
                search_roots=self.search_roots,
            )
        return self._skills

    def reload(self) -> None:
        self._skills = None
        self._manual_active = []
        self._last_auto_active = []
        self._last_match_sources = {}

    def use_skill(self, name: str, *, source: str = "manual"):
        descriptor = self.available_skills()[name]
        if name not in self._manual_active:
            self._manual_active.append(name)
        self._last_match_sources[name] = source
        return descriptor

    def clear_active(self) -> None:
        self._manual_active = []
        self._last_auto_active = []
        self._last_match_sources = {}

    def active_skills(self) -> list[ActiveSkill]:
        active_names = list(dict.fromkeys([*self._manual_active, *self._last_auto_active]))
        skills = self.available_skills()
        items: list[ActiveSkill] = []
        for name in active_names:
            descriptor = skills.get(name)
            if descriptor is None:
                continue
            items.append(
                ActiveSkill(
                    name=name,
                    description=descriptor.description,
                    source=self._last_match_sources.get(name, "manual" if name in self._manual_active else "automatic"),
                    body_loaded=getattr(descriptor, "_body_cache", None) is not None,
                    origin_type=descriptor.origin_type,
                    discovery_root=getattr(descriptor, "discovery_root", None),
                    discovery_mode=getattr(descriptor, "discovery_mode", "legacy_project"),
                )
            )
        return items

    def transform_context(self, state: AgentState, messages: list[ChatMessage]) -> list[ChatMessage]:
        descriptors = self._active_descriptors_for_state(state)
        if not descriptors:
            return messages

        lines = ["Active skills loaded for this turn:"]
        for descriptor in descriptors:
            source = self._last_match_sources.get(descriptor.name, "automatic")
            lines.append(f"- {descriptor.name} ({source})")
        for descriptor in descriptors:
            lines.append("")
            lines.append(f"[Skill: {descriptor.name}]")
            lines.append(_materialize_skill(descriptor))

        skill_message = ChatMessage(
            role="system",
            content=[TextPart(text="\n".join(lines).strip())],
            timestamp=time.time(),
        )
        if not messages:
            return [skill_message]
        return [messages[0], skill_message, *messages[1:]]

    def _active_descriptors_for_state(self, state: AgentState) -> list[object]:
        auto_matches = self._auto_matches(state)
        self._last_auto_active = auto_matches
        active_names = list(dict.fromkeys([*self._manual_active, *auto_matches]))
        skills = self.available_skills()
        return [skills[name] for name in active_names if name in skills]

    def _auto_matches(self, state: AgentState) -> list[str]:
        text = self._latest_user_text(state)
        if not text:
            self._last_match_sources = {name: "manual" for name in self._manual_active}
            return []

        skills = self.available_skills()
        lowered = text.lower()
        explicit: list[tuple[int, str]] = []
        for descriptor in skills.values():
            position = _mention_position(lowered, descriptor.name)
            if position is not None:
                explicit.append((position, descriptor.name))
        if explicit:
            ordered = [name for _, name in sorted(explicit, key=lambda item: (item[0], item[1]))[:2]]
            self._last_match_sources = {name: "manual" for name in self._manual_active}
            self._last_match_sources.update({name: "explicit_name" for name in ordered})
            return ordered

        user_terms = _match_terms(text)
        candidates: list[tuple[float, str]] = []
        for descriptor in skills.values():
            name_terms = _name_terms(descriptor.name)
            description_terms = _description_terms(descriptor.description)
            overlap = len(description_terms & user_terms)
            name_overlap = len(name_terms & user_terms)
            score = float(overlap) + (float(name_overlap) * 2.0)
            if len(description_terms & user_terms) >= 2:
                score += 1.0
            phrase_bonus = _phrase_bonus(text, descriptor.description)
            score += phrase_bonus
            if score < 2.0:
                continue
            candidates.append((score, descriptor.name))
        ordered = [name for _, name in sorted(candidates, key=lambda item: (-item[0], item[1]))[:2]]
        self._last_match_sources = {name: "manual" for name in self._manual_active}
        self._last_match_sources.update({name: "description_match" for name in ordered})
        return ordered

    @staticmethod
    def _latest_user_text(state: AgentState) -> str:
        for message in reversed(state.messages):
            if message.role != "user":
                continue
            parts = [part.text.strip() for part in message.content if getattr(part, "text", "").strip()]
            if parts:
                return " ".join(parts)
        return ""


def _match_terms(text: str) -> set[str]:
    return {_normalize_term(item) for item in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(item) >= 3}


def _description_terms(text: str) -> set[str]:
    stopwords = {"the", "and", "for", "with", "that", "this", "into", "from", "your", "using"}
    return {item for item in _match_terms(text) if item not in stopwords}


def _name_terms(text: str) -> set[str]:
    return {item for item in _match_terms(text.replace("-", " ").replace("_", " ")) if len(item) >= 3}


def _mention_position(text: str, name: str) -> Optional[int]:
    variants = {
        name.lower(),
        name.lower().replace("_", " "),
        name.lower().replace("-", " "),
        name.lower().replace("_", "-"),
    }
    positions = [text.find(variant) for variant in variants if variant and text.find(variant) >= 0]
    if not positions:
        return None
    return min(positions)


def _phrase_bonus(text: str, description: str) -> float:
    normalized_text = " ".join(sorted(_match_terms(text)))
    normalized_desc = " ".join(sorted(_description_terms(description)))
    if not normalized_text or not normalized_desc:
        return 0.0
    shared = len(set(normalized_text.split()) & set(normalized_desc.split()))
    return 0.5 if shared >= 3 else 0.0


def _normalize_term(term: str) -> str:
    value = term.lower()
    if value.endswith("ies") and len(value) > 4:
        return value[:-3] + "y"
    if value.endswith("ing") and len(value) > 5:
        return value[:-3]
    if value.endswith("ed") and len(value) > 4:
        return value[:-2]
    if value.endswith("es") and len(value) > 4:
        return value[:-2]
    if value.endswith("s") and len(value) > 3:
        return value[:-1]
    return value


def _load_skills(workspace: Path, user_root: Path, *, config: object, search_roots: Optional[list[object]] = None) -> dict[str, object]:
    loader = import_module("pp_agent.skills")
    return loader.load_skills(workspace, user_root, config=config, search_roots=search_roots)


def _materialize_skill(descriptor: object) -> str:
    loader = import_module("pp_agent.skills")
    return loader.materialize_skill(descriptor)


__all__ = ["ActiveSkill", "SkillRuntime", "_materialize_skill"]
