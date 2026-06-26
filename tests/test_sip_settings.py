"""Тесты shared/sip_settings: парсинг SIP_ACCOUNTS_JSON, выбор региона."""

from __future__ import annotations

import os

import pytest

from shared import sip_settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("SIP_ACCOUNTS_JSON", "SIP_REGION"):
        monkeypatch.delenv(k, raising=False)
    yield


def test_no_accounts_when_unset():
    assert sip_settings.load_sip_accounts() == []
    assert sip_settings.is_sip_configured() is False


def test_parse_three_sip_provider_accounts(monkeypatch):
    monkeypatch.setenv(
        "SIP_ACCOUNTS_JSON",
        '[{"login":"sip_login_1","password":"sip_password"},'
        ' {"login":"7077305020","password":"sip_pass_2","phone":"+77000000001"},'
        ' {"login":"7470939142","password":"sip_pass_3","phone":"+77000000002"}]',
    )
    accs = sip_settings.load_sip_accounts()
    assert len(accs) == 3
    assert accs[0].login == "sip_login_1"
    assert accs[1].phone == "+77000000001"
    assert sip_settings.is_sip_configured() is True


def test_invalid_json_returns_empty(monkeypatch):
    monkeypatch.setenv("SIP_ACCOUNTS_JSON", "this is not json")
    assert sip_settings.load_sip_accounts() == []


def test_missing_fields_skipped(monkeypatch):
    monkeypatch.setenv(
        "SIP_ACCOUNTS_JSON", '[{"login":"x"}, {"login":"y","password":"z"}]'
    )
    accs = sip_settings.load_sip_accounts()
    assert len(accs) == 1
    assert accs[0].login == "y"


def test_primary_host_defaults_almaty():
    assert sip_settings.primary_sip_host() == "almpbx.example.com"


def test_primary_host_astana(monkeypatch):
    monkeypatch.setenv("SIP_REGION", "astana")
    assert sip_settings.primary_sip_host() == "astpbx.example.com"


def test_primary_host_unknown_falls_back(monkeypatch):
    monkeypatch.setenv("SIP_REGION", "shymkent")
    assert sip_settings.primary_sip_host() == "almpbx.example.com"


def test_sip_provider_constants_match_letter():
    # IP-список из письма SIP-оператор (photo_25 от 2026-04-30) должен быть полным.
    assert "198.51.100.10" in sip_settings.SIP_PROVIDER_ALLOWED_SOURCE_IPS
    assert "198.51.100.17" in sip_settings.SIP_PROVIDER_ALLOWED_SOURCE_IPS
    assert len(sip_settings.SIP_PROVIDER_ALLOWED_SOURCE_IPS) == 8
    assert sip_settings.SIP_PROVIDER_RTP_PORT_RANGE == (10002, 59999)
    assert sip_settings.SIP_PROVIDER_MIN_REGISTER_EXPIRES_S == 120
