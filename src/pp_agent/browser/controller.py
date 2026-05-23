from __future__ import annotations

import base64
import json
import shutil
import subprocess
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Protocol

import httpx

# 导入浏览器相关的数据模型
from pp_agent.browser.models import (
    BrowserActRequest,   # 浏览器操作请求
    BrowserActResult,    # 浏览器操作结果
    BrowserBounds,       # 元素位置大小
    BrowserNode,         # 页面元素节点
    BrowserProfile,      # 浏览器配置文件
    BrowserSnapshot,     # 页面快照
    BrowserSnapshotOptions, # 快照选项
    BrowserTab,          # 标签页
)


class BrowserController(Protocol):
    def doctor(self) -> dict[str, Any]:
        ...

    def status(self) -> dict[str, Any]:
        ...

    def start(self) -> dict[str, Any]:
        ...

    def stop(self) -> dict[str, Any]:
        ...

    def profiles(self) -> list[BrowserProfile]:
        ...

    def list_tabs(self) -> list[BrowserTab]:
        ...

    def open_tab(self, url: str, *, label: str = "") -> BrowserTab:
        ...

    def focus_tab(self, target_id: str) -> BrowserTab:
        ...

    def close_tab(self, target_id: str) -> dict[str, Any]:
        ...

    def navigate(self, url: str, *, target_id: str | None = None, wait_ms: int = 5000) -> BrowserSnapshot:
        ...

    def snapshot(self, *, target_id: str | None = None, options: BrowserSnapshotOptions | None = None) -> BrowserSnapshot:
        ...

    def act(self, request: BrowserActRequest, *, target_id: str | None = None) -> BrowserActResult:
        ...

    def screenshot(self, *, target_id: str | None = None, full_page: bool = True, filename: str | None = None) -> dict[str, Any]:
        ...

    def close(self) -> None:
        ...


