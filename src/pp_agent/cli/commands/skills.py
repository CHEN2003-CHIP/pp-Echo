from __future__ import annotations

import json
from pathlib import Path

from pp_agent.api import sdk
from pp_agent.cli.render.runtime import console


def skills_list_main(workspace: Path) -> list[dict]:
    payload = sdk.list_capabilities(workspace, kind="skill")
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def skills_show_main(workspace: Path, name: str) -> dict:
    payload = sdk.get_capability(workspace, kind="skill", name=name)
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


__all__ = ["skills_list_main", "skills_show_main"]
