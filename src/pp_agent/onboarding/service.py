from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pp_agent.onboarding import checks
from pp_agent.onboarding.schema import OnboardingCheck, OnboardingCommandHint, OnboardingNextStep, OnboardingStatus


class OnboardingService:
    """
    聚合 pp-Echo 首次启动所需的环境检查。

    OnboardingService 同时服务 Web Startup Guide 和 CLI onboard，避免两端各自实现一套检查逻辑。
    它只做只读检查或安全的临时写入测试，不保存用户密钥，不修改项目配置，不执行高风险命令，也不会在
    默认状态下发起真实模型请求。单个检查失败会被转换为 error/warning check，避免整个引导接口 500。
    """

    def build_status(self, workspace: Path, *, include_model_check: bool = False) -> OnboardingStatus:
        """
        构建当前 workspace 的 onboarding 状态快照。

        include_model_check 为 True 时追加模型连接检查；当前实现仍保持保守，只检查凭据和配置边界，不实际
        请求模型。overall_status 根据关键 error 和 warning 聚合，供 Web 顶部状态和 CLI 退出前摘要使用。
        """

        root = workspace.resolve()
        check_fns: list[tuple[str, Callable[[], OnboardingCheck]]] = [
            ("python", checks.check_python_version),
            ("node", checks.check_node_version),
            ("npm", checks.check_npm_available),
            ("api_key", checks.check_api_key),
            ("project_import", checks.check_project_import),
            ("workspace", lambda: checks.check_workspace(root)),
            ("git_available", checks.check_git_available),
            ("git_repo", lambda: checks.check_git_repo(root)),
            ("trace_store", lambda: checks.check_trace_store(root)),
            ("memory", lambda: checks.check_memory_status(root)),
            ("eval", lambda: checks.check_eval_assets(root)),
            ("web_build", lambda: checks.check_web_build_hint(root)),
        ]
        items = [self._safe_check(check_id, fn) for check_id, fn in check_fns]
        if include_model_check:
            items.append(self.check_model_connectivity(root))
        return OnboardingStatus(
            workspace=str(root),
            overall_status=self._overall_status(items),
            checks=items,
            command_hints=self._command_hints(),
            next_steps=self._next_steps(),
        )

    def check_model_connectivity(self, workspace: Path) -> OnboardingCheck:
        """
        检查模型连接前置条件。

        该方法是 Web “测试模型连接”和 CLI --check-model 的共享入口。为了避免首次引导产生费用或网络副作用，
        当前版本不会真正发送 prompt；当 API key 缺失时返回 warning，存在 key 时返回 skipped 并说明后续可
        接入轻量 ping。返回内容仍不会泄露 key 的任何片段。
        """

        _ = workspace
        api_key = checks.check_api_key()
        if api_key.status != "ok":
            return OnboardingCheck(
                id="model_connectivity",
                title="模型连接",
                status="warning",
                summary="未测试模型连接：缺少 API key",
                detail="设置 PP_AGENT_API_KEY 或 OPENAI_API_KEY 后再测试。该检查未发起真实模型请求。",
                action_label=api_key.action_label,
                action_command=api_key.action_command,
            )
        return OnboardingCheck(
            id="model_connectivity",
            title="模型连接",
            status="skipped",
            summary="已具备 API key，当前版本未发起真实模型请求",
            detail="为避免首次引导产生费用，onboard 目前只检查凭据存在性；后续可接入显式轻量 ping。",
        )

    def _safe_check(self, check_id: str, fn: Callable[[], OnboardingCheck]) -> OnboardingCheck:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            return OnboardingCheck(id=check_id, title=check_id.replace("_", " ").title(), status="warning", summary="检查失败", detail=str(exc))

    @staticmethod
    def _overall_status(items: list[OnboardingCheck]) -> str:
        critical_errors = {"python", "project_import", "workspace"}
        if any(item.status == "error" and item.id in critical_errors for item in items):
            return "blocked"
        if any(item.status in {"warning", "error"} for item in items):
            return "partial"
        return "ready"

    @staticmethod
    def _command_hints() -> list[OnboardingCommandHint]:
        return [
            OnboardingCommandHint(title="设置 API key", command='setx PP_AGENT_API_KEY "your_api_key"', description="Windows 用户可用 setx 持久设置。"),
            OnboardingCommandHint(title="启动 CLI", command="python -m pp_agent.cli.main chat", description="进入交互式命令行会话。"),
            OnboardingCommandHint(title="启动 Web", command=".\\start-web.bat", description="启动后点击左上角 pp-Echo 查看 Startup Guide。"),
            OnboardingCommandHint(title="运行 doctor", command="python -m pp_agent.cli.main workflow doctor --json", description="查看更深入的运行时诊断。"),
        ]

    @staticmethod
    def _next_steps() -> list[OnboardingNextStep]:
        return [
            OnboardingNextStep(title="运行第一个安全任务", description="让 Agent 只阅读 README 并总结模块，不修改文件、不执行 shell。", action_label="返回会话", target_view="chat"),
            OnboardingNextStep(title="查看 Agent Trace 审计", description="任务运行后打开 TraceInspect 查看 token、工具调用、审批、Memory、Checkpoint 和错误诊断。", action_label="打开 TraceInspect", target_view="traceInspect"),
            OnboardingNextStep(title="运行 deterministic eval", description="用默认 eval 套件验证关键能力，不依赖真实 LLM。", action_label="查看命令"),
            OnboardingNextStep(title="阅读源码路线图", description="从 docs/source-reading-roadmap.md 开始理解 runtime、tools、memory 和 observability。", action_label="查看文档"),
        ]
