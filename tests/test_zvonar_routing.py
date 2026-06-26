"""Регрессия эвристик zvonar/router.py — outcome и stage transition.

Защищает от регресса регресс «перезвоните callback» (2026-05-11): фраза
«перезвоните позже» обозначает callback, не отказ, и не должна валить
сессию в goodbye.
"""
from __future__ import annotations

import pytest

from shared.models import CallOutcome
from zvonar.router import _next_stage, _outcome_for_stage


@pytest.mark.parametrize(
    "text",
    [
        "Перезвоните позже",
        "перезвоните мне завтра",
        "Я за рулем, перезвонит позже жена",
        "позже наберите",
    ],
)
def test_callback_phrases_yield_callback_outcome(text: str):
    outcome = _outcome_for_stage("qualify", text)
    assert outcome == CallOutcome.callback.value, (
        f"{text!r} должен дать callback, получили {outcome}"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Не интересно",
        "не нужно нам это",
        "не звоните больше",
        "До свидания",
    ],
)
def test_refusal_phrases_yield_not_interested(text: str):
    outcome = _outcome_for_stage("qualify", text)
    assert outcome == CallOutcome.not_interested.value


def test_callback_does_not_force_goodbye_stage():
    """`перезвоните позже` не должен переключать stage в goodbye."""
    next_stage = _next_stage("qualify", "перезвоните позже, я за рулём", qualify_count=1)
    assert next_stage != "goodbye"


def test_refusal_forces_goodbye_stage():
    next_stage = _next_stage("qualify", "не интересно, не звоните", qualify_count=1)
    assert next_stage == "goodbye"
