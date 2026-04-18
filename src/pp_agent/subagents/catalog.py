from __future__ import annotations

from typing import Iterable, Optional

from pp_agent.subagents.specs import SubAgentSpec, default_subagent_specs


class SubAgentCatalog:
    """Registry for built-in and caller-provided subagent specs."""

    def __init__(self, specs: Optional[dict[str, SubAgentSpec]] = None) -> None:
        seed = specs or default_subagent_specs()
        self._specs: dict[str, SubAgentSpec] = {}
        for spec in seed.values():
            self.register(spec)

    def register(self, spec: SubAgentSpec, *, replace: bool = False) -> None:
        if not replace and spec.name in self._specs:
            raise ValueError(f"Subagent '{spec.name}' is already registered.")
        self._specs[spec.name] = spec.model_copy(deep=True)

    def get(self, name: str) -> Optional[SubAgentSpec]:
        spec = self._specs.get(name)
        return spec.model_copy(deep=True) if spec is not None else None

    def list(self) -> list[SubAgentSpec]:
        return [spec.model_copy(deep=True) for spec in self._specs.values()]

    def names(self) -> list[str]:
        return list(self._specs)

    def replace_all(self, specs: Iterable[SubAgentSpec]) -> None:
        self._specs = {}
        for spec in specs:
            self.register(spec)
