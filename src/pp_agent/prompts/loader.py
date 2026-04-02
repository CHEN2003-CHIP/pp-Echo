from __future__ import annotations

from pathlib import Path


BUILTIN_PROMPTS_DIR = Path(__file__).resolve().parent


def prompt_search_paths(workspace: Path, user_root: Path) -> list[Path]:
    return [
        workspace.resolve() / '.pp-agent' / 'prompts',
        user_root.resolve() / 'prompts',
        BUILTIN_PROMPTS_DIR,
    ]


def load_prompt_templates(workspace: Path, user_root: Path) -> dict[str, str]:
    templates: dict[str, str] = {}
    for root in reversed(prompt_search_paths(workspace, user_root)):
        if not root.exists():
            continue
        for path in sorted(root.glob('*.md')):
            templates[path.stem] = path.read_text(encoding='utf-8')
    return templates
