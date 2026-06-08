"""Release 前只读检查脚本。

该脚本用于准备 pp-Echo 预览版发布前的本地检查。它不会联网、
不会创建 Git tag，也不会 push 或修改任何仓库文件。
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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


def main() -> int:
    """执行 release 准备检查并输出下一步建议。"""
    parser = argparse.ArgumentParser(description="Check pp-Echo release preparation without publishing.")
    parser.add_argument("--version", default="v0.1.0-alpha.1", help="Expected release tag.")
    args = parser.parse_args()

    checks: list[tuple[bool, str]] = [
        (not is_tracked(".env"), "OK: .env is not tracked" if not is_tracked(".env") else "FAIL: .env is tracked"),
        require_file(".env.example"),
        require_file(f"releases/{args.version}.md"),
        (gitignore_mentions_env(), "OK: .gitignore ignores local .env files" if gitignore_mentions_env() else "FAIL: .gitignore is missing .env rules"),
        check_metadata_readable(),
    ]

    failed = False
    for ok, message in checks:
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
