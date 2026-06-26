"""Тесты rule-based классификации заинтересованности (shared/qualification.py)."""

from __future__ import annotations

import pathlib

import pytest

from shared.models import CallOutcome
from shared.qualification import classify

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_interested_training_signals():
    text = "А где у вас ближайший филиал? Когда тренировки и сколько стоит пробная?"
    r = classify(text)
    assert r.outcome == CallOutcome.interested.value
    assert any("training_interest:" in s for s in r.reasons)


def test_interested_camp_signals():
    text = _read("dialog_camp_interested.txt")
    r = classify(text)
    assert r.outcome == CallOutcome.interested.value
    assert any("camp_interest:" in s for s in r.reasons)


def test_explicit_refusal():
    text = _read("dialog_rude.txt")
    r = classify(text)
    assert r.outcome == CallOutcome.not_interested.value
    assert any("not_interested:" in s for s in r.reasons)


def test_callback_in_car():
    text = _read("dialog_callback.txt")
    r = classify(text)
    assert r.outcome == CallOutcome.callback.value
    assert any("callback:" in s for s in r.reasons)


def test_silence_defaults_to_not_interested():
    text = _read("dialog_silence.txt")
    r = classify(text)
    assert r.outcome == CallOutcome.not_interested.value
    assert r.reasons == ("default:no_signal",)


def test_loop_bait_defaults_without_signals():
    """Зацикленные вопросы без ключевых слов = нет сигнала интереса."""
    text = _read("dialog_loop_bait.txt")
    r = classify(text)
    assert r.outcome == CallOutcome.not_interested.value


def test_existing_interested_fixture():
    text = _read("dialog_interested.txt")
    r = classify(text)
    # "пробную" или "пробная" — сигнал интереса к тренировкам
    assert r.outcome in (CallOutcome.interested.value, CallOutcome.callback.value)


@pytest.mark.parametrize("phrase,expected", [
    ("Не звоните мне больше", CallOutcome.not_interested.value),
    ("Перезвоните завтра", CallOutcome.callback.value),
    ("А расписание тренировок какое?", CallOutcome.interested.value),
    ("Где локация ближайшего филиала", CallOutcome.interested.value),
    ("Спасибо, до свидания", CallOutcome.not_interested.value),  # default
])
def test_classify_phrases(phrase: str, expected: str):
    assert classify(phrase).outcome == expected
