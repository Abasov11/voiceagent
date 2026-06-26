"""Тесты GreenApiClient: проверка форматирования chat_id, URL-сборки и raise при отсутствии креденшелов.

Сетевые вызовы мокируются через httpx MockTransport.
"""

from __future__ import annotations

import json

import httpx
import pytest

from shared.green_api import GreenApiClient


@pytest.mark.asyncio
async def test_send_message_formats_chat_id_and_url():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"idMessage": "ABC123"})

    client = GreenApiClient(instance_id="YOUR_INSTANCE_ID", token="tok")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    res = await client.send_message(phone="+77000000000", text="Привет")
    assert res == {"idMessage": "ABC123"}
    assert captured["url"] == (
        "https://api.green-api.com/waInstanceYOUR_INSTANCE_ID/sendMessage/tok"
    )
    assert captured["body"]["chatId"] == "77000000000@c.us"
    assert captured["body"]["message"] == "Привет"
    await client.aclose()


@pytest.mark.asyncio
async def test_send_message_keeps_existing_chat_id_suffix():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["chatId"] == "77000000000@c.us"
        return httpx.Response(200, json={"idMessage": "X"})

    client = GreenApiClient(instance_id="ID", token="T")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await client.send_message(phone="77000000000@c.us", text="hi")
    await client.aclose()


@pytest.mark.asyncio
async def test_get_state_returns_json():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/getStateInstance/tok")
        return httpx.Response(200, json={"stateInstance": "authorized"})

    client = GreenApiClient(instance_id="ID", token="tok")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    res = await client.get_state()
    assert res["stateInstance"] == "authorized"
    await client.aclose()


@pytest.mark.asyncio
async def test_raises_without_credentials():
    client = GreenApiClient(instance_id=None, token=None)
    with pytest.raises(RuntimeError):
        await client.send_message(phone="+77001234567", text="x")
    with pytest.raises(RuntimeError):
        await client.get_state()
    await client.aclose()


@pytest.mark.asyncio
async def test_propagates_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "forbidden"})

    client = GreenApiClient(instance_id="ID", token="T")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await client.send_message(phone="+77001234567", text="x")
    await client.aclose()
