"""Тесты AlfaCrmClient: login flow, кеширование токена, релогин при 401, find_customer_by_phone."""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest

from shared.alfacrm import AlfaCrmAuthError, AlfaCrmClient


def _client_with_handler(handler):
    c = AlfaCrmClient(base_url="https://x.s20.online", api_key="K", email="e@x", branch_id=1)
    c._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=c.base_url
    )
    return c


async def test_login_returns_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2api/auth/login"
        return httpx.Response(200, json={"token": "tok-1"})

    c = _client_with_handler(handler)
    tok = await c.login()
    assert tok == "tok-1"
    assert c._token == "tok-1"
    await c.aclose()


async def test_login_fails_without_api_key():
    c = AlfaCrmClient(base_url="https://x", api_key=None, email="e", branch_id=1)
    with pytest.raises(AlfaCrmAuthError):
        await c.login()
    await c.aclose()


async def test_login_fails_when_token_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})  # нет token

    c = _client_with_handler(handler)
    with pytest.raises(AlfaCrmAuthError):
        await c.login()
    await c.aclose()


async def test_token_is_cached_until_expiry():
    calls = {"login": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2api/auth/login":
            calls["login"] += 1
            return httpx.Response(200, json={"token": "tok"})
        return httpx.Response(200, json={"items": []})

    c = _client_with_handler(handler)
    await c.find_customer_by_phone("+77001234567")
    await c.find_customer_by_phone("+77007654321")
    assert calls["login"] == 1  # второй вызов берёт кешированный токен
    await c.aclose()


async def test_relogin_on_401():
    state = {"login_calls": 0, "first_request": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2api/auth/login":
            state["login_calls"] += 1
            return httpx.Response(200, json={"token": f"tok-{state['login_calls']}"})
        if state["first_request"]:
            state["first_request"] = False
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={"items": [{"id": 42}]})

    c = _client_with_handler(handler)
    items = await c.find_customer_by_phone("+77001234567")
    assert items == [{"id": 42}]
    assert state["login_calls"] == 2  # первый + один retry
    await c.aclose()


async def test_find_customer_uses_post_with_phone():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2api/auth/login":
            return httpx.Response(200, json={"token": "tok"})
        captured["path"] = request.url.path
        captured["method"] = request.method
        return httpx.Response(200, json={"items": [{"id": 1, "name": "Иван"}]})

    c = _client_with_handler(handler)
    res = await c.find_customer_by_phone("+77001234567")
    assert res == [{"id": 1, "name": "Иван"}]
    assert captured["method"] == "POST"
    assert captured["path"] == "/v2api/1/customer/index"
    await c.aclose()


async def test_ping_returns_true_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token": "tok"})

    c = _client_with_handler(handler)
    assert await c.ping() is True
    await c.aclose()


async def test_ping_returns_false_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    c = AlfaCrmClient(base_url="https://x.s20.online", api_key="K", email="e", branch_id=1)
    c._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=c.base_url
    )
    # tenacity retry stop_after_attempt(3) — но всё равно False
    assert await c.ping() is False
    await c.aclose()
