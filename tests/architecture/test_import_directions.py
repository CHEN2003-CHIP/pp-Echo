from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "src" / "pp_agent"
CHECKED_LAYERS = {
    "api",
    "app",
    "browser",
    "capabilities",
    "cli",
    "config",
    "domain",
    "evaluation",
    "extensions",
    "learning",
    "llm",
    "mcp",
    "memory",
    "prompts",
    "runtime",
    "skills",
    "storage",
    "subagents",
    "tools",
    "tui",
    "web",
    "web_tools",
}
ALLOWED = {
    "cli": {"cli", "app", "runtime", "storage", "domain", "api", "config", "evaluation", "learning", "memory", "skills", "tools", "tui", "web", "web_tools", "onboarding"},
    "app": {"app", "runtime", "storage", "llm", "tools", "domain", "extensions", "capabilities", "mcp", "web_tools", "config", "learning", "memory", "prompts", "skills", "subagents", "browser", "attachments", "observability"},
    "runtime": {"runtime", "storage", "llm", "tools", "domain", "config", "memory", "subagents", "observability"},
    "llm": {"llm", "domain"},
    "storage": {"storage", "domain", "llm", "learning", "memory"},
    "domain": {"domain"},
    "extensions": {"extensions", "runtime", "domain"},
    "tools": {"tools", "storage", "domain", "api", "runtime", "subagents", "attachments", "observability"},
    "capabilities": {"capabilities", "skills", "tools", "domain"},
    "mcp": {"mcp"},
    "web_tools": {"web_tools", "domain", "runtime", "storage", "tools"},
    "api": {"api", "runtime", "storage", "domain"},
    "config": {"config", "storage", "session"},
    "evaluation": {"evaluation", "api", "domain", "llm", "memory", "runtime"},
    "learning": {"learning", "domain", "memory", "runtime", "storage"},
    "memory": {"memory", "domain", "runtime", "storage", "tools"},
    "prompts": {"prompts"},
    "skills": {"skills"},
    "subagents": {"subagents", "domain", "runtime", "storage", "tools"},
    "browser": {"browser", "storage", "tools", "web_tools"},
    "tui": {"tui", "app", "domain", "runtime"},
    "web": {"web", "api", "app", "cli", "domain", "runtime", "server", "storage"},
}
REMOVED_TOP_LEVEL_PACKAGES = {"agent_cli", "agent_core", "storage", "tools"}


def _layer_for(path: Path) -> str | None:
    relative = path.relative_to(PACKAGE_ROOT)
    if len(relative.parts) < 2:
        return None
    layer = relative.parts[0]
    if layer not in CHECKED_LAYERS:
        return None
    return layer


def test_import_directions_for_core_layers() -> None:
    violations: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        layer = _layer_for(path)
        if layer is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("pp_agent."):
                target = node.module.split(".")[1]
                if target not in ALLOWED[layer]:
                    violations.append(f"{path.relative_to(ROOT)} imports {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if not alias.name.startswith("pp_agent."):
                        continue
                    target = alias.name.split(".")[1]
                    if target not in ALLOWED[layer]:
                        violations.append(f"{path.relative_to(ROOT)} imports {alias.name}")
    assert not violations, "\n".join(sorted(violations))


def test_cli_entry_files_do_not_reference_legacy_impl() -> None:
    main_text = (PACKAGE_ROOT / "cli" / "main.py").read_text(encoding="utf-8-sig")
    chat_text = (PACKAGE_ROOT / "cli" / "chat.py").read_text(encoding="utf-8-sig")

    assert "_legacy_main_impl" not in main_text
    assert "_legacy_main_impl" not in chat_text


def test_removed_top_level_compat_packages_do_not_exist() -> None:
    for name in REMOVED_TOP_LEVEL_PACKAGES:
        assert not (ROOT / "src" / name).exists(), name


def test_runtime_and_extensions_do_not_depend_on_cli_rendering() -> None:
    runtime_paths = [
        PACKAGE_ROOT / "runtime" / "lifecycle.py",
        PACKAGE_ROOT / "runtime" / "emitter.py",
    ]
    for path in runtime_paths:
        text = path.read_text(encoding="utf-8-sig")
        assert "pp_agent.cli" not in text

    for path in (PACKAGE_ROOT / "extensions").rglob("*.py"):
        text = path.read_text(encoding="utf-8-sig")
        assert "pp_agent.cli" not in text


def test_api_and_programmatic_modes_do_not_depend_on_cli_rendering() -> None:
    for path in (PACKAGE_ROOT / "api").rglob("*.py"):
        text = path.read_text(encoding="utf-8-sig")
        assert "pp_agent.cli.commands" not in text
        assert "pp_agent.cli.render" not in text

    text = (PACKAGE_ROOT / "runtime" / "session_host.py").read_text(encoding="utf-8-sig")
    assert "pp_agent.cli" not in text


def test_cli_boundary_guards_for_run_and_sessions_commands() -> None:
    run_text = (PACKAGE_ROOT / "cli" / "commands" / "run.py").read_text(encoding="utf-8-sig")
    sessions_text = (PACKAGE_ROOT / "cli" / "commands" / "sessions.py").read_text(encoding="utf-8-sig")

    assert "import build_agent" not in run_text
    assert "from pp_agent.storage.sessions import SessionStore" not in sessions_text
    assert "import SessionStore" not in sessions_text
