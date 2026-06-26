"""Тесты для shared.existing_clients и таблицы existing_clients."""
from __future__ import annotations

import pytest

from shared.existing_clients import is_existing_client, normalize_phone, split_phones
from shared.models import ExistingClient


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+7(705)550-11-44", "77055501144"),
        ("8 705 550 11 44", "77055501144"),
        ("77055501144", "77055501144"),
        ("  +7-705-550-11-44  ", "77055501144"),
        ("", None),
        (None, None),
        ("abc", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_split_phones_single():
    assert split_phones("+7(705)550-11-44") == ["77055501144"]


def test_split_phones_multiple():
    assert split_phones("+7(705)902-11-22, +7(705)550-11-44") == [
        "77059021122",
        "77055501144",
    ]


def test_split_phones_dedup():
    assert split_phones("+7-705-550-11-44, 87055501144") == ["77055501144"]


def test_split_phones_empty():
    assert split_phones("") == []
    assert split_phones(None) == []


def test_is_existing_client_hit(session):
    # Используем заведомо тестовый номер вне продакшен-базы.
    test_phone = "79990000001"
    session.query(ExistingClient).filter_by(phone=test_phone).delete()
    session.commit()
    session.add(
        ExistingClient(
            phone=test_phone,
            full_name="Тест Клиент",
            active_groups="Тестовая группа",
            source="test",
        )
    )
    session.commit()
    try:
        assert is_existing_client("+7(999)000-00-01", session) is True
        assert is_existing_client("89990000001", session) is True
        assert is_existing_client("79990000001", session) is True
    finally:
        session.query(ExistingClient).filter_by(phone=test_phone).delete()
        session.commit()


def test_is_existing_client_miss(session):
    assert is_existing_client("+7(900)000-00-99", session) is False


def test_is_existing_client_none(session):
    assert is_existing_client(None, session) is False
    assert is_existing_client("", session) is False
