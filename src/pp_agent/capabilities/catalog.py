from __future__ import annotations

from typing import Optional

from pp_agent.capabilities.descriptor import CapabilityDescriptor, CapabilityKind
from pp_agent.capabilities.discovery import CapabilityDiscoveryProvider


CapabilityKey = tuple[str, str]


class CapabilityCatalog:
    """
    Read-only catalog of discovered capabilities keyed by (kind, name).

    The catalog is the governance inventory boundary: discovery providers feed
    descriptors into it, while execution remains owned by ToolRegistry, MCP,
    Skill loader, Bot Center, and AgentRuntime.
    """

    def __init__(self, providers: list[CapabilityDiscoveryProvider]) -> None:
        """
        Build an initial immutable snapshot from the configured providers.

        Providers are copied so later caller-side list mutations do not change
        which discovery sources participate in this catalog instance.
        """
        self._providers = list(providers)
        self._snapshot: dict[CapabilityKey, CapabilityDescriptor] = {}
        self._ordered_keys: list[CapabilityKey] = []
        self.refresh()

    def list(self, kind: Optional[CapabilityKind] = None) -> list[CapabilityDescriptor]:
        """Return deep descriptor copies in discovery order, optionally filtered by kind."""
        descriptors: list[CapabilityDescriptor] = []
        for key in self._ordered_keys:
            descriptor = self._snapshot[key]
            if kind is not None and descriptor.kind != kind:
                continue
            descriptors.append(descriptor.model_copy(deep=True))
        return descriptors

    def get(self, kind: CapabilityKind, name: str) -> CapabilityDescriptor:
        """Return a deep copy of one descriptor by its governance key."""
        return self._snapshot[(kind, name)].model_copy(deep=True)

    def reload(self) -> None:
        """Ask reloadable providers to refresh their source state, then rebuild the snapshot."""
        for provider in self._providers:
            reload_fn = getattr(provider, "reload", None)
            if callable(reload_fn):
                reload_fn()
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the descriptor snapshot and reject duplicate governance keys."""
        next_snapshot: dict[CapabilityKey, CapabilityDescriptor] = {}
        next_ordered_keys: list[CapabilityKey] = []

        for provider in self._providers:
            descriptors = provider.discover()
            for descriptor in descriptors:
                key = (descriptor.kind, descriptor.name)
                if key in next_snapshot:
                    raise ValueError(f"Duplicate capability discovered for key {key!r}")
                next_snapshot[key] = descriptor
                next_ordered_keys.append(key)

        self._snapshot = next_snapshot
        self._ordered_keys = next_ordered_keys
