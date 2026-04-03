from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pp_agent.extensions.descriptor import ExtensionDescriptor


@dataclass
class ExtensionRuntimeBinding:
    descriptor: ExtensionDescriptor
    status: str = "discovered"
    error: Optional[str] = None
    loaded_tools: list[str] = field(default_factory=list)
    loaded_commands: list[str] = field(default_factory=list)
    loaded_resources: list[str] = field(default_factory=list)
    hook_counts: dict[str, int] = field(default_factory=dict)
    event_counts: dict[str, int] = field(default_factory=dict)
    resource_roots: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class ExtensionRegistry:
    items: dict[str, ExtensionRuntimeBinding] = field(default_factory=dict)

    def register(self, descriptor: ExtensionDescriptor, *, status: str = "discovered", error: Optional[str] = None) -> None:
        existing = self.items.get(descriptor.name)
        if existing is None:
            self.items[descriptor.name] = ExtensionRuntimeBinding(descriptor=descriptor, status=status, error=error)
            return
        existing.descriptor = descriptor
        existing.status = status
        existing.error = error

    def mark_loaded(
        self,
        name: str,
        *,
        loaded_tools: Optional[list[str]] = None,
        loaded_commands: Optional[list[str]] = None,
        loaded_resources: Optional[list[str]] = None,
        hook_counts: Optional[dict[str, int]] = None,
        event_counts: Optional[dict[str, int]] = None,
        resource_roots: Optional[dict[str, list[str]]] = None,
    ) -> None:
        binding = self.items[name]
        binding.status = "loaded"
        if loaded_tools is not None:
            binding.loaded_tools = list(loaded_tools)
        if loaded_commands is not None:
            binding.loaded_commands = list(loaded_commands)
        if loaded_resources is not None:
            binding.loaded_resources = list(loaded_resources)
        if hook_counts is not None:
            binding.hook_counts = dict(hook_counts)
        if event_counts is not None:
            binding.event_counts = dict(event_counts)
        if resource_roots is not None:
            binding.resource_roots = {key: list(values) for key, values in resource_roots.items()}

    def mark_errored(self, name: str, error: str) -> None:
        binding = self.items[name]
        binding.status = "errored"
        binding.error = error

    def clear(self) -> None:
        self.items.clear()

    def list(self) -> list[ExtensionRuntimeBinding]:
        return [self.items[name] for name in sorted(self.items)]

    def get(self, name: str) -> Optional[ExtensionRuntimeBinding]:
        return self.items.get(name)
