"""Клиент Альфа CRM (s20.online) REST API v2.

Документация: https://alfacrm.pro/api/

Поток авторизации:
1) POST /v2api/auth/login {email, api_key} → {token, expires_at}
2) Дальше во всех запросах заголовок X-ALFACRM-TOKEN.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


class AlfaCrmAuthError(RuntimeError):
    pass


class AlfaCrmClient:
    """Тонкая обёртка над Альфа CRM v2.

    Текущий минимальный набор операций для интеграции звонаря:
      - login()
      - find_customer_by_phone(phone)
      - create_or_update_customer(...)
      - add_lead_note(customer_id, note)

    Расширяется по мере наполнения сценариев.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        email: str | None = None,
        branch_id: int = 1,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.email = email
        self.branch_id = branch_id
        self._client = httpx.AsyncClient(timeout=timeout, base_url=self.base_url)
        self._token: str | None = None
        self._token_expires: datetime | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def login(self) -> str:
        if not self.api_key:
            raise AlfaCrmAuthError("ALFA_CRM_API_KEY is not set")
        # Альфа CRM v2 использует {email, api_key} либо {api_key} в зависимости от инстанса.
        payload: dict[str, Any] = {"api_key": self.api_key}
        if self.email:
            payload["email"] = self.email
        r = await self._client.post("/v2api/auth/login", json=payload)
        r.raise_for_status()
        data = r.json()
        token = data.get("token") or data.get("access_token")
        if not token:
            raise AlfaCrmAuthError(f"login response missing token: {data}")
        self._token = token
        # консервативно: токен живёт ~10 мин — рефрешим заранее
        self._token_expires = datetime.utcnow() + timedelta(minutes=8)
        log.info("alfa-crm: logged in, token cached")
        return token

    async def _ensure_token(self) -> str:
        if (
            self._token
            and self._token_expires
            and datetime.utcnow() < self._token_expires
        ):
            return self._token
        return await self.login()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        token = await self._ensure_token()
        headers = kwargs.pop("headers", {}) or {}
        headers["X-ALFACRM-TOKEN"] = token
        r = await self._client.request(method, path, headers=headers, **kwargs)
        if r.status_code == 401:
            # одноразовый ретрай с релогином
            self._token = None
            token = await self._ensure_token()
            headers["X-ALFACRM-TOKEN"] = token
            r = await self._client.request(method, path, headers=headers, **kwargs)
        r.raise_for_status()
        return r.json() if r.content else {}

    async def find_customer_by_phone(self, phone: str) -> list[dict[str, Any]]:
        # /v2api/{branch}/customer/index
        body = {"phone": phone, "page": 0}
        return (
            await self._request(
                "POST", f"/v2api/{self.branch_id}/customer/index", json=body
            )
        ).get("items", [])

    async def list_customers_page(
        self, *, page: int = 0, is_study: int | None = None, page_size: int = 50
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"page": page, "page_size": page_size}
        if is_study is not None:
            body["is_study"] = is_study
        return await self._request(
            "POST", f"/v2api/{self.branch_id}/customer/index", json=body
        )

    async def iter_all_customers(
        self, *, page_size: int = 50, max_pages: int = 1000
    ) -> Any:
        """Async-итератор по всем клиентам (без фильтра по статусу).

        Альфа CRM v2 в большинстве инстансов фиксирует страницу в 50 записей,
        даже если запросить больше; ориентируемся только на «есть items / нет».
        """
        for page in range(max_pages):
            data = await self.list_customers_page(page=page, page_size=page_size)
            items = data.get("items") or []
            if not items:
                return
            for it in items:
                yield it

    async def create_or_update_customer(
        self,
        *,
        name: str,
        phone: str,
        legal_type: int = 1,
        is_study: int = 0,
        note: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = await self.find_customer_by_phone(phone)
        if existing:
            cust = existing[0]
            cust_id = cust["id"]
            payload: dict[str, Any] = {"name": name, "phone": [phone]}
            if note:
                payload["note"] = note
            if extra:
                payload.update(extra)
            return await self._request(
                "POST", f"/v2api/{self.branch_id}/customer/update?id={cust_id}", json=payload
            )
        payload = {
            "name": name,
            "phone": [phone],
            "legal_type": legal_type,
            "is_study": is_study,
        }
        if note:
            payload["note"] = note
        if extra:
            payload.update(extra)
        return await self._request(
            "POST", f"/v2api/{self.branch_id}/customer/create", json=payload
        )

    async def ping(self) -> bool:
        """Smoke-тест: логин не падает."""
        try:
            await self.login()
            return True
        except Exception as exc:
            log.warning("alfa-crm ping failed: %s", exc)
            return False
