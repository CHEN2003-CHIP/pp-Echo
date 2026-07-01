from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / 'src' / 'pp_agent'
ALLOWED = {
    'cli': {'cli', 'runtime', 'domain', 'storage', 'app', 'api', 'config', 'evaluation', 'learning', 'memory', 'skills', 'tools', 'tui', 'web', 'web_tools', 'onboarding', 'sandbox', 'coding', 'observability'},
    'runtime': {'runtime', 'domain', 'llm', 'tools', 'storage', 'config', 'memory', 'subagents', 'observability'},
    'storage': {'storage', 'domain', 'llm', 'learning', 'memory', 'sandbox'},
    'llm': {'llm', 'domain'},
    'domain': {'domain'},
    'tools': {'tools', 'domain', 'storage', 'api', 'runtime', 'subagents', 'attachments', 'observability', 'sandbox'},
    'app': {'app', 'runtime', 'storage', 'llm', 'tools', 'domain', 'prompts', 'skills', 'extensions', 'capabilities', 'mcp', 'web_tools', 'config', 'learning', 'memory', 'subagents', 'browser', 'attachments', 'observability', 'sandbox'},
    'api': {'api', 'runtime', 'storage', 'domain'},
    'config': {'config', 'storage', 'session', 'sandbox', 'llm'},
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
    'coding': {'coding', 'context', 'observability', 'runtime'},
    'tui': {'tui', 'app', 'domain', 'runtime'},
    'web': {'web', 'api', 'app', 'cli', 'config', 'domain', 'runtime', 'sandbox', 'server', 'storage', 'coding', 'observability'},
    'sandbox': {'sandbox'},
}
SANDBOX_CONTRACT_MODULES = {
    'pp_agent.sandbox',
    'pp_agent.sandbox.base',
    'pp_agent.sandbox.changes',
    'pp_agent.sandbox.config',
    'pp_agent.sandbox.network',
    'pp_agent.sandbox.preflight',
}
SANDBOX_RESOLVER_ALLOWED_LAYERS = {'app', 'sandbox'}
REMOVED_TOP_LEVEL_PACKAGES = {'agent_cli', 'agent_core', 'storage', 'tools'}


def _layer_for(path: Path) -> str | None:
    rel = path.relative_to(PACKAGE_ROOT)
    if len(rel.parts) < 2:
        return None
    layer = rel.parts[0]
    if layer == 'compat':
        return None
    return layer


def _allowed_import(layer: str, module_name: str) -> bool:
    target = module_name.split('.')[1]
    if target != 'sandbox':
        return target in ALLOWED[layer]
    if module_name == 'pp_agent.sandbox.resolver':
        return layer in SANDBOX_RESOLVER_ALLOWED_LAYERS
    if module_name.startswith(('pp_agent.sandbox.docker', 'pp_agent.sandbox.local')):
        return layer == 'sandbox'
    # sandbox.base/changes/config/network are shared contract modules: they
    # contain dataclasses, protocols, config parsing, and pure helpers rather
    # than backend execution implementations.
    return module_name in SANDBOX_CONTRACT_MODULES and target in ALLOWED[layer]


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
                        if not _allowed_import(layer, name):
                            violations.append(f'{path.relative_to(ROOT)} imports {name}')
                continue
            if not module_name or not module_name.startswith('pp_agent.'):
                continue
            if not _allowed_import(layer, module_name):
                violations.append(f'{path.relative_to(ROOT)} imports {module_name}')
    assert not violations, '\n'.join(sorted(violations))


def test_removed_top_level_compat_packages_do_not_exist() -> None:
    for name in REMOVED_TOP_LEVEL_PACKAGES:
        assert not (ROOT / 'src' / name).exists(), name
