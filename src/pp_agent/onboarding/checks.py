from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from pp_agent.onboarding.schema import OnboardingCheck


def _run_version(command: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    output = (result.stdout or result.stderr or "").strip()
    return result.returncode == 0, output


def check_python_version() -> OnboardingCheck:
    """检查当前 Python 版本是否满足 pp-Echo 的最低运行要求。"""

    version = sys.version_info
    text = f"Python {version.major}.{version.minor}.{version.micro}"
    if version >= (3, 9):
        return OnboardingCheck(id="python", title="Python", status="ok", summary=text, detail="满足 Python 3.9+ 要求。")
    return OnboardingCheck(id="python", title="Python", status="error", summary=text, detail="pp-Echo 需要 Python 3.9 或更高版本。")


def check_node_version() -> OnboardingCheck:
    """检查 Node.js 是否可用；缺失不会阻止 CLI，但会影响 Web 构建。"""

    if shutil.which("node") is None:
        return OnboardingCheck(id="node", title="Node.js", status="warning", summary="未找到 node 命令", detail="CLI 仍可运行，但 Web 构建可能失败。")
    ok, output = _run_version(["node", "--version"])
    if not ok:
        return OnboardingCheck(id="node", title="Node.js", status="warning", summary="node 命令无法读取版本", detail=output)
    version = output.lstrip("v").split(".", 1)[0]
    try:
        major = int(version)
    except ValueError:
        major = 0
    if major >= 20:
        return OnboardingCheck(id="node", title="Node.js", status="ok", summary=output, detail="满足 Web 构建建议版本。")
    return OnboardingCheck(id="node", title="Node.js", status="warning", summary=output, detail="建议使用 Node.js 20+ 构建 Web UI。")


def check_npm_available() -> OnboardingCheck:
    """检查 npm 是否可用；该检查只读版本信息，不安装依赖。"""

    if shutil.which("npm") is None:
        return OnboardingCheck(id="npm", title="npm", status="warning", summary="未找到 npm 命令", detail="Web 构建需要 npm。")
    ok, output = _run_version(["npm", "--version"])
    status = "ok" if ok else "warning"
    return OnboardingCheck(id="npm", title="npm", status=status, summary=output or "npm 可用", detail="仅检查版本，不会安装依赖。")


def check_api_key() -> OnboardingCheck:
    """
    检查 API key 环境变量是否存在且不泄露具体值。

    该函数最多报告变量名和长度，不显示前缀、后缀或完整密钥，避免 Startup Guide、CLI 或日志泄露凭据。
    """

    configured: list[str] = []
    for name in ("PP_AGENT_API_KEY", "OPENAI_API_KEY"):
        value = os.getenv(name)
        if value:
            configured.append(f"{name}: 已设置，长度 {len(value)}")
    if configured:
        return OnboardingCheck(id="api_key", title="API Key", status="ok", summary="已检测到 API key", detail="；".join(configured))
    return OnboardingCheck(
        id="api_key",
        title="API Key",
        status="warning",
        summary="未检测到 PP_AGENT_API_KEY 或 OPENAI_API_KEY",
        detail="真实模型调用前需要设置 API key。不会自动保存或写入密钥。",
        action_label="设置 API key",
        action_command='setx PP_AGENT_API_KEY "your_api_key"',
    )


def check_project_import() -> OnboardingCheck:
    """检查 pp_agent 包是否能被当前 Python 环境 import。"""

    try:
        importlib.import_module("pp_agent")
    except Exception as exc:  # noqa: BLE001
        return OnboardingCheck(id="project_import", title="pp_agent import", status="error", summary="无法 import pp_agent", detail=str(exc))
    return OnboardingCheck(id="project_import", title="pp_agent import", status="ok", summary="pp_agent 可导入", detail="当前 Python 环境可以加载项目源码。")


def check_workspace(workspace: Path) -> OnboardingCheck:
    """检查 workspace 是否存在、可读写，并能安全创建和删除一个临时探针文件。"""

    path = workspace.resolve()
    if not path.exists():
        return OnboardingCheck(id="workspace", title="Workspace", status="error", summary=f"路径不存在：{path}")
    if not path.is_dir():
        return OnboardingCheck(id="workspace", title="Workspace", status="error", summary=f"不是目录：{path}")
    if not os.access(path, os.R_OK):
        return OnboardingCheck(id="workspace", title="Workspace", status="error", summary=f"不可读：{path}")
    agent_dir = path / ".pp-agent"
    probe = agent_dir / "onboarding.tmp"
    try:
        agent_dir.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return OnboardingCheck(id="workspace", title="Workspace", status="error", summary="Workspace 不可写", detail=str(exc))
    return OnboardingCheck(id="workspace", title="Workspace", status="ok", summary=f"可读写：{path}", detail="仅写入并删除 .pp-agent/onboarding.tmp。")


def check_git_available() -> OnboardingCheck:
    """检查 git 命令是否可用；不修改仓库状态。"""

    if shutil.which("git") is None:
        return OnboardingCheck(id="git_available", title="Git 命令", status="warning", summary="未找到 git 命令")
    ok, output = _run_version(["git", "--version"])
    return OnboardingCheck(id="git_available", title="Git 命令", status="ok" if ok else "warning", summary=output or "git 可用")


def check_git_repo(workspace: Path) -> OnboardingCheck:
    """检查当前 workspace 是否是 Git 仓库；失败只提示 checkpoint/rewind 能力受限。"""

    try:
        result = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=workspace, check=False, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError) as exc:
        return OnboardingCheck(id="git_repo", title="Git 仓库", status="warning", summary="无法检查 Git 仓库", detail=str(exc))
    if result.returncode == 0 and result.stdout.strip() == "true":
        return OnboardingCheck(id="git_repo", title="Git 仓库", status="ok", summary="当前 workspace 是 Git 仓库")
    return OnboardingCheck(id="git_repo", title="Git 仓库", status="warning", summary="当前目录不是 Git 仓库", detail="部分 checkpoint/rewind 能力会受影响。")


