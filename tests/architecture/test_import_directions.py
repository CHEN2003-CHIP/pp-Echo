from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "src" / "pp_agent"
CHECKED_LAYERS = {"cli", "app", "runtime", "llm", "storage", "domain", "extensions", "api", "tools", "capabilities", "mcp", "web_tools"}
ALLOWED = {
    "cli": {"cli", "app", "runtime", "storage", "domain", "api"},
    "app": {"app", "runtime", "storage", "llm", "tools", "domain", "extensions", "capabilities", "mcp", "web_tools"},
    "runtime": {"runtime", "storage", "llm", "tools", "domain"},
    "llm": {"llm", "domain"},
    "storage": {"storage", "domain"},
    "domain": {"domain"},
    "extensions": {"extensions", "runtime", "domain"},
    "tools": {"tools", "storage", "domain"},
    "capabilities": {"capabilities", "skills", "tools", "domain"},
    "mcp": {"mcp"},
    "web_tools": {"web_tools", "tools"},
    "api": {"api", "runtime", "storage", "domain"},
}
EXCLUDED = {
    PACKAGE_ROOT / "cli" / "_legacy_main_impl.py",
    PACKAGE_ROOT / "domain" / "_legacy_types_impl.py",
}


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
        if path in EXCLUDED:
            continue
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
