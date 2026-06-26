"""Green API (WhatsApp) клиент — отправка сообщений заинтересованным клиентам."""
from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class GreenApiClient:
    def __init__(
        self,
        instance_id: str | None,
        token: str | None,
        timeout: float = 20.0,
    ) -> None:
        self.instance_id = instance_id
        self.token = token
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _base(self) -> str:
        return f"https://api.green-api.com/waInstance{self.instance_id}"

    async def send_message(self, *, phone: str, text: str) -> dict[str, Any]:
        if not self.instance_id or not self.token:
            raise RuntimeError("Green API credentials are not configured")
        # phone должен быть в формате 7700XXXXXXX@c.us
        chat_id = phone.lstrip("+")
        if not chat_id.endswith("@c.us"):
            chat_id = f"{chat_id}@c.us"
        url = f"{self._base()}/sendMessage/{self.token}"
        r = await self._client.post(url, json={"chatId": chat_id, "message": text})
        r.raise_for_status()
        return r.json()

    async def get_state(self) -> dict[str, Any]:
        if not self.instance_id or not self.token:
            raise RuntimeError("Green API credentials are not configured")
        r = await self._client.get(f"{self._base()}/getStateInstance/{self.token}")
        r.raise_for_status()
        return r.json()
