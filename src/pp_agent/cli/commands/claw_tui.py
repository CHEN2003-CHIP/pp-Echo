from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pp_agent.cli.render.runtime import console


def claw_tui_main(workspace: Path) -> int:
    repo_root = Path(__file__).resolve().parents[4]
    binary = _binary_path(repo_root)
    if not binary.exists():
        console.print("Rust claw TUI binary was not found.")
        console.print(f"Expected: {binary}")
        console.print(f"Build it with: cargo build --manifest-path {repo_root / 'rust' / 'Cargo.toml'} -p pp-echo-claw-tui")
        return 1
    env = dict(os.environ)
    env.setdefault("PYTHON", sys.executable)
    completed = subprocess.run(
        [str(binary), "--workspace", str(workspace.resolve(strict=False)), "--python", sys.executable],
        cwd=repo_root,
        env=env,
        check=False,
    )
    return int(completed.returncode)


def _binary_path(repo_root: Path) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return repo_root / "rust" / "target" / "debug" / f"pp-echo-claw-tui{suffix}"


__all__ = ["claw_tui_main"]
