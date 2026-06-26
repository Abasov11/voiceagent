"""Voximplant Management API клиент.

Документация: https://voximplant.com/docs/references/httpapi
Используется server-side для:
  - запуска исходящих сценариев (CallList API)
  - управления номерами и приложениями

NB: помимо Management API есть VoxEngine — JS-сценарии, которые крутятся внутри
Voximplant и обращаются к нашему бэкенду по HTTPS на каждом шаге диалога.
JS-сценарий лежит в zvonar/voxengine_scenario.js (создаётся и заливается в платформу
один раз через UI или API после регистрации аккаунта).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class VoximplantClient:
    """Минимальная обёртка над Management API."""

    BASE_URL = "https://api.voximplant.com/platform_api"

    def __init__(
        self,
        account_id: str | None,
        api_key: str | None,
        application_id: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.account_id = account_id
        self.api_key = api_key
        self.application_id = application_id
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _params(self, extra: dict[str, Any]) -> dict[str, Any]:
        if not self.account_id or not self.api_key:
            raise RuntimeError("Voximplant credentials are not configured")
        params = {
            "account_id": self.account_id,
            "api_key": self.api_key,
        }
        params.update(extra)
        return params

    async def get_account_info(self) -> dict[str, Any]:
        r = await self._client.get(
            f"{self.BASE_URL}/GetAccountInfo/", params=self._params({})
        )
        r.raise_for_status()
        return r.json()

    async def start_outbound_call(
        self, *, rule_id: int, phone: str, custom_data: str | None = None
    ) -> dict[str, Any]:
        params = self._params({"rule_id": rule_id, "script_custom_data": custom_data or ""})
        params["script_custom_data"] = (custom_data or "")[:200]
        r = await self._client.post(
            f"{self.BASE_URL}/StartScenarios/",
            data=params,
        )
        r.raise_for_status()
        return r.json()
