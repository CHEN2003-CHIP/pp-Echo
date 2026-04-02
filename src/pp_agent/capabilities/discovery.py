from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pp_agent.capabilities.descriptor import CapabilityDescriptor
from pp_agent.mcp import MCPManager
from pp_agent.skills import load_skills
from pp_agent.tools.registry import ToolRegistry


class CapabilityDiscoveryProvider(Protocol):
    def discover(self) -> list[CapabilityDescriptor]:
        ...


@dataclass
class SkillCapabilityDiscoveryProvider:
    workspace: Path
    user_root: Path

    def discover(self) -> list[CapabilityDescriptor]:
        descriptors: list[CapabilityDescriptor] = []
        for skill in load_skills(self.workspace, self.user_root).values():
            descriptors.append(
                CapabilityDescriptor(
                    kind="skill",
                    name=skill.name,
                    description=skill.description,
                    source=f"skill:{skill.path}",
                    path=str(skill.path),
                    risk_level="low",
                    cost_hint="low",
                    discoverability="listed",
                    metadata={"origin": "skill", "body_materialized": False},
                )
            )
        return descriptors


@dataclass
class BuiltinToolCapabilityDiscoveryProvider:
    registry: ToolRegistry

    def discover(self) -> list[CapabilityDescriptor]:
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


@dataclass
class MCPCapabilityDiscoveryProvider:
    manager: MCPManager

    def discover(self) -> list[CapabilityDescriptor]:
        descriptors: list[CapabilityDescriptor] = []
        for server_name in self.manager.server_names():
            for tool in self.manager.list_mcp_tools(server_name):
                descriptors.append(
                    CapabilityDescriptor(
                        kind="mcp_tool",
                        name=self._qualified_name(server_name, tool.name),
                        description=tool.description,
                        source=f"mcp:{server_name}:tool:{tool.name}",
                        risk_level=tool.risk_level,
                        cost_hint="medium" if tool.is_remote else "low",
                        discoverability="listed",
                        metadata={
                            "origin": "mcp_tool",
                            "server_name": server_name,
                            "name": tool.name,
                            "is_remote": tool.is_remote,
                            "requires_auth": tool.requires_auth,
                            "is_destructive": tool.is_destructive,
                            "approval_mode": tool.approval_mode,
                            "input_schema": tool.input_schema,
                        },
                    )
                )
            for resource in self.manager.list_mcp_resources(server_name):
                resource_name = resource.name or resource.uri
                descriptors.append(
                    CapabilityDescriptor(
                        kind="mcp_resource",
                        name=self._qualified_name(server_name, resource_name),
                        description=resource.description,
                        source=f"mcp:{server_name}:resource:{resource.uri}",
                        risk_level=resource.risk_level,
                        cost_hint="medium" if resource.is_remote else "low",
                        discoverability="listed",
                        metadata={
                            "origin": "mcp_resource",
                            "server_name": server_name,
                            "name": resource.name,
                            "uri": resource.uri,
                            "mime_type": resource.mime_type,
                            "is_remote": resource.is_remote,
                            "requires_auth": resource.requires_auth,
                            "approval_mode": resource.approval_mode,
                        },
                    )
                )
            for prompt in self.manager.list_mcp_prompts(server_name):
                descriptors.append(
                    CapabilityDescriptor(
                        kind="mcp_prompt",
                        name=self._qualified_name(server_name, prompt.name),
                        description=prompt.description,
                        source=f"mcp:{server_name}:prompt:{prompt.name}",
                        risk_level=prompt.risk_level,
                        cost_hint="medium" if prompt.is_remote else "low",
                        discoverability="listed",
                        metadata={
                            "origin": "mcp_prompt",
                            "server_name": server_name,
                            "name": prompt.name,
                            "is_remote": prompt.is_remote,
                            "requires_auth": prompt.requires_auth,
                            "approval_mode": prompt.approval_mode,
                            "arguments_schema": prompt.arguments_schema,
                        },
                    )
                )
        return descriptors

    @staticmethod
    def _qualified_name(server_name: str, name: str) -> str:
        return f"{server_name}.{name}"
