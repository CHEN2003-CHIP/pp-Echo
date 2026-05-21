from __future__ import annotations

import base64
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx


@dataclass
class BrowserSnapshot:
    url: str
    title: str
    ready_state: str
    body_text: str
    html: str | None = None


class BrowserController(Protocol):
    def read_state(self) -> BrowserSnapshot:
        ...

    def navigate(self, url: str, *, wait_ms: int = 5000) -> BrowserSnapshot:
        ...

    def click(self, selector: str, *, wait_ms: int = 1500) -> BrowserSnapshot:
        ...

    def type(self, selector: str, text: str, *, press_enter: bool = False, wait_ms: int = 1500) -> BrowserSnapshot:
        ...

    def screenshot(self, *, full_page: bool = True, filename: str | None = None) -> dict[str, Any]:
        ...

    def close(self) -> None:
        ...


class LocalCDPBrowserController:
    """
    Minimal local Chrome/Edge bridge via the DevTools protocol.
    """

    def __init__(
        self,
        *,
        workspace: Path,
        browser_executable: str = "",
        user_data_dir: str = "",
        screenshot_dir: str = "",
        launch_flags: list[str] | None = None,
        connect_timeout_seconds: int = 20,
    ) -> None:
        self.workspace = workspace.resolve()
        self.browser_executable = browser_executable.strip()
        self.user_data_dir = self._resolve_workspace_path(user_data_dir, self.workspace / ".pp-agent" / "browser" / "profile")
        self.screenshot_dir = self._resolve_workspace_path(screenshot_dir, self.workspace / ".pp-agent" / "browser" / "screenshots")
        self.launch_flags = list(launch_flags or [])
        self.connect_timeout_seconds = max(5, int(connect_timeout_seconds))
        self._process: subprocess.Popen[str] | None = None
        self._client: Any = None
        self._browser_ws_url: str | None = None
        self._page_ws_url: str | None = None
        self._request_id = 0

    def read_state(self) -> BrowserSnapshot:
        client = self._ensure_client()
        payload = self._evaluate(
            client,
            "(() => ({"
            "url: location.href,"
            "title: document.title,"
            "readyState: document.readyState,"
            "bodyText: document.body ? document.body.innerText : '',"
            "html: document.documentElement ? document.documentElement.outerHTML : null"
            "}))()",
        )
        value = self._response_value(payload)
        return BrowserSnapshot(
            url=str(value.get("url", "")),
            title=str(value.get("title", "")),
            ready_state=str(value.get("readyState", "")),
            body_text=str(value.get("bodyText", "")),
            html=value.get("html"),
        )

    def navigate(self, url: str, *, wait_ms: int = 5000) -> BrowserSnapshot:
        client = self._ensure_client()
        self._call(client, "Page.navigate", {"url": url})
        self._wait_ready(client, wait_ms=wait_ms)
        return self.read_state()

    def click(self, selector: str, *, wait_ms: int = 1500) -> BrowserSnapshot:
        client = self._ensure_client()
        self._evaluate(
            client,
            "(() => {"
            f"const selector = {json.dumps(selector)};"
            "const el = document.querySelector(selector);"
            "if (!el) throw new Error('Selector not found: ' + selector);"
            "el.click();"
            "return true;"
            "})()",
        )
        self._wait_ready(client, wait_ms=wait_ms)
        return self.read_state()

    def type(self, selector: str, text: str, *, press_enter: bool = False, wait_ms: int = 1500) -> BrowserSnapshot:
        client = self._ensure_client()
        self._evaluate(
            client,
            "(() => {"
            f"const selector = {json.dumps(selector)};"
            "const el = document.querySelector(selector);"
            "if (!el) throw new Error('Selector not found: ' + selector);"
            f"const value = {json.dumps(text)};"
            "if ('value' in el) { el.value = value; } else { el.textContent = value; }"
            "el.dispatchEvent(new Event('input', { bubbles: true }));"
            "el.dispatchEvent(new Event('change', { bubbles: true }));"
            "return true;"
            "})()",
        )
        if press_enter:
            self._call(client, "Input.dispatchKeyEvent", {"type": "keyDown", "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13, "key": "Enter", "code": "Enter", "text": "\r"})
            self._call(client, "Input.dispatchKeyEvent", {"type": "keyUp", "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13, "key": "Enter", "code": "Enter"})
        self._wait_ready(client, wait_ms=wait_ms)
        return self.read_state()

    def screenshot(self, *, full_page: bool = True, filename: str | None = None) -> dict[str, Any]:
        client = self._ensure_client()
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
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        self._page_ws_url = None
        self._browser_ws_url = None
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._process = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        self._start_browser_if_needed()
        self._client = self._connect_page_client()
        self._call(self._client, "Page.enable", {})
        self._call(self._client, "Runtime.enable", {})
        self._call(self._client, "DOM.enable", {})
        self._call(self._client, "Network.enable", {})
        return self._client

    def _start_browser_if_needed(self) -> None:
        if self._page_ws_url is not None:
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
            self._browser_ws_url = f"ws://127.0.0.1:{port}{browser_ws_path}"
            self._page_ws_url = self._discover_page_ws_url(port)
        except Exception:
            self.close()
            raise

    def _connect_page_client(self):
        import websocket

        if not self._page_ws_url:
            raise RuntimeError("Browser target websocket is unavailable.")
        return websocket.create_connection(self._page_ws_url, timeout=self.connect_timeout_seconds, suppress_origin=True)

    def _wait_for_devtools_port(self) -> tuple[int, str]:
        devtools_file = self.user_data_dir / "DevToolsActivePort"
        deadline = time.time() + self.connect_timeout_seconds
        last_error = ""
        while time.time() < deadline:
            if self._process is not None and self._process.poll() is not None:
                raise RuntimeError(f"Browser exited before DevTools became available (exit code {self._process.returncode}).")
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
        raise RuntimeError(f"Timed out waiting for browser DevTools port.{suffix}")

    def _discover_page_ws_url(self, port: int) -> str:
        deadline = time.time() + self.connect_timeout_seconds
        version_url = f"http://127.0.0.1:{port}/json/version"
        list_url = f"http://127.0.0.1:{port}/json/list"
        browser_ws = self._browser_ws_url
        created_target_id: str | None = None
        create_attempted = False
        last_error = ""
        while time.time() < deadline:
            try:
                with httpx.Client(timeout=3) as client:
                    page_targets = client.get(list_url).json()
                    for target in page_targets:
                        if not (target.get("type") in {"page", "tab"} and target.get("webSocketDebuggerUrl")):
                            continue
                        if created_target_id and target.get("id") != created_target_id:
                            continue
                        if target.get("url") != "chrome://newtab/":
                            return str(target["webSocketDebuggerUrl"])
                    if browser_ws is None:
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
        raise RuntimeError(f"Timed out waiting for browser page target.{suffix}")

    def _connect_browser_client(self, ws_url: str):
        import websocket

        return websocket.create_connection(ws_url, timeout=self.connect_timeout_seconds, suppress_origin=True)

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
        message = json.dumps({"id": self._request_id, "method": method, "params": params})
        client.send(message)
        deadline = time.time() + self.connect_timeout_seconds
        while time.time() < deadline:
            raw = client.recv()
            payload = json.loads(raw)
            if payload.get("id") != self._request_id:
                continue
            if "error" in payload:
                raise RuntimeError(f"CDP {method} failed: {payload['error']}")
            return payload
        raise TimeoutError(f"Timed out waiting for CDP response to {method}")

    def _evaluate(self, client, expression: str) -> dict[str, Any]:
        payload = self._call(
            client,
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
            },
        )
        return payload

    def _response_value(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = payload.get("result", {}).get("result", {})
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


class FakeBrowserController:
    """
    Small in-memory controller for tests.
    """

    def __init__(self) -> None:
        self.url = "about:blank"
        self.title = "Blank"
        self.ready_state = "complete"
        self.body_text = ""
        self.html = "<html><body></body></html>"
        self.clicks: list[str] = []
        self.types: list[tuple[str, str, bool]] = []
        self.screenshots: list[str] = []

    def read_state(self) -> BrowserSnapshot:
        return BrowserSnapshot(self.url, self.title, self.ready_state, self.body_text, self.html)

    def navigate(self, url: str, *, wait_ms: int = 5000) -> BrowserSnapshot:
        self.url = url
        self.title = f"Page: {url}"
        self.body_text = f"Visited {url}"
        return self.read_state()

    def click(self, selector: str, *, wait_ms: int = 1500) -> BrowserSnapshot:
        self.clicks.append(selector)
        self.body_text = f"Clicked {selector}"
        return self.read_state()

    def type(self, selector: str, text: str, *, press_enter: bool = False, wait_ms: int = 1500) -> BrowserSnapshot:
        self.types.append((selector, text, press_enter))
        self.body_text = f"Typed into {selector}: {text}"
        return self.read_state()

    def screenshot(self, *, full_page: bool = True, filename: str | None = None) -> dict[str, Any]:
        name = filename or f"shot-{len(self.screenshots) + 1}.png"
        self.screenshots.append(name)
        return {"path": str(Path("fake-browser") / name), "bytes": 1, "full_page": bool(full_page)}

    def close(self) -> None:
        return None
