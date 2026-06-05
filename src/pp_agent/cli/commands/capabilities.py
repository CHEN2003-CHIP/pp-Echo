from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pp_agent.api import sdk
from pp_agent.cli.render.runtime import console


VALID_KINDS = {"skill", "builtin_tool", "extension", "mcp_tool", "mcp_resource", "mcp_prompt"}


def capabilities_list_main(workspace: Path, kind: Optional[str] = None, include_mcp: Optional[bool] = None) -> list[dict]:
    payload = sdk.list_capabilities(workspace, kind=kind, include_mcp=include_mcp)
    console.print(json.dumps(payload, ensure_ascii=False, indent=2), soft_wrap=True)
    return payload


def capabilities_show_main(workspace: Path, kind: str, name: str, include_mcp: Optional[bool] = None) -> dict:
    if kind not in VALID_KINDS:
        raise ValueError(f"Unsupported capability kind: {kind}")
    payload = sdk.get_capability(workspace, kind=kind, name=name, include_mcp=include_mcp)
    console.print(json.dumps(payload, ensure_ascii=False, indent=2), soft_wrap=True)
    return payload


def capabilities_reload_main(workspace: Path, include_mcp: Optional[bool] = None) -> list[dict]:
    payload = sdk.reload_capabilities(workspace, include_mcp=include_mcp)
    console.print(json.dumps(payload, ensure_ascii=False, indent=2), soft_wrap=True)
    return payload


__all__ = [
    "capabilities_list_main",
    "capabilities_reload_main",
    "capabilities_show_main",
]
