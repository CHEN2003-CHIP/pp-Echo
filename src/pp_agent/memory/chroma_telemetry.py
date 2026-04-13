from __future__ import annotations

from chromadb.config import System
from chromadb.telemetry.product import ProductTelemetryClient, ProductTelemetryEvent
from overrides import override


class NoOpProductTelemetryClient(ProductTelemetryClient):
    """Disable Chroma product telemetry entirely for local CLI usage."""

    def __init__(self, system: System) -> None:
        super().__init__(system)

    @override
    def capture(self, event: ProductTelemetryEvent) -> None:
        return
