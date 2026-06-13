from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / 'src' / 'pp_agent'
ALLOWED = {
    'cli': {'cli', 'runtime', 'domain', 'storage', 'app', 'api', 'config', 'evaluation', 'learning', 'memory', 'skills', 'tools', 'tui', 'web', 'web_tools', 'onboarding'},
    'runtime': {'runtime', 'domain', 'llm', 'tools', 'storage', 'config', 'memory', 'subagents', 'observability'},
    'storage': {'storage', 'domain', 'llm', 'learning', 'memory'},
    'llm': {'llm', 'domain'},
    'domain': {'domain'},
    'tools': {'tools', 'domain', 'storage', 'api', 'runtime', 'subagents', 'attachments', 'observability'},
    'app': {'app', 'runtime', 'storage', 'llm', 'tools', 'domain', 'prompts', 'skills', 'extensions', 'capabilities', 'mcp', 'web_tools', 'config', 'learning', 'memory', 'subagents', 'browser', 'attachments', 'observability'},
    'api': {'api', 'runtime', 'storage', 'domain'},
    'config': {'config', 'storage', 'session'},
    'evaluation': {'evaluation', 'api', 'domain', 'llm', 'memory', 'runtime'},
    'learning': {'learning', 'domain', 'memory', 'runtime', 'storage'},
    'memory': {'memory', 'domain', 'runtime', 'storage', 'tools'},
    'prompts': {'prompts'},
    'skills': {'skills'},
    'capabilities': {'capabilities', 'skills', 'tools', 'domain'},
    'mcp': {'mcp'},
    'extensions': {'extensions', 'domain', 'runtime'},
    'subagents': {'subagents', 'domain', 'runtime', 'storage', 'tools'},
    'web_tools': {'web_tools', 'domain', 'runtime', 'storage', 'tools'},
    'browser': {'browser', 'storage', 'tools', 'web_tools'},
    'tui': {'tui', 'app', 'domain', 'runtime'},
    'web': {'web', 'api', 'app', 'cli', 'domain', 'runtime', 'server', 'storage'},
}
REMOVED_TOP_LEVEL_PACKAGES = {'agent_cli', 'agent_core', 'storage', 'tools'}


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


def test_removed_top_level_compat_packages_do_not_exist() -> None:
    for name in REMOVED_TOP_LEVEL_PACKAGES:
        assert not (ROOT / 'src' / name).exists(), name
