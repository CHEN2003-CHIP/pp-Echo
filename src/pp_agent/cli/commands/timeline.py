from __future__ import annotations

from pathlib import Path
from typing import Optional

from pp_agent.app.bootstrap import timeline_store_for
from pp_agent.cli.commands.sessions import resolve_session_id
from pp_agent.cli.render.runtime import load_timeline_entries
from pp_agent.cli.render.timeline import render_timeline


def timeline_show_main(workspace: Path, session_id: Optional[str] = None, limit: int = 30) -> None:
    store = timeline_store_for(workspace)
    if session_id:
        try:
            session_id = resolve_session_id(workspace, session_id)
        except (FileNotFoundError, ValueError):
            pass
    entries = load_timeline_entries(store, session_id, limit)
    render_timeline(entries)


__all__ = ["timeline_show_main"]
