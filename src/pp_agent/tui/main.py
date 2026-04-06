from __future__ import annotations

from pathlib import Path
from typing import Optional

from pp_agent.cli.render.runtime import console


def tui_main(workspace: Path, session_id: Optional[str] = None) -> None:
    try:
        from pp_agent.tui.app import run_tui_app
    except ImportError:
        console.print("TUI support requires the optional dependency: pip install -e .[tui]")
        return
    run_tui_app(workspace, session_id=session_id)
