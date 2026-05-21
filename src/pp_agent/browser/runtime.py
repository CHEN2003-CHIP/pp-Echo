from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from pp_agent.browser.controller import BrowserController, LocalCDPBrowserController
from pp_agent.browser.models import BrowserActRequest, BrowserNode, BrowserSnapshot, BrowserToolArgs
from pp_agent.browser.policy import BrowserPolicy
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
        controller_status = self._browser_controller.status() if self._browser_controller is not None else {}
        return {
            "enabled": bool(self.settings.capabilities.browser.enable),
            "tools": list(self._registered_tool_names),
            "controller_ready": self._browser_controller is not None,
            **controller_status,
        }

    def close(self) -> None:
        if self._browser_controller is not None:
            self._browser_controller.close()
        self._browser_controller = None

    def _register_tools(self) -> None:
        self.tool_registry.register_function_tool(
            name="browser",
            description=(
                "Unified local browser automation tool. Use action=status/profiles/tabs.open/tabs.list/"
                "tabs.focus/tabs.close/snapshot/screenshot/navigate/act. Prefer web.search/web.fetch for static "
                "web pages; use browser for JS-heavy, logged-in, or interactive workflows. Always snapshot before act."
            ),
            parameters=self._browser_parameters(),
            executor=self._execute_browser,
            category="browser",
            requires_confirmation=False,
            permission_domain=PermissionDomain.EDIT,
            sensitive=False,
            model_callable=True,
            tool_family="browser",
            exact_effect_mode="none",
            non_side_effectful=False,
            known_safe_inspect=False,
            requests_network_hint=False,
            touches_external_hint=False,
            replace=True,
        )
        self._registered_tool_names = ["browser"]

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

    def _execute_browser(self, workspace: Path, arguments: dict[str, Any]) -> ToolExecutionResult:
        try:
            args = BrowserToolArgs.model_validate(arguments)
            self._validate_target_and_profile(args)
            result = self._dispatch(args)
            return self._tool_result(result["content"], result["details"], is_error=bool(result.get("is_error", False)))
        except ValidationError as exc:
            return self._tool_result("browser error: invalid arguments", {"error": str(exc)}, is_error=True)
        except Exception as exc:
            return self._tool_result(f"browser error: {exc}", {"error": str(exc)}, is_error=True)

    def _dispatch(self, args: BrowserToolArgs) -> dict[str, Any]:
        controller = self._controller()
        action = args.action
        if action == "doctor":
            return self._plain("browser doctor", {"doctor": controller.doctor(), "untrusted_web_content": False})
        if action == "status":
            return self._plain("browser status", {"status": controller.status(), "untrusted_web_content": False})
        if action == "start":
            return self._plain("browser start", {"status": controller.start(), "untrusted_web_content": False})
        if action == "stop":
            return self._plain("browser stop", {"status": controller.stop(), "untrusted_web_content": False})
        if action == "profiles":
            return self._plain("browser profiles", {"profiles": [item.model_dump(mode="python") for item in controller.profiles()], "untrusted_web_content": False})
        if action == "tabs.list":
            return self._plain("browser tabs", {"tabs": [item.model_dump(mode="python") for item in controller.list_tabs()], "untrusted_web_content": False})
        if action == "tabs.open":
            self._require_url(args.url)
            decision = BrowserPolicy(self.settings.capabilities.browser).check_url(args.url or "")
            if not decision.allowed:
                return self._blocked(decision.reason)
            tab = controller.open_tab(args.url or "about:blank", label=args.label or "")
            return self._plain(f"browser tabs.open: {tab.target_id}", {"tab": tab.model_dump(mode="python"), "untrusted_web_content": False})
        if action == "tabs.focus":
            tab = controller.focus_tab(self._require_target_id(args.target_id))
            return self._plain(f"browser tabs.focus: {tab.target_id}", {"tab": tab.model_dump(mode="python"), "untrusted_web_content": False})
        if action == "tabs.close":
            result = controller.close_tab(self._require_target_id(args.target_id))
            return self._plain(f"browser tabs.close: {result.get('target_id')}", {"result": result, "untrusted_web_content": False})
        if action == "navigate":
            self._require_url(args.url)
            decision = BrowserPolicy(self.settings.capabilities.browser).check_url(args.url or "")
            if not decision.allowed:
                return self._blocked(decision.reason)
            snapshot = controller.navigate(args.url or "about:blank", target_id=args.target_id, wait_ms=int(args.wait_ms or 5000))
            return self._snapshot_payload("browser navigate", snapshot)
        if action == "snapshot":
            if args.snapshot_options.selector or args.snapshot_options.frame:
                return self._blocked("browser.snapshot selector/frame are reserved and not available in this controller.")
            snapshot = controller.snapshot(target_id=args.target_id, options=args.snapshot_options)
            return self._snapshot_payload("browser snapshot", snapshot)
        if action == "screenshot":
            result = controller.screenshot(
                target_id=args.target_id,
                filename=args.screenshot_options.filename,
                full_page=args.screenshot_options.full_page,
            )
            return self._plain(f"browser screenshot: {result['path']}", {"screenshot": result, "untrusted_web_content": False})
        if action == "act":
            if args.request is None:
                raise ValueError("browser action 'act' requires request.")
            node = self._node_for_policy(controller, args.target_id, args.request)
            decision = BrowserPolicy(self.settings.capabilities.browser).check_act(args.request, node)
            if not decision.allowed:
                return self._blocked(decision.reason, {"high_risk": decision.high_risk, "sensitive": decision.sensitive})
            result = controller.act(args.request, target_id=args.target_id)
            return self._snapshot_payload(
                f"browser act {args.request.kind}",
                result.snapshot,
                extra={
                    "requires_resnapshot": result.requires_resnapshot,
                    "stale_ref": result.stale_ref,
                    "act_details": result.details,
                },
            )
        raise ValueError(f"Unsupported browser action: {action}")

    def _validate_target_and_profile(self, args: BrowserToolArgs) -> None:
        if args.target != "host":
            raise ValueError(f"browser target '{args.target}' is reserved; only target='host' is implemented.")
        decision = BrowserPolicy(self.settings.capabilities.browser).check_profile(args.profile)
        if not decision.allowed:
            raise PermissionError(decision.reason)

    def _node_for_policy(self, controller: BrowserController, target_id: str | None, request: BrowserActRequest) -> BrowserNode | None:
        if not request.ref:
            return None
        maps = getattr(controller, "ref_maps", None) or getattr(controller, "_ref_maps", None) or {}
        candidate_maps: list[dict[str, BrowserNode]] = []
        if target_id and target_id in maps:
            candidate_maps.append(maps[target_id])
        candidate_maps.extend(item for item in maps.values() if isinstance(item, dict))
        for ref_map in candidate_maps:
            node = ref_map.get(request.ref)
            if node is not None:
                return node
        return None

    def _snapshot_payload(self, prefix: str, snapshot: BrowserSnapshot, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        summary = snapshot.compact_text()
        content = f"{prefix}: untrusted_web_content url={snapshot.url}, title={snapshot.title}, ready_state={snapshot.ready_state}"
        if summary:
            content += f", text={summary}"
        if snapshot.nodes:
            node_lines = [
                f"{node.ref} role={node.role} name={node.name or node.label or node.text[:40]} text={node.text[:80]}"
                for node in snapshot.nodes[:20]
            ]
            content += "\n" + "\n".join(node_lines)
        details = {
            "snapshot": snapshot.model_dump(exclude={"nodes": {"__all__": {"selector"}}}, mode="python"),
            "untrusted_web_content": True,
        }
        if extra:
            details.update(extra)
        return {"content": content, "details": details}

    def _plain(self, content: str, details: dict[str, Any]) -> dict[str, Any]:
        return {"content": content, "details": details}

    def _blocked(self, reason: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        details = {"blocked": True, "reason": reason, "untrusted_web_content": False}
        if extra:
            details.update(extra)
        return {"content": f"browser blocked: {reason}", "details": details, "is_error": True}

    def _tool_result(self, content: str, details: dict[str, Any], *, is_error: bool = False) -> ToolExecutionResult:
        return ToolExecutionResult(tool_call_id="", tool_name="", content=content, details=details, is_error=is_error)

    @staticmethod
    def _require_url(url: str | None) -> None:
        if not url:
            raise ValueError("browser action requires url.")

    @staticmethod
    def _require_target_id(target_id: str | None) -> str:
        if not target_id:
            raise ValueError("browser action requires target_id.")
        return target_id

    @staticmethod
    def _browser_parameters() -> dict[str, Any]:
        actions = [
            "doctor",
            "status",
            "start",
            "stop",
            "profiles",
            "tabs.open",
            "tabs.list",
            "tabs.focus",
            "tabs.close",
            "snapshot",
            "screenshot",
            "navigate",
            "act",
        ]
        act_kinds = ["click", "type", "press", "hover", "drag", "select", "fill", "wait", "evaluate", "resize", "close"]
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": actions},
                "target": {"type": "string", "enum": ["host", "sandbox", "node"], "default": "host"},
                "profile": {"type": "string", "enum": ["default", "isolated", "user", "remote"], "default": "default"},
                "target_id": {"type": "string"},
                "url": {"type": "string"},
                "label": {"type": "string"},
                "wait_ms": {"type": "integer"},
                "request": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": act_kinds},
                        "ref": {"type": "string"},
                        "text": {"type": "string"},
                        "key": {"type": "string"},
                        "values": {"type": "array", "items": {"type": "string"}},
                        "fields": {"type": "object", "additionalProperties": {"type": "string"}},
                        "timeout_ms": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                        "selector": {"type": "string"},
                        "expression": {"type": "string"},
                    },
                    "required": ["kind"],
                },
                "snapshot_options": {
                    "type": "object",
                    "properties": {
                        "refs": {"type": "boolean"},
                        "interactive": {"type": "boolean"},
                        "compact": {"type": "boolean"},
                        "max_chars": {"type": "integer"},
                        "selector": {"type": "string"},
                        "frame": {"type": "string"},
                    },
                },
                "screenshot_options": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "full_page": {"type": "boolean"},
                    },
                },
            },
            "required": ["action"],
        }
