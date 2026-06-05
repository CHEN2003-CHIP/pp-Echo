from __future__ import annotations

import sys
from pathlib import Path


if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / "src"))

from pp_agent.evaluation.runner import main


if __name__ == "__main__":
    raise SystemExit(main())
