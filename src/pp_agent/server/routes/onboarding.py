from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pp_agent.onboarding.service import OnboardingService


def mount_onboarding_routes(app, active_workspace: Callable[[], Path]) -> None:
    """
    挂载 Web Startup Guide 使用的 onboarding API。

    路由只读取当前 active workspace，并复用 OnboardingService 的安全检查逻辑。status 接口不会发起真实
    模型请求，也不会泄露 API key；check-model 接口当前只检查模型连接前置条件，失败时以结构化 check
    返回 warning/error，而不是让整个请求崩溃。
    """

    service = OnboardingService()

    @app.get("/api/onboarding/status")
    def onboarding_status() -> dict:
        return service.build_status(active_workspace()).model_dump(mode="json")

    @app.post("/api/onboarding/check-model")
    def onboarding_check_model() -> dict:
        return service.check_model_connectivity(active_workspace()).model_dump(mode="json")
