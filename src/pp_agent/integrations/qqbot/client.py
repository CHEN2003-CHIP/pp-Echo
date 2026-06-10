from __future__ import annotations

import time
from typing import Any

import httpx

from pp_agent.integrations.qqbot.config import QQBotConfig
from pp_agent.integrations.qqbot.errors import QQBotAPIError


class QQBotClient:
    def __init__(self, config: QQBotConfig, *, http_client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._http_client = http_client
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self.config.request_timeout)
            close_client = True
        try:
            response = await client.post(
                self.config.token_url,
                json={"appId": self.config.app_id, "clientSecret": self.config.app_secret},
            )
            if response.status_code >= 400:
                raise QQBotAPIError(f"QQ access token request failed with HTTP {response.status_code}.")
            payload = response.json()
            token = str(payload.get("access_token") or "")
            if not token:
                raise QQBotAPIError("QQ access token response did not include access_token.")
            self._token = token
            self._token_expires_at = time.time() + int(payload.get("expires_in") or 7200)
            return token
        finally:
            if close_client:
                await client.aclose()

    async def send_c2c_text(self, openid: str, content: str, *, msg_id: str | None = None, event_id: str | None = None, msg_seq: int = 1) -> dict:
        return await self._post_message(f"/v2/users/{openid}/messages", content, msg_id=msg_id, event_id=event_id, msg_seq=msg_seq)

    async def send_group_text(self, group_openid: str, content: str, *, msg_id: str | None = None, event_id: str | None = None, msg_seq: int = 1) -> dict:
        return await self._post_message(f"/v2/groups/{group_openid}/messages", content, msg_id=msg_id, event_id=event_id, msg_seq=msg_seq)

    async def _post_message(self, path: str, content: str, *, msg_id: str | None, event_id: str | None, msg_seq: int) -> dict[str, Any]:
        token = await self.access_token()
        body: dict[str, Any] = {"content": content, "msg_type": 0, "msg_seq": msg_seq}
        if msg_id:
            body["msg_id"] = msg_id
        if event_id:
            body["event_id"] = event_id
        close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self.config.request_timeout)
            close_client = True
        try:
            response = await client.post(
                f"{self.config.api_base}{path}",
                headers={"Authorization": f"QQBot {token}"},
                json=body,
            )
            if response.status_code >= 400:
                raise QQBotAPIError(f"QQ send message failed with HTTP {response.status_code}.")
            return response.json() if response.content else {}
        finally:
            if close_client:
                await client.aclose()

