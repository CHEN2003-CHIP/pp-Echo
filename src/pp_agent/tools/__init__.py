from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name != "ToolRegistry":
        raise AttributeError(name)
    from pp_agent.tools.registry import ToolRegistry

    globals()[name] = ToolRegistry
    return ToolRegistry


__all__ = ["ToolRegistry"]
