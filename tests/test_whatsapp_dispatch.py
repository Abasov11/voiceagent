"""Тесты на отправку WhatsApp заинтересованным .

Hook `zvonar.router.send_interested_whatsapp` вызывается background-таском
после `/zvonar/dialogue/finish` с outcome=interested. Тут проверяем три
ветки: нет креденшелов → skipped, сетевой успех → ok, исключение → error.
"""
from __future__ import annotations

import json

import httpx
import pytest

from shared import green_api as ga_mod
from shared.models import ApiCallLog, Lead
from shared.settings import get_settings
import zvonar.router as zr


def _make_lead(session, phone: str = "+77001112233", name: str | None = "Тест"):
    lead = Lead(phone=phone, name=name)
    session.add(lead)
    session.commit()
    session.refresh(lead)
    return lead


@pytest.mark.asyncio
async def test_skips_when_no_green_api_creds(monkeypatch, session):
    lead = _make_lead(session)
    monkeypatch.setenv("GREEN_API_INSTANCE_ID", "")
    monkeypatch.setenv("GREEN_API_TOKEN", "")
    get_settings.cache_clear()

    await zr.send_interested_whatsapp(lead.id)

    log = (
        session.query(ApiCallLog)
        .filter_by(provider="greenapi", operation="send_message")
        .one()
    )
    assert log.status == "skipped"
    assert (log.request or {}).get("lead_id") == lead.id


@pytest.mark.asyncio
async def test_sends_via_green_api_and_logs_ok(monkeypatch, session):
    lead = _make_lead(session, phone="+77000000000", name="Айгерим")
    monkeypatch.setenv("GREEN_API_INSTANCE_ID", "ID")
    monkeypatch.setenv("GREEN_API_TOKEN", "TOK")
    get_settings.cache_clear()

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"idMessage": "MSG-1"})

    orig_init = ga_mod.GreenApiClient.__init__

    def patched_init(self, instance_id, token, timeout: float = 20.0):
        orig_init(self, instance_id, token, timeout)
        self._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ga_mod.GreenApiClient, "__init__", patched_init)

    await zr.send_interested_whatsapp(lead.id)

    assert captured["body"]["chatId"] == "77000000000@c.us"
    assert "Айгерим" in captured["body"]["message"]

    log = (
        session.query(ApiCallLog)
        .filter_by(provider="greenapi", status="ok")
        .one()
    )
    assert (log.response or {}).get("idMessage") == "MSG-1"
    assert (log.request or {}).get("phone_tail") == "9388"


@pytest.mark.asyncio
async def test_logs_error_on_green_api_failure(monkeypatch, session):
    lead = _make_lead(session)
    monkeypatch.setenv("GREEN_API_INSTANCE_ID", "ID")
    monkeypatch.setenv("GREEN_API_TOKEN", "TOK")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    orig_init = ga_mod.GreenApiClient.__init__

    def patched_init(self, instance_id, token, timeout: float = 20.0):
        orig_init(self, instance_id, token, timeout)
        self._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ga_mod.GreenApiClient, "__init__", patched_init)

    await zr.send_interested_whatsapp(lead.id)

    log = (
        session.query(ApiCallLog)
        .filter_by(provider="greenapi", status="error")
        .one()
    )
    assert log.error and "503" in log.error
