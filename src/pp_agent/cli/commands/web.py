from __future__ import annotations

from pathlib import Path


def web_main(workspace: Path, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install pp-agent with the 'web' extra to run the web UI.") from exc

    from pp_agent.web.server import create_app

    app = create_app(workspace)
    uvicorn.run(app, host=host, port=port)
