from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / 'src' / 'pp_agent'
ALLOWED = {
    'cli': {'cli', 'runtime', 'domain', 'storage', 'app', 'api'},
    'runtime': {'runtime', 'domain', 'llm', 'tools', 'storage'},
    'storage': {'storage', 'domain', 'llm'},
    'llm': {'llm', 'domain'},
    'domain': {'domain'},
    'tools': {'tools', 'domain', 'storage'},
    'app': {'app', 'runtime', 'storage', 'llm', 'tools', 'domain', 'prompts', 'skills', 'extensions', 'capabilities', 'mcp'},
    'api': {'api', 'runtime', 'storage', 'domain'},
    'prompts': {'prompts'},
    'skills': {'skills'},
    'capabilities': {'capabilities', 'skills', 'tools', 'domain'},
    'mcp': {'mcp'},
    'extensions': {'extensions', 'domain', 'runtime'},
}
EXCLUDED = {
    PACKAGE_ROOT / 'cli' / '_legacy_main_impl.py',
    PACKAGE_ROOT / 'domain' / '_legacy_types_impl.py',
}


def _layer_for(path: Path) -> str | None:
    rel = path.relative_to(PACKAGE_ROOT)
    if len(rel.parts) < 2:
        return None
    layer = rel.parts[0]
    if layer == 'compat':
        return None
    return layer


def test_pp_agent_import_graph_respects_layers() -> None:
    violations: list[str] = []
    for path in PACKAGE_ROOT.rglob('*.py'):
        if path in EXCLUDED:
            continue
        layer = _layer_for(path)
        if layer is None or layer not in ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            module_name = None
            if isinstance(node, ast.ImportFrom) and node.module:
                module_name = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name.startswith('pp_agent.'):
                        target = name.split('.')[1]
                        if target not in ALLOWED[layer]:
                            violations.append(f'{path.relative_to(ROOT)} imports {name}')
                continue
            if not module_name or not module_name.startswith('pp_agent.'):
                continue
            target = module_name.split('.')[1]
            if target not in ALLOWED[layer]:
                violations.append(f'{path.relative_to(ROOT)} imports {module_name}')
    assert not violations, '\n'.join(sorted(violations))
