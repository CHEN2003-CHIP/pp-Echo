from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtensionRegistry:
    items: dict[str, Any] = field(default_factory=dict)

    def register(self, name: str, value: Any) -> None:
        self.items[name] = value

    def get(self, name: str) -> Any:
        return self.items.get(name)
