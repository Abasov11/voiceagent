"""Тесты VoximplantClient: проверка params-сборки, raise без credentials и custom_data truncation."""

from __future__ import annotations

import httpx
import pytest

from shared.voximplant import VoximplantClient


@pytest.mark.asyncio
async def test_get_account_info_passes_credentials():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"result": True, "account_info": {"balance": 0}})

    client = VoximplantClient(account_id="acct", api_key="key")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    info = await client.get_account_info()
    assert info["result"] is True
    assert captured["params"]["account_id"] == "acct"
    assert captured["params"]["api_key"] == "key"
    await client.aclose()


@pytest.mark.asyncio
async def test_start_outbound_call_truncates_custom_data():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"call_session_history_id": 1})

    client = VoximplantClient(account_id="A", api_key="K", application_id=1)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    long_data = "x" * 500
    await client.start_outbound_call(rule_id=42, phone="+77001234567", custom_data=long_data)
    # custom_data должно быть обрезано до 200 символов
    assert "x" * 200 in captured["body"]
    assert "x" * 201 not in captured["body"]
    await client.aclose()


@pytest.mark.asyncio
async def test_raises_without_credentials():
    client = VoximplantClient(account_id=None, api_key=None)
    with pytest.raises(RuntimeError):
        await client.get_account_info()
    await client.aclose()


@pytest.mark.asyncio
async def test_start_outbound_call_propagates_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "auth failed"})

    client = VoximplantClient(account_id="A", api_key="K")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await client.start_outbound_call(rule_id=1, phone="+77001234567")
    await client.aclose()
