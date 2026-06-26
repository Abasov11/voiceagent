"""SIP-провайдер: SIP-оператор Казахстан, динамическая регистрация.

Источник конфигурации — письмо от SIP-оператор от 2026-04-30 (sip-provider@example.com).

Хосты регистрации:
  almpbx.example.com — Алматы (предпочтительный, по локации клиента)
  astpbx.example.com — Астана

Разрешённые публичные SIP-адреса оператора (источник входящего трафика):
  198.51.100.10, 198.51.100.11, 198.51.100.12, 198.51.100.13,
  198.51.100.14, 198.51.100.15, 198.51.100.16, 198.51.100.17

RTP-медиа порты: 10002–59999
Формат набора: international11 (+7XXXXXXXXXX)
Минимальная expires регистрации: 120 секунд

ВАЖНО: наш публичный SIP-адрес (или адрес Voximplant trunk-а) должен быть
передан менеджеру SIP-оператор для добавления в их whitelist — иначе INVITE будут
отбрасываться.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SipAccount:
    """Один SIP-аккаунт (логин/пароль) и привязанный к нему номер."""

    login: str
    password: str
    phone: str | None = None  # E.164 (+7...). None если логин не равен номеру.


SIP_PROVIDER_HOSTS = {
    "almaty": "almpbx.example.com",
    "astana": "astpbx.example.com",
}

SIP_PROVIDER_ALLOWED_SOURCE_IPS = (
    "198.51.100.10",
    "198.51.100.11",
    "198.51.100.12",
    "198.51.100.13",
    "198.51.100.14",
    "198.51.100.15",
    "198.51.100.16",
    "198.51.100.17",
)

SIP_PROVIDER_RTP_PORT_RANGE = (10002, 59999)
SIP_PROVIDER_MIN_REGISTER_EXPIRES_S = 120
SIP_PROVIDER_NUMBER_FORMAT = "international11"  # +7XXXXXXXXXX


def _parse_accounts_env(raw: str | None) -> list[SipAccount]:
    """SIP_ACCOUNTS_JSON='[{"login":"...","password":"...","phone":"+7..."}]'."""
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out: list[SipAccount] = []
    for it in items:
        if "login" in it and "password" in it:
            out.append(
                SipAccount(
                    login=str(it["login"]),
                    password=str(it["password"]),
                    phone=it.get("phone"),
                )
            )
    return out


def load_sip_accounts() -> list[SipAccount]:
    """Возвращает список SIP-аккаунтов, либо пустой список если SIP не настроен."""
    return _parse_accounts_env(os.environ.get("SIP_ACCOUNTS_JSON"))


def primary_sip_host() -> str:
    region = os.environ.get("SIP_REGION", "almaty").lower()
    return SIP_PROVIDER_HOSTS.get(region, SIP_PROVIDER_HOSTS["almaty"])


def is_sip_configured() -> bool:
    return bool(load_sip_accounts())
