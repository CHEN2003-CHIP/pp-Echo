from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pp_agent.capabilities.descriptor import CapabilityDescriptor
from pp_agent.skills import load_skills
from pp_agent.tools.registry import ToolRegistry


class CapabilityDiscoveryProvider(Protocol):
    def discover(self) -> list[CapabilityDescriptor]:
        ...


@dataclass
class SkillCapabilityDiscoveryProvider:
    workspace: Path
    user_root: Path
    config: Any = None
    search_roots: list[Any] | None = None

    def discover(self) -> list[CapabilityDescriptor]:
        descriptors: list[CapabilityDescriptor] = []
        for skill in load_skills(self.workspace, self.user_root, config=self.config, search_roots=self.search_roots).values():
            descriptors.append(
                CapabilityDescriptor(
                    kind="skill",
                    name=skill.name,
                    description=skill.description,
                    source=f"skill:{skill.path}",
                    path=str(skill.path),
                    status="discovered",
                    origin_type=skill.origin_type,
                    risk_level="low",
                    cost_hint="low",
                    discoverability="listed",
                    metadata={
                        "origin": "skill",
                        "body_materialized": False,
                        "root_name": skill.root_name,
                        "precedence": skill.precedence,
                        "declared_by_manifest": skill.declared_by_manifest,
                        "discovery_root": skill.discovery_root,
                        "discovery_mode": skill.discovery_mode,
                    },
                )
            )
        return descriptors


@dataclass
class BuiltinToolCapabilityDiscoveryProvider:
    registry: ToolRegistry
    enabled: bool = True

    def discover(self) -> list[CapabilityDescriptor]:
        if not self.enabled:
            return []
        descriptors: list[CapabilityDescriptor] = []
        metadata_map = self.registry.metadata()
        for name, metadata in metadata_map.items():
            spec = self.registry.get_spec(name)
            descriptors.append(
                CapabilityDescriptor(
                    kind="builtin_tool",
                    name=name,
                    description=spec.description,
                    source=f"builtin:{name}",
                    status="loaded",
                    origin_type="builtin",
                    risk_level=self._risk_level_for(metadata.category, spec.requires_confirmation),
                    cost_hint=self._cost_hint_for(metadata.category),
                    discoverability="listed",
                    metadata={
                        "origin": "builtin_tool",
                        "category": metadata.category,
                        "requires_confirmation": spec.requires_confirmation,
                    },
                )
            )
        return descriptors

    @staticmethod
    def _risk_level_for(category: str, requires_confirmation: bool) -> str:
        if requires_confirmation or category in {"repo", "shell"}:
            return "medium"
        return "low"

    @staticmethod
    def _cost_hint_for(category: str) -> str:
        if category in {"repo", "shell"}:
            return "medium"
        return "low"
