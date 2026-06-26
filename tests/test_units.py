import pytest


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+7(777)970-11-99", "+77779701199"),
        ("8 705 550 11 44", "+77055501144"),
        ("77001234567", "+77001234567"),
        ("", None),
        (None, None),
    ],
)
def test_phone_normalize(raw, expected):
    from shared.alfacrm_sync import normalize_phone

    assert normalize_phone(raw) == expected


def test_csv_loader_phone_normalize():
    from zvonar.csv_loader import normalize_phone as cl_normalize

    assert cl_normalize("8 705 550 11 44") == "+77055501144"
    assert cl_normalize("+7(777)970-11-99") == "+77779701199"


def test_pick_tier():
    from shared.llm import pick_tier

    assert pick_tier(None) == "short"
    assert pick_tier(0) == "short"
    assert pick_tier(59) == "short"
    assert pick_tier(60) == "long"
    assert pick_tier(3600) == "long"


def test_make_session_cookie_roundtrip():
    from shared.auth import make_session_cookie, parse_session_cookie

    cookie = make_session_cookie(42)
    assert parse_session_cookie(cookie) == {"uid": 42}
    assert parse_session_cookie("garbage") is None
