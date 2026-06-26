"""Тесты push outcome → Альфа CRM (shared/alfacrm_push)."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from shared import alfacrm_push
from shared.alfacrm import AlfaCrmClient
from shared.models import CallOutcome, Lead, ZvonarCall
from shared.settings import get_settings


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    for k in (
        "ALFA_CRM_PUSH_OUTCOME", "ALFA_CRM_OUTCOME_STATUS_JSON",
        "ALFA_CRM_API_KEY", "ALFA_CRM_EMAIL",
    ):
        monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_zvonar_call(session, *, alfa_crm_id: str | None, outcome: str = "interested") -> int:
    lead = Lead(phone="+77001234567", name="Тест", alfa_crm_id=alfa_crm_id)
    session.add(lead)
    session.flush()
    z = ZvonarCall(
        lead_id=lead.id,
        voximplant_session_id="sess-1",
        started_at=datetime.now(timezone.utc),
        duration_s=42,
        outcome=outcome,
    )
    session.add(z)
    session.commit()
    return z.id


def _mock_alfa_client(monkeypatch, captured: dict, *, fail: bool = False) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2api/auth/login":
            return httpx.Response(200, json={"token": "tok"})
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode()
        if fail:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json={"id": 555})

    def factory():
        c = AlfaCrmClient(base_url="https://x.s20.online", api_key="K", email="e@x", branch_id=1)
        c._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=c.base_url
        )
        return c

    monkeypatch.setattr(alfacrm_push, "_make_alfacrm_client", factory)


async def test_skipped_when_disabled(session):
    cid = _make_zvonar_call(session, alfa_crm_id="123")
    res = await alfacrm_push.push_outcome(cid)
    assert res == {"skipped": "push_disabled"}


async def test_skipped_without_credentials(monkeypatch, session):
    monkeypatch.setenv("ALFA_CRM_PUSH_OUTCOME", "1")
    monkeypatch.delenv("ALFA_CRM_API_KEY", raising=False)
    get_settings.cache_clear()
    cid = _make_zvonar_call(session, alfa_crm_id="123")
    res = await alfacrm_push.push_outcome(cid)
    assert res == {"skipped": "no_credentials"}


async def test_skipped_without_alfa_crm_id(monkeypatch, session):
    monkeypatch.setenv("ALFA_CRM_PUSH_OUTCOME", "1")
    monkeypatch.setenv("ALFA_CRM_API_KEY", "K")
    get_settings.cache_clear()
    cid = _make_zvonar_call(session, alfa_crm_id=None)
    res = await alfacrm_push.push_outcome(cid)
    assert res["skipped"] == "lead_has_no_alfa_crm_id"


async def test_pushes_with_status_map(monkeypatch, session):
    monkeypatch.setenv("ALFA_CRM_PUSH_OUTCOME", "1")
    monkeypatch.setenv("ALFA_CRM_API_KEY", "K")
    monkeypatch.setenv(
        "ALFA_CRM_OUTCOME_STATUS_JSON",
        '{"interested":12,"callback":7,"not_interested":15,"no_answer":3}',
    )
    get_settings.cache_clear()
    cid = _make_zvonar_call(session, alfa_crm_id="555", outcome=CallOutcome.interested.value)
    captured: dict = {}
    _mock_alfa_client(monkeypatch, captured)

    res = await alfacrm_push.push_outcome(cid)
    assert res.get("ok") is True, f"unexpected res: {res}"
    assert res["status_id"] == 12
    assert "id=555" in captured["url"]
    assert "lead_status_id" in captured["body"]
    assert "12" in captured["body"]
    # body — JSON со escape-юникодом из httpx; проверяем ASCII-фрагмент
    assert "outcome=interested" in captured["body"]


async def test_pushes_without_status_map(monkeypatch, session):
    monkeypatch.setenv("ALFA_CRM_PUSH_OUTCOME", "1")
    monkeypatch.setenv("ALFA_CRM_API_KEY", "K")
    get_settings.cache_clear()
    cid = _make_zvonar_call(session, alfa_crm_id="555", outcome="callback")
    captured: dict = {}
    _mock_alfa_client(monkeypatch, captured)

    res = await alfacrm_push.push_outcome(cid)
    assert res["ok"] is True
    assert res["status_id"] is None
    assert "lead_status_id" not in captured["body"]
    assert "outcome=callback" in captured["body"]


async def test_graceful_on_http_error(monkeypatch, session):
    monkeypatch.setenv("ALFA_CRM_PUSH_OUTCOME", "1")
    monkeypatch.setenv("ALFA_CRM_API_KEY", "K")
    get_settings.cache_clear()
    cid = _make_zvonar_call(session, alfa_crm_id="555")
    captured: dict = {}
    _mock_alfa_client(monkeypatch, captured, fail=True)

    res = await alfacrm_push.push_outcome(cid)
    assert "error" in res
    assert res["alfa_crm_id"] == "555"


def test_invalid_status_json_treated_as_empty(monkeypatch):
    monkeypatch.setenv("ALFA_CRM_OUTCOME_STATUS_JSON", "not-json")
    get_settings.cache_clear()
    assert alfacrm_push._outcome_status_map() == {}


def test_status_map_parses_string_int(monkeypatch):
    monkeypatch.setenv(
        "ALFA_CRM_OUTCOME_STATUS_JSON",
        '{"interested":12,"callback":"7","not_interested":15}',
    )
    get_settings.cache_clear()
    m = alfacrm_push._outcome_status_map()
    assert m == {"interested": 12, "callback": 7, "not_interested": 15}
