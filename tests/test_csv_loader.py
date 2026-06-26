"""Edge-cases для zvonar.csv_loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from shared.alfacrm_sync import normalize_phone as alfa_norm
from shared.db import db_session
from shared.models import Lead
from zvonar.csv_loader import load_csv, normalize_phone


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("8 705 550 11 44", "+77055501144"),
        ("+7(777)970-11-99", "+77779701199"),
        ("77001234567", "+77001234567"),
        ("+77001234567", "+77001234567"),
        ("+7-707-111-22-33", "+77071112233"),
        ("  +7 701 999 88 77  ", "+77019998877"),
    ],
)
def test_csv_normalize_variants(raw, expected):
    assert normalize_phone(raw) == expected


def test_alfa_normalize_handles_none_and_empty():
    assert alfa_norm(None) is None
    assert alfa_norm("") is None
    assert alfa_norm("---") is None


def test_alfa_normalize_keeps_already_canonical():
    assert alfa_norm("+77019998877") == "+77019998877"


def test_load_csv_inserts_dedup_and_normalizes():
    fixture = Path(__file__).parent / "fixtures" / "leads_sample.csv"
    n = load_csv(fixture)
    # 8 строк в CSV; 1 без телефона; 1 дубликат (одинаковый normalized phone)
    assert n == 6, f"expected 6 inserted, got {n}"

    with db_session() as db:
        rows = db.query(Lead).all()
        phones = sorted(r.phone for r in rows)
        # Все нормализованы в +7…
        assert all(p.startswith("+7") for p in phones), phones
        # Уникальны
        assert len(set(phones)) == len(phones)
        # Сегмент `SPECIAL` нижним регистром
        d = next((r for r in rows if r.name == "Дмитрий"), None)
        assert d is not None
        assert d.segment == "special"