class LocalCDPBrowserController:
    """
    通过Chrome开发者工具协议(CDP)连接本地Chrome/Edge浏览器的桥接类
    负责：启动浏览器、建立CDP连接、执行所有页面操作
    """

    def __init__(
        self,
        *,
        workspace: Path,                # 工作目录
        browser_executable: str = "",   # 浏览器可执行文件路径
        user_data_dir: str = "",        # 用户数据目录（保存登录信息）
        screenshot_dir: str = "",        # 截图保存目录
        launch_flags: list[str] | None = None, # 浏览器启动参数
        connect_timeout_seconds: int = 20,     # 连接超时
        navigation_timeout_ms: int = 5000,     # 页面导航超时
        cdp_http_timeout_seconds: int = 3,     # CDP HTTP请求超时
        cdp_response_timeout_seconds: int | None = None, # CDP响应超时
        action_timeout_ms: int = 1500,   # 操作超时
        shutdown_timeout_seconds: int = 5, # 关闭超时
    ) -> None:
        self.workspace = workspace.resolve()
        self.browser_executable = browser_executable.strip()
        # 解析用户数据目录（默认在工作目录下）
        self.user_data_dir = self._resolve_workspace_path(user_data_dir, self.workspace / ".pp-agent" / "browser" / "profile")
        self.screenshot_dir = self._resolve_workspace_path(screenshot_dir, self.workspace / ".pp-agent" / "browser" / "screenshots")
        self.launch_flags = list(launch_flags or [])
        # 初始化各类超时时间（确保最小值合理）
        self.connect_timeout_seconds = max(5, int(connect_timeout_seconds))
        self.navigation_timeout_ms = max(0, int(navigation_timeout_ms))
        self.cdp_http_timeout_seconds = max(1, int(cdp_http_timeout_seconds))
        self.cdp_response_timeout_seconds = max(1, int(cdp_response_timeout_seconds or self.connect_timeout_seconds))
        self.action_timeout_ms = max(0, int(action_timeout_ms))
        self.shutdown_timeout_seconds = max(1, int(shutdown_timeout_seconds))
        # 浏览器进程对象
        self._process: subprocess.Popen[str] | None = None
        # 页面WebSocket客户端缓存：target_id -> websocket连接
        self._clients: dict[str, Any] = {}
        # 浏览器级WebSocket URL
        self._browser_ws_url: str | None = None
        # 当前激活页面的WebSocket URL
        self._page_ws_url: str | None = None
        # CDP调试端口
        self._devtools_port: int | None = None
        # CDP请求ID（自增）
        self._request_id = 0
        # 标签页自定义名称映射
        self._tab_labels: dict[str, str] = {}
        # 元素引用映射：target_id -> {ref: BrowserNode}
        self._ref_maps: dict[str, dict[str, BrowserNode]] = {}
        # 快照ID映射
        self._snapshot_ids: dict[str, str] = {}
        # 已失效的目标标签页集合
        self._stale_targets: set[str] = set()
        # 最后一次错误信息
        self._last_error = ""
        # 最近操作记录（最多50条）
        self._actions: deque[dict[str, Any]] = deque(maxlen=50)

    def doctor(self) -> dict[str, Any]:
        status = self.status()
        status["user_data_dir"] = str(self.user_data_dir)
        status["screenshot_dir"] = str(self.screenshot_dir)
        status["browser_executable_configured"] = bool(self.browser_executable)
        status["browser_executable"] = self._diagnose_browser_executable()
        status["profile_writable"] = self._diagnose_writable_dir(self.user_data_dir)
        status["screenshots_writable"] = self._diagnose_writable_dir(self.screenshot_dir)
        status["recent_actions"] = list(self._actions)
        return status

    def status(self) -> dict[str, Any]:
        tabs: list[BrowserTab] = []
        try:
            if self._devtools_port is not None:
                tabs = self.list_tabs()
        except Exception as exc:
            self._last_error = str(exc)
        return {
            "controller": "local_cdp",
            "running": self._process is not None and self._process.poll() is None,
            "controller_ready": bool(self._page_ws_url),
            "cdp_port": self._devtools_port,
            "tabs_count": len(tabs),
            "last_error": self._last_error,
            "timeouts": {
                "connect_timeout_seconds": self.connect_timeout_seconds,
                "navigation_timeout_ms": self.navigation_timeout_ms,
                "cdp_http_timeout_seconds": self.cdp_http_timeout_seconds,
                "cdp_response_timeout_seconds": self.cdp_response_timeout_seconds,
                "action_timeout_ms": self.action_timeout_ms,
                "shutdown_timeout_seconds": self.shutdown_timeout_seconds,
            },
            "recent_actions": list(self._actions),
        }

    def start(self) -> dict[str, Any]:
        return self._record_action("start", lambda: self._start_and_status())

    def stop(self) -> dict[str, Any]:
        return self._record_action("stop", lambda: self._stop_and_status())

    def profiles(self) -> list[BrowserProfile]:
        return [
            BrowserProfile(name="default", mode="host", user_data_dir=str(self.user_data_dir), enabled=True, explicitly_enabled=True),
            BrowserProfile(name="isolated", mode="host", user_data_dir=str(self.user_data_dir), enabled=True, explicitly_enabled=True),
            BrowserProfile(name="user", mode="host", user_data_dir="", enabled=False, explicitly_enabled=False),
            BrowserProfile(name="remote", mode="host", cdp_url="", attach_only=True, enabled=False, explicitly_enabled=False),
        ]

    def list_tabs(self) -> list[BrowserTab]:
        return self._record_action("tabs.list", self._list_tabs_impl)

    def open_tab(self, url: str, *, label: str = "") -> BrowserTab:
        return self._record_action("tabs.open", lambda: self._open_tab_impl(url, label=label), {"url": url, "label": label})

    # 打开标签页的具体实现
    def _open_tab_impl(self, url: str, *, label: str = "") -> BrowserTab:
        # 确保浏览器已启动
        self._start_browser_if_needed()
        # 连接浏览器WebSocket
        browser_client = self._connect_browser_client(self._browser_ws_url or "")
        try:
            # 调用CDP接口创建新标签页
            payload = self._call(browser_client, "Target.createTarget", {"url": url})
            target_id = str(payload.get("result", {}).get("targetId") or "")
        finally:
            browser_client.close()
        # 设置标签页名称
        if label:
            self._tab_labels[target_id] = label
        # 标记为需要重新快照
        self._stale_targets.add(target_id)
        # 聚焦新标签页
        self.focus_tab(target_id)
        # 等待页面加载完成
        self._wait_ready(self._client_for_target(target_id), wait_ms=self.navigation_timeout_ms)
        return self._tab_for_target(target_id)

    def focus_tab(self, target_id: str) -> BrowserTab:
        return self._record_action("tabs.focus", lambda: self._focus_tab_impl(target_id), {"target_id": target_id})

    # 聚焦标签页具体实现
    def _focus_tab_impl(self, target_id: str) -> BrowserTab:
        self._start_browser_if_needed()
        # 解析目标ID
        resolved = self._resolve_target_id(target_id)
        browser_client = self._connect_browser_client(self._browser_ws_url or "")
        try:
            # 调用CDP激活标签页
            self._call(browser_client, "Target.activateTarget", {"targetId": resolved})
        finally:
            browser_client.close()
        # 更新当前页面WebSocket
        self._page_ws_url = self._ws_url_for_target(resolved)
        self._stale_targets.add(resolved)
        return self._tab_for_target(resolved)

    def close_tab(self, target_id: str) -> dict[str, Any]:
        return self._record_action("tabs.close", lambda: self._close_tab_impl(target_id), {"target_id": target_id})

    # 关闭标签页具体实现
    def _close_tab_impl(self, target_id: str) -> dict[str, Any]:
        self._start_browser_if_needed()
        resolved = self._resolve_target_id(target_id)
        browser_client = self._connect_browser_client(self._browser_ws_url or "")
        try:
            # 调用CDP关闭标签页
            self._call(browser_client, "Target.closeTarget", {"targetId": resolved})
        finally:
            browser_client.close()
        # 清理缓存数据
        self._clients.pop(resolved, None)
        self._tab_labels.pop(resolved, None)
        self._ref_maps.pop(resolved, None)
        self._snapshot_ids.pop(resolved, None)
        self._stale_targets.discard(resolved)
        # 如果关闭的是当前激活页，重新发现激活页
        if self._page_ws_url and self._target_id_from_ws(self._page_ws_url) == resolved:
            self._page_ws_url = self._discover_page_ws_url(self._devtools_port or 0)
        return {"closed": True, "target_id": resolved}

    def navigate(self, url: str, *, target_id: str | None = None, wait_ms: int = 5000) -> BrowserSnapshot:
        return self._record_action(
            "navigate",
            lambda: self._navigate_impl(url, target_id=target_id, wait_ms=wait_ms),
            {"url": url, "target_id": target_id, "wait_ms": wait_ms},
        )

    # 导航具体实现
    def _navigate_impl(self, url: str, *, target_id: str | None = None, wait_ms: int = 5000) -> BrowserSnapshot:
        # 获取页面客户端
        client = self._client_for_target_id(target_id)
        # 执行导航
        self._call(client, "Page.navigate", {"url": url})
        # 等待加载完成
        self._wait_ready(client, wait_ms=wait_ms)
        resolved = self._target_id_for_client(client, target_id)
        self._stale_targets.add(resolved)
        # 返回新页面快照
        return self.snapshot(target_id=resolved)

    def snapshot(self, *, target_id: str | None = None, options: BrowserSnapshotOptions | None = None) -> BrowserSnapshot:
        return self._record_action(
            "snapshot",
            lambda: self._snapshot_impl(target_id=target_id, options=options),
            {"target_id": target_id, "options": options.model_dump(mode="python") if options is not None else {}},
        )

    # 快照具体实现（核心）
    def _snapshot_impl(self, *, target_id: str | None = None, options: BrowserSnapshotOptions | None = None) -> BrowserSnapshot:
        options = options or BrowserSnapshotOptions()
        client = self._client_for_target_id(target_id)
        target = self._target_id_for_client(client, target_id)
        # 执行JS获取页面结构和元素信息
        payload = self._evaluate(client, self._snapshot_expression(options))
        value = self._response_value(payload)
        # 转换为BrowserNode对象
        nodes = [self._node_from_payload(index + 1, item) for index, item in enumerate(value.get("nodes", []) or [])]
        snapshot_id = str(uuid.uuid4())
        # 缓存元素引用映射
        self._ref_maps[target] = {node.ref: node for node in nodes}
        self._snapshot_ids[target] = snapshot_id
        self._stale_targets.discard(target)
        # 返回快照对象
        return BrowserSnapshot(
            snapshot_id=snapshot_id,
            target_id=target,
            url=str(value.get("url", "")),
            title=str(value.get("title", "")),
            ready_state=str(value.get("readyState", "")),
            body_text=str(value.get("bodyText", ""))[: options.max_chars],
            html=None,
            nodes=nodes,
            stats={"node_count": len(nodes), "compact": options.compact, "interactive": options.interactive},
        )
    
    def act(self, request: BrowserActRequest, *, target_id: str | None = None) -> BrowserActResult:
        return self._record_action(
            "act",
            lambda: self._act_impl(request, target_id=target_id),
            {"target_id": target_id, "kind": request.kind, "ref": request.ref},
        )

    # 交互操作具体实现（核心）
    def _act_impl(self, request: BrowserActRequest, *, target_id: str | None = None) -> BrowserActResult:
        client = self._client_for_target_id(target_id)
        target = self._target_id_for_client(client, target_id)
        
        # 处理无需元素引用的操作：resize、close、wait
        if request.kind in {"resize", "close", "wait"}:
            self._act_without_ref(client, target, request)
            snapshot = self.snapshot(target_id=target)
            return BrowserActResult(snapshot=snapshot, action=request.kind, requires_resnapshot=request.kind != "wait")
        
        # 必须提供元素引用
        if not request.ref:
            raise ValueError(f"browser.act kind '{request.kind}' requires ref from browser.snapshot.")
        
        # 如果目标已失效，返回新快照
        if target in self._stale_targets:
            stale = self.snapshot(target_id=target)
            return BrowserActResult(snapshot=stale, action=request.kind, requires_resnapshot=True, stale_ref=True)
        
        # 获取要操作的元素
        node = self._ref_maps.get(target, {}).get(request.ref)
        if node is None:
            stale = self.snapshot(target_id=target)
            return BrowserActResult(snapshot=stale, action=request.kind, requires_resnapshot=True, stale_ref=True)
        
        # 执行交互JS
        self._evaluate(client, self._act_expression(node.selector, request))
        # 等待操作完成
        self._wait_ready(client, wait_ms=request.timeout_ms or self.action_timeout_ms)
        self._stale_targets.add(target)
        # 返回操作后的快照
        snapshot = self.snapshot(target_id=target)
        return BrowserActResult(
            snapshot=snapshot, 
            action=request.kind, 
            requires_resnapshot=request.kind in {"click", "type", "select", "fill", "press"}
        )

    def screenshot(self, *, target_id: str | None = None, full_page: bool = True, filename: str | None = None) -> dict[str, Any]:
        return self._record_action(
            "screenshot",
            lambda: self._screenshot_impl(target_id=target_id, full_page=full_page, filename=filename),
            {"target_id": target_id, "full_page": full_page, "filename": filename},
        )

    def _screenshot_impl(self, *, target_id: str | None = None, full_page: bool = True, filename: str | None = None) -> dict[str, Any]:
        client = self._client_for_target_id(target_id)
        payload = self._call(
            client,
            "Page.captureScreenshot",
            {"format": "png", "captureBeyondViewport": bool(full_page)},
        )
        raw = base64.b64decode(payload["result"]["data"])
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        name = filename or f"screenshot-{int(time.time() * 1000)}.png"
        path = self.screenshot_dir / name
        path.write_bytes(raw)
        return {"path": str(path), "bytes": len(raw), "full_page": bool(full_page)}

    def close(self) -> None:
        for client in list(self._clients.values()):
            try:
                client.close()
            except Exception:
                pass
        self._clients = {}
        self._page_ws_url = None
        self._browser_ws_url = None
        self._devtools_port = None
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=self.shutdown_timeout_seconds)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._process = None

    def _start_and_status(self) -> dict[str, Any]:
        self._start_browser_if_needed()
        return self.status()

    def _stop_and_status(self) -> dict[str, Any]:
        self.close()
        return self.status()

    def _list_tabs_impl(self) -> list[BrowserTab]:
        self._start_browser_if_needed()
        targets = self._list_page_targets()
        active_target = self._target_id_from_ws(self._page_ws_url or "")
        tabs: list[BrowserTab] = []
        for target in targets:
            target_id = str(target.get("id") or "")
            tabs.append(
                BrowserTab(
                    tab_id=target_id,
                    target_id=target_id,
                    label=self._tab_labels.get(target_id, ""),
                    url=str(target.get("url") or ""),
                    title=str(target.get("title") or ""),
                    active=target_id == active_target,
                )
            )
        return tabs

    def _record_action(self, action: str, fn, details: dict[str, Any] | None = None):
        started = time.time()
        entry: dict[str, Any] = {
            "action": action,
            "started_at": started,
            "ok": False,
            "duration_ms": 0,
            "details": {key: value for key, value in (details or {}).items() if value not in (None, "")},
        }
        try:
            result = fn()
            entry["ok"] = True
            return result
        except Exception as exc:
            self._last_error = str(exc)
            entry["error_type"] = type(exc).__name__
            entry["error"] = str(exc)
            raise
        finally:
            entry["duration_ms"] = int((time.time() - started) * 1000)
            self._actions.append(entry)

    def _act_without_ref(self, client, target: str, request: BrowserActRequest) -> None:
        if request.kind == "resize":
            width = int(request.width or 1280)
            height = int(request.height or 720)
            self._call(client, "Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
            return
        if request.kind == "close":
            self.close_tab(target)
            return
        if request.kind == "wait":
            time.sleep(max(0, request.timeout_ms or 1000) / 1000.0)
            return
        raise ValueError(f"Unsupported browser.act kind without ref: {request.kind}")

    def _client_for_target_id(self, target_id: str | None):
        if target_id:
            return self._client_for_target(self._resolve_target_id(target_id))
        return self._ensure_active_client()

    def _ensure_active_client(self):
        self._start_browser_if_needed()
        target = self._target_id_from_ws(self._page_ws_url or "")
        return self._client_for_target(target)

    def _client_for_target(self, target_id: str):
        if target_id in self._clients:
            return self._clients[target_id]
        ws_url = self._ws_url_for_target(target_id)
        client = self._connect_page_client(ws_url)
        self._call(client, "Page.enable", {})
        self._call(client, "Runtime.enable", {})
        self._call(client, "DOM.enable", {})
        self._call(client, "Network.enable", {})
        self._clients[target_id] = client
        return client

    def _target_id_for_client(self, client, target_id: str | None) -> str:
        if target_id:
            return self._resolve_target_id(target_id)
        for candidate, candidate_client in self._clients.items():
            if candidate_client is client:
                return candidate
        active = self._target_id_from_ws(self._page_ws_url or "")
        return active

    def _start_browser_if_needed(self) -> None:
        if self._page_ws_url is not None and self._devtools_port is not None:
            return
        browser_executable = self._resolve_browser_executable()
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._remove_stale_devtools_port()
        args = [
            browser_executable,
            f"--user-data-dir={self.user_data_dir}",
            "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-popup-blocking",
            "--disable-features=DialMediaRouteProvider",
            "--new-window",
            *self.launch_flags,
            "about:blank",
        ]
        try:
            self._process = subprocess.Popen(args, cwd=str(self.workspace), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
            port, browser_ws_path = self._wait_for_devtools_port()
            self._devtools_port = port
            self._browser_ws_url = f"ws://127.0.0.1:{port}{browser_ws_path}"
            self._page_ws_url = self._discover_page_ws_url(port)
        except Exception as exc:
            self._last_error = str(exc)
            self.close()
            raise

    def _connect_page_client(self, ws_url: str):
        import websocket

        if not ws_url:
            raise RuntimeError("Browser target websocket is unavailable.")
        return websocket.create_connection(ws_url, timeout=self.connect_timeout_seconds, suppress_origin=True)

    def _connect_browser_client(self, ws_url: str):
        import websocket

        if not ws_url:
            raise RuntimeError("Browser websocket is unavailable.")
        return websocket.create_connection(ws_url, timeout=self.connect_timeout_seconds, suppress_origin=True)

    def _wait_for_devtools_port(self) -> tuple[int, str]:
        devtools_file = self.user_data_dir / "DevToolsActivePort"
        deadline = time.time() + self.connect_timeout_seconds
        last_error = ""
        while time.time() < deadline:
            if self._process is not None and self._process.poll() is not None:
                raise RuntimeError(
                    f"Browser exited before DevTools became available (exit code {self._process.returncode}). "
                    f"executable={self._diagnose_browser_executable().get('path', '')} "
                    f"profile={self.user_data_dir}"
                )
            if devtools_file.exists():
                try:
                    lines = [line.strip() for line in devtools_file.read_text(encoding="utf-8").splitlines() if line.strip()]
                    if len(lines) >= 2 and lines[0].isdigit():
                        return int(lines[0]), lines[1]
                    last_error = "DevToolsActivePort was present but malformed."
                except Exception as exc:
                    last_error = str(exc)
            time.sleep(0.2)
        suffix = f" Last error: {last_error}" if last_error else ""
        raise RuntimeError(
            f"Timed out waiting for browser DevTools port after {self.connect_timeout_seconds}s.{suffix} "
            f"executable={self._diagnose_browser_executable().get('path', '')} profile={self.user_data_dir}"
        )

    def _discover_page_ws_url(self, port: int) -> str:
        deadline = time.time() + self.connect_timeout_seconds
        version_url = f"http://127.0.0.1:{port}/json/version"
        browser_ws = self._browser_ws_url
        created_target_id: str | None = None
        create_attempted = False
        last_error = ""
        while time.time() < deadline:
            try:
                page_targets = self._list_page_targets(port=port)
                for target in page_targets:
                    if created_target_id and target.get("id") != created_target_id:
                        continue
                    if target.get("url") != "chrome://newtab/":
                        return str(target["webSocketDebuggerUrl"])
                if browser_ws is None:
                    with httpx.Client(timeout=self.cdp_http_timeout_seconds) as client:
                        browser_ws = str(client.get(version_url).json()["webSocketDebuggerUrl"])
            except Exception as exc:
                last_error = str(exc)
            if browser_ws is not None and not create_attempted:
                try:
                    browser_client = self._connect_browser_client(browser_ws)
                    payload = self._call(browser_client, "Target.createTarget", {"url": "about:blank"})
                    created_target_id = str(payload.get("result", {}).get("targetId") or "")
                    create_attempted = True
                except Exception as exc:
                    last_error = str(exc)
                finally:
                    try:
                        browser_client.close()
                    except Exception:
                        pass
            time.sleep(0.2)
        suffix = f" Last error: {last_error}" if last_error else ""
        raise RuntimeError(f"Timed out waiting for browser page target after {self.connect_timeout_seconds}s.{suffix}")

    def _list_page_targets(self, *, port: int | None = None) -> list[dict[str, Any]]:
        port = port or self._devtools_port
        if port is None:
            return []
        list_url = f"http://127.0.0.1:{port}/json/list"
        with httpx.Client(timeout=self.cdp_http_timeout_seconds) as client:
            page_targets = client.get(list_url).json()
        return [
            target
            for target in page_targets
            if target.get("type") in {"page", "tab"} and target.get("webSocketDebuggerUrl")
        ]

    def _ws_url_for_target(self, target_id: str) -> str:
        for target in self._list_page_targets():
            if str(target.get("id") or "") == target_id:
                return str(target["webSocketDebuggerUrl"])
        raise RuntimeError(f"Browser tab not found: {target_id}")

    def _tab_for_target(self, target_id: str) -> BrowserTab:
        for tab in self.list_tabs():
            if tab.target_id == target_id:
                return tab
        return BrowserTab(tab_id=target_id, target_id=target_id, label=self._tab_labels.get(target_id, ""))

    def _resolve_target_id(self, target_id: str) -> str:
        for tab in self.list_tabs():
            if target_id in {tab.label, tab.tab_id, tab.target_id}:
                return tab.target_id
        raise RuntimeError(f"Browser tab not found: {target_id}")

    @staticmethod
    def _target_id_from_ws(ws_url: str) -> str:
        return ws_url.rstrip("/").split("/")[-1]

    def _resolve_browser_executable(self) -> str:
        if self.browser_executable:
            path = Path(self.browser_executable).expanduser()
            if path.exists():
                return str(path)
            resolved = shutil.which(self.browser_executable)
            if resolved:
                return resolved
            raise FileNotFoundError(f"Browser executable not found: {self.browser_executable}")
        candidates = [
            shutil.which("chrome"),
            shutil.which("google-chrome"),
            shutil.which("msedge"),
            r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
            r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return str(candidate)
        raise FileNotFoundError("No local Chrome/Edge executable found. Set capabilities.browser.browser_executable.")

    def _diagnose_browser_executable(self) -> dict[str, Any]:
        try:
            path = self._resolve_browser_executable()
            return {"ok": True, "path": path}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _diagnose_writable_dir(path: Path) -> dict[str, Any]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".pp-echo-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return {"ok": True, "path": str(path)}
        except Exception as exc:
            return {"ok": False, "path": str(path), "error": str(exc)}

    def _resolve_workspace_path(self, value: str, fallback: Path) -> Path:
        if not value:
            return fallback.resolve()
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        return path.resolve()

    def _remove_stale_devtools_port(self) -> None:
        devtools_file = self.user_data_dir / "DevToolsActivePort"
        if not devtools_file.exists():
            return
        try:
            devtools_file.unlink()
        except OSError:
            pass

    def _call(self, client, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        client.send(json.dumps({"id": request_id, "method": method, "params": params}))
        deadline = time.time() + self.cdp_response_timeout_seconds
        while time.time() < deadline:
            raw = client.recv()
            payload = json.loads(raw)
            if payload.get("id") != request_id:
                continue
            if "error" in payload:
                raise RuntimeError(f"CDP {method} failed: {payload['error']}")
            return payload
        raise TimeoutError(f"Timed out waiting for CDP response to {method} after {self.cdp_response_timeout_seconds}s")

    def _evaluate(self, client, expression: str) -> dict[str, Any]:
        return self._call(
            client,
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
            },
        )

    def _response_value(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = payload.get("result", {}).get("result", {})
        if result.get("subtype") == "error":
            raise RuntimeError(str(result.get("description") or result.get("value") or "Browser evaluation failed."))
        value = result.get("value")
        if not isinstance(value, dict):
            raise RuntimeError("Browser evaluation did not return an object by value.")
        return value

    def _wait_ready(self, client, *, wait_ms: int) -> None:
        deadline = time.time() + max(0, wait_ms) / 1000.0
        while time.time() < deadline:
            try:
                payload = self._evaluate(client, "(() => ({ value: document.readyState }))()")
                value = self._response_value(payload)
                if str(value.get("value", "")) in {"interactive", "complete"}:
                    return
            except Exception:
                pass
            time.sleep(0.15)

    def _snapshot_expression(self, options: BrowserSnapshotOptions) -> str:
        interactive_only = "true" if options.interactive else "false"
        max_chars = int(options.max_chars)
        return (
            "(() => {"
            "const interactiveOnly = " + interactive_only + ";"
            "const roleFor = (el) => el.getAttribute('role') || ({A:'link',BUTTON:'button',INPUT:'textbox',TEXTAREA:'textbox',SELECT:'combobox'}[el.tagName] || el.tagName.toLowerCase());"
            "const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return !!(r.width && r.height) && s.visibility !== 'hidden' && s.display !== 'none'; };"
            "const cssPath = (el) => { if (el.id) return '#' + CSS.escape(el.id); const parts = []; while (el && el.nodeType === 1 && el !== document.body) { let part = el.tagName.toLowerCase(); const parent = el.parentElement; if (parent) { const same = Array.from(parent.children).filter(x => x.tagName === el.tagName); if (same.length > 1) part += ':nth-of-type(' + (same.indexOf(el) + 1) + ')'; } parts.unshift(part); el = parent; } return parts.length ? parts.join(' > ') : 'body'; };"
            "const candidates = Array.from(document.querySelectorAll('a,button,input,textarea,select,[role],summary,[contenteditable=true],[tabindex]'));"
            "const nodes = candidates.filter(el => !interactiveOnly || visible(el)).slice(0, 200).map(el => { const r = el.getBoundingClientRect(); const labels = el.id ? Array.from(document.querySelectorAll('label[for=\"' + CSS.escape(el.id) + '\"]')).map(l => l.innerText.trim()).join(' ') : ''; return { role: roleFor(el), text: (el.innerText || el.value || '').trim().slice(0, 240), name: (el.getAttribute('aria-label') || el.getAttribute('name') || '').trim(), label: labels || (el.closest('label') ? el.closest('label').innerText.trim() : ''), placeholder: el.getAttribute('placeholder') || '', href: el.href || '', visible: visible(el), bounds: {x:r.x,y:r.y,width:r.width,height:r.height}, selector: cssPath(el) }; });"
            f"return {{url: location.href, title: document.title, readyState: document.readyState, bodyText: (document.body ? document.body.innerText : '').slice(0, {max_chars}), nodes}};"
            "})()"
        )

    def _act_expression(self, selector: str, request: BrowserActRequest) -> str:
        selector_json = json.dumps(selector)
        text_json = json.dumps(request.text or "")
        key_json = json.dumps(request.key or "")
        values_json = json.dumps(request.values)
        kind = request.kind
        return (
            "(() => {"
            f"const el = document.querySelector({selector_json});"
            "if (!el) throw new Error('Ref target not found');"
            f"const kind = {json.dumps(kind)};"
            f"const text = {text_json};"
            f"const key = {key_json};"
            f"const values = {values_json};"
            "el.scrollIntoView({block:'center', inline:'center'});"
            "if (kind === 'click') { el.click(); return {ok:true}; }"
            "if (kind === 'hover') { el.dispatchEvent(new MouseEvent('mouseover', {bubbles:true})); return {ok:true}; }"
            "if (kind === 'type' || kind === 'fill') { if ('value' in el) { el.value = kind === 'fill' ? text : String(el.value || '') + text; } else { el.textContent = text; } el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); return {ok:true}; }"
            "if (kind === 'select') { if ('value' in el && values.length) el.value = values[0]; el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); return {ok:true}; }"
            "if (kind === 'press') { el.dispatchEvent(new KeyboardEvent('keydown', {key, bubbles:true})); el.dispatchEvent(new KeyboardEvent('keyup', {key, bubbles:true})); return {ok:true}; }"
            "if (kind === 'drag') { throw new Error('browser.act drag is reserved for a future controller implementation'); }"
            "throw new Error('Unsupported browser.act kind: ' + kind);"
            "})()"
        )

    @staticmethod
    def _node_from_payload(index: int, payload: dict[str, Any]) -> BrowserNode:
        bounds = payload.get("bounds") if isinstance(payload.get("bounds"), dict) else {}
        return BrowserNode(
            ref=f"e{index}",
            role=str(payload.get("role") or ""),
            text=str(payload.get("text") or ""),
            name=str(payload.get("name") or ""),
            label=str(payload.get("label") or ""),
            placeholder=str(payload.get("placeholder") or ""),
            href=str(payload.get("href") or ""),
            visible=bool(payload.get("visible", True)),
            bounds=BrowserBounds(
                x=float(bounds.get("x") or 0),
                y=float(bounds.get("y") or 0),
                width=float(bounds.get("width") or 0),
                height=float(bounds.get("height") or 0),
            ),
            selector=str(payload.get("selector") or ""),
        )


class FakeBrowserController:
    """
    In-memory controller for focused tests.
    """

    def __init__(self) -> None:
        self.url = "about:blank"
        self.title = "Blank"
        self.ready_state = "complete"
        self.body_text = ""
        self.html = "<html><body><button id='submit'>Submit</button><input id='query' placeholder='Search'></body></html>"
        self.clicks: list[str] = []
        self.types: list[tuple[str, str, bool]] = []
        self.screenshots: list[str] = []
        self.tabs: dict[str, BrowserTab] = {"tab-1": BrowserTab(tab_id="tab-1", target_id="tab-1", label="default", url=self.url, title=self.title, active=True)}
        self.ref_maps: dict[str, dict[str, BrowserNode]] = {}
        self.stale_targets: set[str] = set()

    def doctor(self) -> dict[str, Any]:
        return {**self.status(), "controller": "fake"}

    def status(self) -> dict[str, Any]:
        return {"controller": "fake", "running": True, "controller_ready": True, "tabs_count": len(self.tabs), "last_error": ""}

    def start(self) -> dict[str, Any]:
        return self.status()

    def stop(self) -> dict[str, Any]:
        return {"controller": "fake", "running": False, "controller_ready": False, "tabs_count": 0, "last_error": ""}

    def profiles(self) -> list[BrowserProfile]:
        return [
            BrowserProfile(name="default", mode="host", enabled=True, explicitly_enabled=True),
            BrowserProfile(name="isolated", mode="host", enabled=True, explicitly_enabled=True),
            BrowserProfile(name="user", mode="host", enabled=False),
            BrowserProfile(name="remote", mode="host", enabled=False, attach_only=True),
        ]

    def list_tabs(self) -> list[BrowserTab]:
        return list(self.tabs.values())

    def open_tab(self, url: str, *, label: str = "") -> BrowserTab:
        target = f"tab-{len(self.tabs) + 1}"
        for tab in self.tabs.values():
            tab.active = False
        tab = BrowserTab(tab_id=target, target_id=target, label=label, url=url, title=f"Page: {url}", active=True)
        self.tabs[target] = tab
        self.url = url
        self.title = tab.title
        self.body_text = f"Visited {url}"
        return tab

    def focus_tab(self, target_id: str) -> BrowserTab:
        resolved = self._resolve_tab(target_id).target_id
        for tab in self.tabs.values():
            tab.active = tab.target_id == resolved
        return self.tabs[resolved]

    def close_tab(self, target_id: str) -> dict[str, Any]:
        resolved = self._resolve_tab(target_id).target_id
        self.tabs.pop(resolved, None)
        return {"closed": True, "target_id": resolved}

    def navigate(self, url: str, *, target_id: str | None = None, wait_ms: int = 5000) -> BrowserSnapshot:
        tab = self._resolve_tab(target_id) if target_id else self._active_tab()
        tab.url = url
        tab.title = f"Page: {url}"
        self.url = url
        self.title = tab.title
        self.body_text = f"Visited {url}"
        self.stale_targets.add(tab.target_id)
        return self.snapshot(target_id=tab.target_id)

    def snapshot(self, *, target_id: str | None = None, options: BrowserSnapshotOptions | None = None) -> BrowserSnapshot:
        tab = self._resolve_tab(target_id) if target_id else self._active_tab()
        nodes = [
            BrowserNode(ref="e1", role="textbox", text="", name="query", placeholder="Search", bounds=BrowserBounds(width=120, height=20), selector="#query"),
            BrowserNode(ref="e2", role="button", text="Submit", name="submit", bounds=BrowserBounds(width=80, height=24), selector="#submit"),
        ]
        self.ref_maps[tab.target_id] = {node.ref: node for node in nodes}
        self.stale_targets.discard(tab.target_id)
        return BrowserSnapshot(
            snapshot_id=str(uuid.uuid4()),
            target_id=tab.target_id,
            url=tab.url,
            title=tab.title,
            ready_state=self.ready_state,
            body_text=self.body_text,
            html=None,
            nodes=nodes,
            stats={"node_count": len(nodes)},
        )

    def act(self, request: BrowserActRequest, *, target_id: str | None = None) -> BrowserActResult:
        tab = self._resolve_tab(target_id) if target_id else self._active_tab()
        if request.kind in {"resize", "close", "wait"}:
            snapshot = self.snapshot(target_id=tab.target_id)
            return BrowserActResult(snapshot=snapshot, action=request.kind, requires_resnapshot=request.kind != "wait")
        if not request.ref:
            raise ValueError(f"browser.act kind '{request.kind}' requires ref from browser.snapshot.")
        if tab.target_id in self.stale_targets or request.ref not in self.ref_maps.get(tab.target_id, {}):
            return BrowserActResult(snapshot=self.snapshot(target_id=tab.target_id), action=request.kind, stale_ref=True, requires_resnapshot=True)
        node = self.ref_maps[tab.target_id][request.ref]
        if request.kind == "click":
            self.clicks.append(node.selector)
            self.body_text = f"Clicked {node.selector}"
        if request.kind in {"type", "fill"}:
            self.types.append((node.selector, request.text or "", False))
            self.body_text = f"Typed into {node.selector}: {request.text or ''}"
        self.stale_targets.add(tab.target_id)
        return BrowserActResult(snapshot=self.snapshot(target_id=tab.target_id), action=request.kind, requires_resnapshot=request.kind in {"click", "type", "select", "fill"})

    def screenshot(self, *, target_id: str | None = None, full_page: bool = True, filename: str | None = None) -> dict[str, Any]:
        name = filename or f"shot-{len(self.screenshots) + 1}.png"
        self.screenshots.append(name)
        return {"path": str(Path("fake-browser") / name), "bytes": 1, "full_page": bool(full_page)}

    def close(self) -> None:
        return None

    def _active_tab(self) -> BrowserTab:
        for tab in self.tabs.values():
            if tab.active:
                return tab
        return next(iter(self.tabs.values()))

    def _resolve_tab(self, target_id: str | None) -> BrowserTab:
        if not target_id:
            return self._active_tab()
        for tab in self.tabs.values():
            if target_id in {tab.label, tab.tab_id, tab.target_id}:
                return tab
        raise RuntimeError(f"Browser tab not found: {target_id}")
