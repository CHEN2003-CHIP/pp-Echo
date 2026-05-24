from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from pp_agent.browser.controller import LocalCDPBrowserController
from pp_agent.browser.models import BrowserProfile


class ManagedBrowserController(LocalCDPBrowserController):
    def __init__(
        self,
        *,
        workspace: Path,
        browser_executable: str = "",
        user_data_dir: str = "",
        screenshot_dir: str = "",
        launch_flags: list[str] | None = None,
        profile_mode: str = "isolated",
        remote_cdp_url: str = "",
        connect_timeout_seconds: int = 20,
        navigation_timeout_ms: int = 5000,
        cdp_http_timeout_seconds: int = 3,
        cdp_response_timeout_seconds: int | None = None,
        action_timeout_ms: int = 1500,
        shutdown_timeout_seconds: int = 5,
    ) -> None:
        super().__init__(
            workspace=workspace,
            browser_executable=browser_executable,
            user_data_dir=user_data_dir,
            screenshot_dir=screenshot_dir,
            launch_flags=launch_flags,
            connect_timeout_seconds=connect_timeout_seconds,
            navigation_timeout_ms=navigation_timeout_ms,
            cdp_http_timeout_seconds=cdp_http_timeout_seconds,
            cdp_response_timeout_seconds=cdp_response_timeout_seconds,
            action_timeout_ms=action_timeout_ms,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
        )
        self.profile_mode = (profile_mode or "isolated").strip().lower() or "isolated"
        self.remote_cdp_url = remote_cdp_url.strip()
        self._remote_attached = False

    def doctor(self) -> dict[str, Any]:
        status = super().doctor()
        status["profile_mode"] = self.profile_mode
        status["remote_cdp_url"] = self.remote_cdp_url
        status["remote_attached"] = self._remote_attached
        return status

    def profiles(self) -> list[BrowserProfile]:
        profiles = super().profiles()
        for profile in profiles:
            if profile.name == "remote":
                profile.cdp_url = self.remote_cdp_url
                profile.enabled = bool(self.remote_cdp_url)
                profile.explicitly_enabled = bool(self.remote_cdp_url)
        return profiles

    def close(self) -> None:
        if self.remote_cdp_url:
            for client in list(self._clients.values()):
                try:
                    client.close()
                except Exception:
                    pass
            self._clients = {}
            self._page_ws_url = None
            self._browser_ws_url = None
            self._devtools_port = None
            self._remote_attached = False
            return
        super().close()

    def _start_browser_if_needed(self) -> None:
        if self.remote_cdp_url:
            self._start_remote_browser_if_needed()
            return
        super()._start_browser_if_needed()

    def _start_remote_browser_if_needed(self) -> None:
        if self._remote_attached and self._page_ws_url is not None:
            return
        version_url = self.remote_cdp_url
        if version_url.startswith("http://") or version_url.startswith("https://"):
            if not version_url.endswith("/json/version"):
                version_url = version_url.rstrip("/") + "/json/version"
            base_url = version_url[: -len("/json/version")]
        else:
            raise RuntimeError("Remote CDP URL must be an http(s) endpoint ending in /json/version or a base URL.")
        with httpx.Client(timeout=self.cdp_http_timeout_seconds) as client:
            version_payload = client.get(version_url).json()
        browser_ws = str(version_payload.get("webSocketDebuggerUrl") or "")
        if not browser_ws:
            raise RuntimeError("Remote CDP endpoint did not expose a browser websocket URL.")
        self._browser_ws_url = browser_ws
        self._devtools_port = None
        self._page_ws_url = self._discover_remote_page_ws_url(base_url, browser_ws)
        self._remote_attached = True

    def _discover_remote_page_ws_url(self, base_url: str, browser_ws: str) -> str:
        list_url = base_url.rstrip("/") + "/json/list"
        last_error = ""
        deadline = time.time() + self.connect_timeout_seconds
        while time.time() < deadline:
            try:
                with httpx.Client(timeout=self.cdp_http_timeout_seconds) as client:
                    page_targets = client.get(list_url).json()
                for target in page_targets:
                    if target.get("type") in {"page", "tab"} and target.get("webSocketDebuggerUrl") and target.get("url") != "chrome://newtab/":
                        return str(target["webSocketDebuggerUrl"])
            except Exception as exc:
                last_error = str(exc)
            try:
                browser_client = self._connect_browser_client(browser_ws)
                try:
                    payload = self._call(browser_client, "Target.createTarget", {"url": "about:blank"})
                    created_target_id = str(payload.get("result", {}).get("targetId") or "")
                    if created_target_id:
                        with httpx.Client(timeout=self.cdp_http_timeout_seconds) as client:
                            page_targets = client.get(list_url).json()
                        for target in page_targets:
                            if target.get("id") == created_target_id and target.get("webSocketDebuggerUrl"):
                                return str(target["webSocketDebuggerUrl"])
                finally:
                    browser_client.close()
            except Exception as exc:
                last_error = str(exc)
            time.sleep(0.2)
        raise RuntimeError(
            f"Timed out waiting for remote browser page target after {self.connect_timeout_seconds}s. Last error: {last_error}"
        )