def check_trace_store(workspace: Path) -> OnboardingCheck:
    """检查 .pp-agent/traces 是否可临时写入，并删除探针文件，不触碰已有 trace。"""

    trace_dir = workspace.resolve() / ".pp-agent" / "traces"
    probe = trace_dir / "onboarding-check.tmp.jsonl"
    try:
        trace_dir.mkdir(parents=True, exist_ok=True)
        probe.write_text('{"ok": true}\n', encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return OnboardingCheck(id="trace_store", title="Trace Store", status="warning", summary="Trace store 不可写", detail=str(exc))
    return OnboardingCheck(id="trace_store", title="Trace Store", status="ok", summary="Trace store 可写", detail="临时 JSONL 已删除。")


def check_memory_status(workspace: Path) -> OnboardingCheck:
    """轻量检查 memory/learning 模块可导入和 memory 目录可访问，不构建索引。"""

    try:
        importlib.import_module("pp_agent.learning")
    except Exception as exc:  # noqa: BLE001
        return OnboardingCheck(id="memory", title="Memory", status="warning", summary="Memory 模块无法导入", detail=str(exc))
    memory_dir = workspace.resolve() / ".pp-agent" / "memory"
    if memory_dir.exists() and not os.access(memory_dir, os.R_OK):
        return OnboardingCheck(id="memory", title="Memory", status="warning", summary="Memory 目录不可读", detail=str(memory_dir))
    return OnboardingCheck(id="memory", title="Memory", status="ok", summary="Memory 模块可用", detail="未自动构建索引或写入记忆。")


def check_eval_assets(workspace: Path) -> OnboardingCheck:
    """检查 evals 目录和默认 deterministic suite 是否存在；缺失不阻塞启动。"""

    root = workspace.resolve()
    evals = root / "evals"
    suite = evals / "suites" / "pp_echo_core.json"
    if evals.exists() and suite.exists():
        return OnboardingCheck(id="eval", title="Eval", status="ok", summary="evals/ 和 pp_echo_core suite 存在")
    return OnboardingCheck(id="eval", title="Eval", status="warning", summary="未找到完整 eval 资产", detail=f"检查路径：{suite}")


def check_web_build_hint(workspace: Path) -> OnboardingCheck:
    """检查 Web 工程关键文件是否存在；不执行 npm install 或 npm build。"""

    package_json = workspace.resolve() / "web" / "package.json"
    if package_json.exists():
        return OnboardingCheck(id="web_build", title="Web 构建", status="ok", summary="web/package.json 存在", detail="可手动运行 cd web && npm run build。")
    return OnboardingCheck(id="web_build", title="Web 构建", status="warning", summary="未找到 web/package.json")
