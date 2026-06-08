from __future__ import annotations

import json
from pathlib import Path

from pp_agent.onboarding.schema import OnboardingCheck, OnboardingStatus
from pp_agent.onboarding.service import OnboardingService

STATUS_LABELS = {"ok": "OK", "warning": "WARN", "error": "ERROR", "skipped": "SKIP"}


def onboarding_main(workspace: Path, *, json_mode: bool = False, check_model: bool = False, no_color: bool = False) -> None:
    """
    执行 CLI onboard 新手引导。

    该命令复用 OnboardingService，与 Web Startup Guide 保持同一套检查逻辑。默认只输出人类友好的 checklist，
    不写配置、不保存 API key、不执行危险命令，也不发起真实模型请求。--json 输出合法 JSON；--check-model
    仅追加模型连接前置条件检查，当前实现仍保持费用安全边界。
    """

    _ = no_color
    status = OnboardingService().build_status(workspace, include_model_check=check_model)
    if json_mode:
        print(json.dumps(status.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return
    print(_render_status(status))


def _render_status(status: OnboardingStatus) -> str:
    lines = ["pp-Echo Onboard", "", f"Workspace: {status.workspace}", f"Overall: {status.overall_status}", ""]
    for item in status.checks:
        lines.append(_render_check(item))
    lines.extend(["", "下一步："])
    for index, hint in enumerate(status.command_hints, start=1):
        lines.append(f"{index}. {hint.title}")
        if hint.description:
            lines.append(f"   {hint.description}")
        lines.append(f"   {hint.command}")
        lines.append("")
    lines.append("安全首个任务：")
    lines.append("   请阅读 README，总结 pp-Echo 的核心模块，不要修改文件，不要执行 shell。")
    return "\n".join(lines).rstrip()


def _render_check(item: OnboardingCheck) -> str:
    label = STATUS_LABELS.get(item.status, item.status.upper())
    line = f"[{label}] {item.title}: {item.summary}"
    if item.detail:
        line += f" - {item.detail}"
    return line


__all__ = ["onboarding_main"]
