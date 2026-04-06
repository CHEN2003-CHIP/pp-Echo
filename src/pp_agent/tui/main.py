from __future__ import annotations

from pathlib import Path
from typing import Optional


def tui_main(workspace: Path, session_id: Optional[str] = None) -> None:
    from pp_agent.tui.app import run_tui_app

    run_tui_app(workspace, session_id=session_id)
