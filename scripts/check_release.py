"""Release 前只读检查脚本。

该脚本用于准备 pp-Echo 预览版发布前的本地检查。它不会联网、
不会创建 Git tag，也不会 push 或修改任何仓库文件。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for import_path in (ROOT, ROOT / "src"):
    value = str(import_path)
    if value not in sys.path:
        sys.path.insert(0, value)


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    """运行只读 Git 命令并返回结果。"""
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def is_tracked(path: str) -> bool:
    """判断给定路径是否仍被 Git 跟踪。"""
    result = run_git(["ls-files", "--", path])
    return path in result.stdout.splitlines()


def require_file(path: str) -> tuple[bool, str]:
    """检查仓库内文件是否存在。"""
    target = ROOT / path
    if target.exists():
        return True, f"OK: {path} exists"
    return False, f"FAIL: {path} is missing"


def gitignore_mentions_env() -> bool:
    """检查 .gitignore 是否包含本地 .env 忽略规则。"""
    gitignore = ROOT / ".gitignore"
    if not gitignore.exists():
        return False
    lines = {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()}
    return ".env" in lines and ".env.*" in lines and "!.env.example" in lines


def check_metadata_readable() -> tuple[bool, str]:
    """检查 Python 包元数据文件是否可读取。"""
    candidates = ["pyproject.toml", "setup.py"]
    missing = [path for path in candidates if not (ROOT / path).exists()]
    if missing:
        return False, f"FAIL: missing package metadata: {', '.join(missing)}"
    for path in candidates:
        try:
            (ROOT / path).read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            return False, f"FAIL: {path} is not UTF-8 readable: {exc}"
    return True, "OK: pyproject.toml and setup.py are readable"


def check_tool_policy_names() -> tuple[bool, str]:
    try:
        from pp_agent.app.bootstrap import create_tool_registry, load_settings
    except Exception as exc:  # noqa: BLE001
        return False, f"FAIL: cannot import ToolRegistry bootstrap: {exc}"
    try:
        settings = load_settings(ROOT)
        registry = create_tool_registry(ROOT)
    except Exception as exc:  # noqa: BLE001
        return False, f"FAIL: cannot build ToolRegistry inventory: {exc}"
    registered = set(registry.metadata())
    missing: list[str] = []
    for field in ("allowed_tools", "denied_tools", "ask_tools"):
        for name in getattr(settings.tool_policy, field):
            if any(char in name for char in "*?[]"):
                continue
            if name not in registered:
                missing.append(f"{field}:{name}")
    if missing:
        return False, f"FAIL: tool policy references unknown registered tools: {', '.join(sorted(missing))}"
    return True, f"OK: tool policy names match registered ToolRegistry inventory ({len(registered)} tools)"


def run_command(label: str, command: list[str], *, cwd: Path = ROOT) -> tuple[bool, str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode == 0:
        return True, f"OK: {label}"
    tail = "\n".join((result.stdout + "\n" + result.stderr).splitlines()[-12:])
    return False, f"FAIL: {label}\n{tail}"


def stable_gate_commands(*, skip_web: bool = False, full: bool = False) -> list[tuple[str, list[str], Path]]:
    commands: list[tuple[str, list[str], Path]] = [
        (
            "focused runtime/tools/subagents/observability tests",
            [sys.executable, "-m", "pytest", "tests/runtime", "tests/tools", "tests/subagents", "tests/observability", "-q"],
            ROOT,
        ),
        (
            "focused onboarding/storage/config/mcp/attachments tests",
            [sys.executable, "-m", "pytest", "tests/onboarding", "tests/storage", "tests/config", "tests/mcp", "tests/attachments", "-q"],
            ROOT,
        ),
        (
            "known Web memory regression",
            [sys.executable, "-m", "pytest", "tests/web/test_server.py::test_web_api_memory_status_search_and_read", "-q"],
            ROOT,
        ),
        ("onboard JSON", [sys.executable, "-m", "pp_agent.cli.main", "onboard", "--json"], ROOT),
        ("workflow doctor JSON", [sys.executable, "-m", "pp_agent.cli.main", "workflow", "doctor", "--json"], ROOT),
        ("eval report JSON", [sys.executable, "-m", "pp_agent.cli.main", "eval", "report", "--json"], ROOT),
    ]
    if full:
        commands.append(("full Python tests", [sys.executable, "-m", "pytest", "tests", "-q"], ROOT))
        commands.append(
            (
                "deterministic eval 100 cases",
                [sys.executable, "-m", "pp_agent.cli.main", "eval", "run", "--suite", "pp_echo_core", "--mode", "deterministic", "--cases", "100"],
                ROOT,
            )
        )
    if not skip_web:
        npm = shutil.which("npm") or "npm"
        commands.extend(
            [
                ("Web JS tests", [npm, "test"], ROOT / "web"),
                ("Web build", [npm, "run", "build"], ROOT / "web"),
            ]
        )
    return commands


def main() -> int:
    """执行 release 准备检查并输出下一步建议。"""
    parser = argparse.ArgumentParser(description="Check pp-Echo release preparation without publishing.")
    parser.add_argument("--version", default="v0.1.0-alpha.1", help="Expected release tag.")
    parser.add_argument("--stable-gate", action="store_true", help="Run the stable release gate commands.")
    parser.add_argument("--full", action="store_true", help="With --stable-gate, also run full tests and deterministic eval.")
    parser.add_argument("--skip-web", action="store_true", help="With --stable-gate, skip npm tests and build.")
    args = parser.parse_args()

    checks: list[tuple[bool, str]] = [
        (not is_tracked(".env"), "OK: .env is not tracked" if not is_tracked(".env") else "FAIL: .env is tracked"),
        require_file(".env.example"),
        require_file("docs/next-stable-release-plan.md"),
        require_file("docs/release-checklist.md"),
        require_file(f"releases/{args.version}.md"),
        (gitignore_mentions_env(), "OK: .gitignore ignores local .env files" if gitignore_mentions_env() else "FAIL: .gitignore is missing .env rules"),
        check_metadata_readable(),
        check_tool_policy_names(),
    ]

    failed = False
    for ok, message in checks:
        print(message)
        failed = failed or not ok

    if args.stable_gate:
        print()
        print("Stable gate:")
        for label, command, cwd in stable_gate_commands(skip_web=args.skip_web, full=args.full):
            ok, message = run_command(label, command, cwd=cwd)
            print(message)
            failed = failed or not ok

    print()
    print("Next manual steps, if all checks pass:")
    print(f"  git tag -a {args.version} -m \"pp-Echo {args.version}\"")
    print("  git push origin master")
    print(f"  git push origin {args.version}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
