from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pp_agent.browser.controller import BrowserController, BrowserSnapshot, LocalCDPBrowserController
from pp_agent.storage.settings import BrowserCapabilityConfig, Settings
from pp_agent.tools.base import ToolExecutionResult
from pp_agent.tools.policy import PermissionDomain
from pp_agent.tools.registry import ToolRegistry


BrowserControllerFactory = Callable[[Path, BrowserCapabilityConfig], BrowserController]


@dataclass
class BrowserRuntime:
    workspace: Path
    settings: Settings
    tool_registry: ToolRegistry
    controller_factory: BrowserControllerFactory | None = None
    _browser_controller: BrowserController | None = field(default=None, init=False, repr=False)
    _registered_tool_names: list[str] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.settings.capabilities.browser.enable:
            return
        self._register_tools()

    def status(self) -> dict[str, object]:
        return {
            "enabled": bool(self.settings.capabilities.browser.enable),
            "tools": list(self._registered_tool_names),
            "controller_ready": self._browser_controller is not None,
        }

    def close(self) -> None:
        if self._browser_controller is not None:
            self._browser_controller.close()
        self._browser_controller = None

    def _register_tools(self) -> None:
        tool_defs = [
            (
                "browser.navigate",
                "Navigate the local browser to a URL and wait for the page to settle.",
                PermissionDomain.EDIT,
                self._execute_navigate,
            ),
            (
                "browser.click",
                "Click a CSS selector in the local browser and return the updated page state.",
                PermissionDomain.EDIT,
                self._execute_click,
            ),
            (
                "browser.type",
                "Type text into a CSS selector in the local browser and return the updated page state.",
                PermissionDomain.EDIT,
                self._execute_type,
            ),
            (
                "browser.read_state",
                "Read the active browser page state, including URL, title, and visible text.",
                PermissionDomain.READ,
                self._execute_read_state,
            ),
            (
                "browser.screenshot",
                "Capture a screenshot of the active browser page and store it under .pp-agent/browser.",
                PermissionDomain.READ,
                self._execute_screenshot,
            ),
        ]
        for name, description, permission_domain, executor in tool_defs:
            self.tool_registry.register_function_tool(
                name=name,
                description=description,
                parameters=self._parameters_for(name),
                executor=executor,
                category="browser",
                requires_confirmation=False,
                permission_domain=permission_domain,
                sensitive=False,
                model_callable=True,
                tool_family="browser",
                exact_effect_mode="none",
                non_side_effectful=permission_domain == PermissionDomain.READ,
                known_safe_inspect=permission_domain == PermissionDomain.READ,
                requests_network_hint=False,
                touches_external_hint=False,
                replace=True,
            )
            self._registered_tool_names.append(name)

    def _controller(self) -> BrowserController:
        if self._browser_controller is None:
            factory = self.controller_factory or self._default_controller_factory
            self._browser_controller = factory(self.workspace, self.settings.capabilities.browser)
        return self._browser_controller

    def _default_controller_factory(self, workspace: Path, config: BrowserCapabilityConfig) -> BrowserController:
        return LocalCDPBrowserController(
            workspace=workspace,
            browser_executable=config.browser_executable,
            user_data_dir=config.user_data_dir,
            screenshot_dir=config.screenshot_dir,
            launch_flags=list(config.launch_flags),
        )

    def _snapshot_result(self, action: str, snapshot: BrowserSnapshot, *, extra: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
        body_text = snapshot.body_text.strip().replace("\n", " ")
        summary = body_text[:240]
        if len(body_text) > 240:
            summary += "..."
        content = f"{action}: url={snapshot.url}, title={snapshot.title}, ready_state={snapshot.ready_state}"
        if summary:
            content += f", text={summary}"
        details = {
            "url": snapshot.url,
            "title": snapshot.title,
            "ready_state": snapshot.ready_state,
            "body_text": snapshot.body_text,
            "html": snapshot.html,
        }
        if extra:
            details.update(extra)
        return content, details

    def _execute_navigate(self, workspace: Path, arguments: dict[str, Any]) -> ToolExecutionResult:
        snapshot = self._controller().navigate(str(arguments["url"]), wait_ms=int(arguments.get("wait_ms", 5000)))
        content, details = self._snapshot_result("Navigated", snapshot, extra={"url": str(arguments["url"])})
        return self._tool_result(content, details)

    def _execute_click(self, workspace: Path, arguments: dict[str, Any]) -> ToolExecutionResult:
        selector = str(arguments["selector"])
        snapshot = self._controller().click(selector, wait_ms=int(arguments.get("wait_ms", 1500)))
        content, details = self._snapshot_result("Clicked", snapshot, extra={"selector": selector})
        return self._tool_result(content, details)

    def _execute_type(self, workspace: Path, arguments: dict[str, Any]) -> ToolExecutionResult:
        selector = str(arguments["selector"])
        text = str(arguments["text"])
        snapshot = self._controller().type(
            selector,
            text,
            press_enter=bool(arguments.get("press_enter", False)),
            wait_ms=int(arguments.get("wait_ms", 1500)),
        )
        content, details = self._snapshot_result("Typed", snapshot, extra={"selector": selector, "text_length": len(text)})
        return self._tool_result(content, details)

    def _execute_read_state(self, workspace: Path, arguments: dict[str, Any]) -> ToolExecutionResult:
        snapshot = self._controller().read_state()
        content, details = self._snapshot_result("Browser state", snapshot)
        max_chars = int(arguments.get("max_body_chars", 1200))
        details["body_text"] = snapshot.body_text[:max_chars]
        if snapshot.html is not None and not bool(arguments.get("include_html", False)):
            details["html"] = None
        return self._tool_result(content, details)

    def _execute_screenshot(self, workspace: Path, arguments: dict[str, Any]) -> ToolExecutionResult:
        result = self._controller().screenshot(
            full_page=bool(arguments.get("full_page", True)),
            filename=str(arguments["filename"]) if arguments.get("filename") else None,
        )
        return self._tool_result(
            f"Captured screenshot at {result['path']}",
            {"path": result["path"], "bytes": result["bytes"], "full_page": result["full_page"]},
        )

    def _tool_result(self, content: str, details: dict[str, Any]) -> ToolExecutionResult:
        return ToolExecutionResult(tool_call_id="", tool_name="", content=content, details=details)

    @staticmethod
    def _parameters_for(name: str) -> dict[str, Any]:
        if name == "browser.navigate":
            return {"type": "object", "properties": {"url": {"type": "string"}, "wait_ms": {"type": "integer"}},"required": ["url"]}
        if name == "browser.click":
            return {"type": "object", "properties": {"selector": {"type": "string"}, "wait_ms": {"type": "integer"}}, "required": ["selector"]}
        if name == "browser.type":
            return {
                "type": "object",
                "properties": {
                    "selector": {"type": "string"},
                    "text": {"type": "string"},
                    "press_enter": {"type": "boolean"},
                    "wait_ms": {"type": "integer"},
                },
                "required": ["selector", "text"],
            }
        if name == "browser.screenshot":
            return {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "full_page": {"type": "boolean"},
                },
            }
        return {
            "type": "object",
            "properties": {
                "max_body_chars": {"type": "integer"},
                "include_html": {"type": "boolean"},
            },
        }
