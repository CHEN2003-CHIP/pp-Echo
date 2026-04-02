from __future__ import annotations

from typing import Optional

from pp_agent.capabilities.descriptor import CapabilityDescriptor, CapabilityKind
from pp_agent.capabilities.discovery import CapabilityDiscoveryProvider


CapabilityKey = tuple[str, str]


class CapabilityCatalog:
    """Read-only catalog of discovered capabilities keyed by (kind, name)."""

    def __init__(self, providers: list[CapabilityDiscoveryProvider]) -> None:
        self._providers = list(providers)
        self._snapshot: dict[CapabilityKey, CapabilityDescriptor] = {}
        self._ordered_keys: list[CapabilityKey] = []
        self.refresh()

    def list(self, kind: Optional[CapabilityKind] = None) -> list[CapabilityDescriptor]:
        descriptors: list[CapabilityDescriptor] = []
        for key in self._ordered_keys:
            descriptor = self._snapshot[key]
            if kind is not None and descriptor.kind != kind:
                continue
            descriptors.append(descriptor.model_copy(deep=True))
        return descriptors

    def get(self, kind: CapabilityKind, name: str) -> CapabilityDescriptor:
        return self._snapshot[(kind, name)].model_copy(deep=True)

    def reload(self) -> None:
        for provider in self._providers:
            reload_fn = getattr(provider, "reload", None)
            if callable(reload_fn):
                reload_fn()
        self.refresh()

    def refresh(self) -> None:
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
