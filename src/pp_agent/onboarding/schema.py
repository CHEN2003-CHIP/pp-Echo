from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

OnboardingCheckStatus = Literal["ok", "warning", "error", "skipped"]


class OnboardingCheck(BaseModel):
    """
    表示启动指引中的单个检查项。

    一个检查项对应 Web Startup Guide 页面上的一行 checklist，也对应 CLI onboard 命令中的一条输出。
    它只描述当前环境是否满足 pp-Echo 的启动条件，以及用户下一步应该如何处理；检查函数不得自动写入
    API key、修改项目配置或执行高风险命令。status 字段用于前端和 CLI 展示：ok 表示通过，warning
    表示可继续但需注意，error 表示关键条件缺失，skipped 表示因安全或依赖边界暂不检查。
    """

    id: str
    title: str
    status: OnboardingCheckStatus
    summary: str
    detail: str = ""
    action_label: Optional[str] = None
    action_command: Optional[str] = None
    docs_hint: Optional[str] = None


class OnboardingCommandHint(BaseModel):
    """
    表示启动指引推荐给用户复制执行的一条命令。

    该结构只承载显示文本，不会由后端或前端自动执行。Web Startup Guide 和 CLI onboard 都可以复用它
    展示设置 API key、启动 Web、运行 workflow doctor 等下一步命令，确保新手引导和真实执行保持分离。
    """

    title: str
    command: str
    description: str = ""


class OnboardingNextStep(BaseModel):
    """
    表示启动检查完成后的建议下一步。

    next step 用于把检查结果转成安全、低风险的学习路径，例如返回会话、打开 TraceInspect、阅读文档或
    运行 deterministic eval。target_view 仅供 Web UI 切换已有视图使用，不代表后端会执行任何命令。
    """

    title: str
    description: str
    action_label: Optional[str] = None
    target_view: Optional[str] = None


class OnboardingStatus(BaseModel):
    """
    Web Startup Guide 和 CLI onboard 共用的启动状态快照。

    该结构聚合 Python、Node、npm、API Key、项目 import、workspace、Git、Trace Store、Memory、Eval
    等检查结果。它只服务首次启动引导，不承担真实 Runtime 执行逻辑，也不会保存敏感信息。overall_status
    的含义为：ready 表示核心项可用，partial 表示存在 warning 但未阻塞，blocked 表示存在关键 error。
    """

    workspace: str
    overall_status: Literal["ready", "partial", "blocked"]
    checks: List[OnboardingCheck]
    command_hints: List[OnboardingCommandHint] = Field(default_factory=list)
    next_steps: List[OnboardingNextStep] = Field(default_factory=list)
