"""Хелпер для работы с базой уже-клиентов школы.

Используется звонарём ДО постановки лида в очередь обзвона: если телефон
совпадает с записью в `existing_clients`, родитель уже в школе и звонить
не нужно (анти-спам + защита репутации бренда).

Нормализация телефона:
  +7(705)550-11-44      → 77055501144
  8 705 550 11 44       → 77055501144
  77055501144           → 77055501144
  +1-555-1234           → 15551234   (мало цифр — оставим как есть, помечаем dirty)

Длина после очистки 11 цифр и первая «8» → подменяем на «7» (КЗ/РФ).
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.models import ExistingClient


_DIGITS_RE = re.compile(r"\D+")


def normalize_phone(raw: str | None) -> str | None:
    """Возвращает только цифры; ведущая «8» из 11-значного → «7». None если пусто."""
    if not raw:
        return None
    digits = _DIGITS_RE.sub("", raw)
    if not digits:
        return None
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def split_phones(raw: str | None) -> list[str]:
    """Разделяет ячейку «+7(705)902-11-22, +7(705)550-11-44» на нормализованные номера."""
    if not raw:
        return []
    parts = re.split(r"[,;/\n]+", str(raw))
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        norm = normalize_phone(p)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def is_existing_client(phone: str | None, db: Session) -> bool:
    """True если телефон есть в базе уже-клиентов."""
    norm = normalize_phone(phone)
    if not norm:
        return False
    stmt = select(ExistingClient.id).where(ExistingClient.phone == norm).limit(1)
    return db.execute(stmt).first() is not None
