from __future__ import annotations

from pathlib import Path
from typing import Optional


BUILTIN_PROMPTS_DIR = Path(__file__).resolve().parent


def prompt_search_paths(workspace: Path, user_root: Path, extra_paths: Optional[list[Path]] = None) -> list[Path]:
    paths = [
        workspace.resolve() / '.pp-agent' / 'prompts',
        user_root.resolve() / 'prompts',
        BUILTIN_PROMPTS_DIR,
    ]
    for path in extra_paths or []:
        candidate = _safe_resolve(path)
        if candidate not in paths:
            paths.append(candidate)
    return paths


def load_prompt_templates(workspace: Path, user_root: Path, extra_paths: Optional[list[Path]] = None) -> dict[str, str]:
    templates: dict[str, str] = {}
    for root in reversed(prompt_search_paths(workspace, user_root, extra_paths=extra_paths)):
        if not root.exists():
            continue
        for path in sorted(root.glob('*.md')):
            templates[path.stem] = path.read_text(encoding='utf-8')
    return templates


def _safe_resolve(path: Path) -> Path:
    candidate = path.expanduser()
    try:
        return candidate.resolve()
    except (OSError, PermissionError):
        return candidate.absolute()
