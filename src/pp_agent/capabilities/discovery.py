from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol

from pp_agent.capabilities.descriptor import CapabilityDescriptor
from pp_agent.skills import load_skills
from pp_agent.tools.registry import ToolRegistry


class CapabilityDiscoveryProvider(Protocol):
    """
    Minimal discovery boundary for governance inventory providers.

    Implementations describe available capabilities only; they must not execute
    tools, load skill bodies, or replace the owning runtime component.
    """

    def discover(self) -> list[CapabilityDescriptor]:
        ...


@dataclass
class SkillCapabilityDiscoveryProvider:
    """Discover skill descriptors through the existing skill loader."""

    workspace: Path
    user_root: Path
    config: Any = None
    search_roots: Optional[list[Any]] = None

    def discover(self) -> list[CapabilityDescriptor]:
        """
        Discover skill package descriptors without materializing skill bodies.

        Skill metadata is emitted directly as v2 descriptor fields so catalog
        consumers do not need legacy discovery adapters.
        """
        descriptors: list[CapabilityDescriptor] = []
        for skill in load_skills(self.workspace, self.user_root, config=self.config, search_roots=self.search_roots).values():
            descriptors.append(
                CapabilityDescriptor(
                    kind="skill",
                    id=f"skill.{skill.name}",
                    name=skill.name,
                    display_name=skill.name,
                    description=skill.description,
                    source=f"skill:{skill.path}",
                    source_kind="skill_package",
                    status="discovered",
                    risk_level="safe",
                    cost_hint="low",
                    latency_hint="fast",
                    discoverability="listed",
                    tags=["skill", skill.origin_type],
                    metadata={
                        "origin": "skill",
                        "path": str(skill.path),
                        "origin_type": skill.origin_type,
                        "body_materialized": False,
                        "root_name": skill.root_name,
                        "precedence": skill.precedence,
                        "declared_by_manifest": skill.declared_by_manifest,
                        "discovery_root": skill.discovery_root,
                        "discovery_mode": skill.discovery_mode,
                        "manifest": dict(skill.metadata),
                    },
                )
            )
        return descriptors


@dataclass
class BuiltinToolCapabilityDiscoveryProvider:
    """Expose ToolRegistry registrations as governance descriptors."""

    registry: ToolRegistry
    enabled: bool = True

    def discover(self) -> list[CapabilityDescriptor]:
        """
        Snapshot ToolRegistry registrations as builtin tool capabilities.

        ToolRegistry stays responsible for execution; this provider only
        translates its stable spec and metadata into governance descriptors for
        listing, routing, and trace selection.
        """
        if not self.enabled:
            return []
        descriptors: list[CapabilityDescriptor] = []
        metadata_map = self.registry.metadata()
        for name, metadata in metadata_map.items():
            spec = self.registry.get_spec(name)
            descriptors.append(
                CapabilityDescriptor(
                    kind="builtin_tool",
                    id=name,
                    name=name,
                    display_name=name,
                    description=spec.description,
                    source=f"builtin:{name}",
                    source_kind="builtin",
                    input_schema=spec.parameters,
                    status="loaded",
                    risk_level=self._risk_level_for(metadata.category, spec.requires_confirmation),
                    permissions_required=[spec.permission_domain],
                    effects=self._effects_for(metadata.category, spec.requires_confirmation),
                    tags=["tool", metadata.category, metadata.tool_family or ""],
                    cost_hint=self._cost_hint_for(metadata.category),
                    latency_hint="normal" if metadata.category in {"repo", "shell"} else "fast",
                    discoverability="listed",
                    metadata={
                        "origin": "builtin_tool",
                        "category": metadata.category,
                        "tool_family": metadata.tool_family,
                        "requires_confirmation": spec.requires_confirmation,
                        "model_callable": spec.model_callable,
                    },
                )
            )
        return descriptors

    @staticmethod
    def _risk_level_for(category: str, requires_confirmation: bool) -> str:
        """Map current tool categories to v2 capability risk labels."""
        if category == "shell":
            return "shell"
        if requires_confirmation and category in {"repo", "files"}:
            return "write"
        if category == "mcp" and requires_confirmation:
            return "network"
        if category in {"repo", "files", "attachments", "memory"}:
            return "read"
        return "safe"

    @staticmethod
    def _cost_hint_for(category: str) -> str:
        if category in {"repo", "shell"}:
            return "medium"
        return "low"

    @staticmethod
    def _effects_for(category: str, requires_confirmation: bool) -> list[str]:
        if category == "shell":
            return ["shell_command"]
        if requires_confirmation:
            return ["workspace_write"]
        return ["inspect"]


@dataclass
class SubAgentCapabilityDiscoveryProvider:
    """Expose SubAgent catalog entries without changing delegated execution."""

    catalog: Optional[Any] = None

    def discover(self) -> list[CapabilityDescriptor]:
        """Expose configured SubAgent specs as delegated-run capabilities."""
        descriptors: list[CapabilityDescriptor] = []
        catalog_cls = importlib.import_module("pp_agent.subagents.catalog").SubAgentCatalog
        for spec in (self.catalog or catalog_cls()).list():
            descriptors.append(
                CapabilityDescriptor(
                    id=f"subagent.{spec.name}",
                    kind="subagent",
                    name=spec.name,
                    display_name=spec.name,
                    description=spec.description,
                    source=f"subagent:{spec.name}",
                    source_kind="subagent",
                    risk_level="read",
                    permissions_required=list(spec.tool_allowlist),
                    effects=["delegated_run"],
                    tags=["subagent"],
                    cost_hint="medium",
                    latency_hint="slow",
                    metadata={
                        "origin": "subagent",
                        "max_turns": spec.max_turns,
                        "return_format": spec.return_format,
                        "require_plan_approval": spec.require_plan_approval,
                    },
                )
            )
        return descriptors


@dataclass
class BotConnectorCapabilityDiscoveryProvider:
    """Expose Bot Center connectors as governed network ingress capabilities."""

    workspace: Path

    def discover(self) -> list[CapabilityDescriptor]:
        """Expose Bot Center connector configs as governance capabilities."""
        descriptors: list[CapabilityDescriptor] = []
        bot_registry_cls = importlib.import_module("pp_agent.bots.registry").BotRegistry
        for config in bot_registry_cls(self.workspace).list_configs(readonly=True):
            descriptors.append(
                CapabilityDescriptor(
                    id=f"connector.{config.id}",
                    kind="connector",
                    name=config.id,
                    display_name=config.name,
                    description=config.description or f"{config.platform} bot connector",
                    source=f"connector:{config.platform}:{config.id}",
                    source_kind="connector",
                    risk_level="network",
                    permissions_required=["network"],
                    effects=["external_message_ingress"],
                    tags=["connector", config.platform, config.type],
                    status="enabled" if config.enabled else "disabled",
                    cost_hint="unknown",
                    latency_hint="normal",
                    discoverability="listed" if config.enabled else "disabled",
                    metadata={
                        "origin": "connector",
                        "platform": config.platform,
                        "type": config.type,
                        "runtime_id": config.runtime_id,
                        "model_provider_id": config.model_provider_id,
                        "model_id": config.model_id,
                    },
                )
            )
        return descriptors
