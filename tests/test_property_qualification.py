"""Property-style тесты для shared/qualification и shared/cost_calculator.

Без `hypothesis` (не в requirements образа) — пользуемся parametrize и явными
комбинациями, покрывающими свойства:

- идемпотентность classify (повторный вызов даёт тот же результат)
- сильный refusal-маркер всегда побеждает interest+callback
- любое interest-слово даёт interested при отсутствии refusal
- cost_calculator: total = sum(components); монотонность; для нулевого ввода = 0
"""

from __future__ import annotations

import itertools

import pytest

from shared.cost_calculator import CostInputs, compute
from shared.models import CallOutcome
from shared.qualification import classify

REFUSAL_PHRASES = [
    "не интересно",
    "не нужно",
    "не нужны",
    "уберите",
    "не звоните",
    "перестаньте",
    "не беспокойте",
]
INTEREST_PHRASES = [
    "локация ближайшего филиала",
    "расписание тренировок",
    "пробную тренировку",
    "тренер кто",
    "когда начинается лагерь",
    "программа лагеря",
]
CALLBACK_PHRASES = [
    "перезвоните позже",
    "позвоните потом",
    "за рулём",
    "в дороге",
]


@pytest.mark.parametrize("text", REFUSAL_PHRASES + INTEREST_PHRASES + CALLBACK_PHRASES)
def test_classify_idempotent(text):
    a = classify(text)
    b = classify(text)
    assert a == b


@pytest.mark.parametrize("refusal,interest", itertools.product(REFUSAL_PHRASES, INTEREST_PHRASES))
def test_refusal_always_wins_over_interest(refusal, interest):
    txt = f"{interest}. {refusal}."
    assert classify(txt).outcome == CallOutcome.not_interested.value


@pytest.mark.parametrize("interest", INTEREST_PHRASES)
def test_interest_alone_gives_interested(interest):
    assert classify(interest).outcome == CallOutcome.interested.value


@pytest.mark.parametrize("callback", CALLBACK_PHRASES)
def test_callback_alone_gives_callback(callback):
    assert classify(callback).outcome == CallOutcome.callback.value


def test_classify_case_insensitive():
    a = classify("Не интересно")
    b = classify("НЕ ИНТЕРЕСНО")
    c = classify("не интересно")
    assert a.outcome == b.outcome == c.outcome == CallOutcome.not_interested.value


def test_classify_handles_unicode_whitespace():
    assert classify("\tне интересно   ").outcome == CallOutcome.not_interested.value


# --- cost_calculator ---


@pytest.mark.parametrize("sip,tts_chars,stt,llm_in,llm_out,tier", [
    (0, 0, 0, 0, 0, "short"),
    (60, 0, 0, 0, 0, "short"),
    (300, 1500, 180, 5000, 1000, "short"),
    (3600, 30000, 3600, 1_000_000, 200_000, "long"),
])
def test_total_equals_sum_of_components(sip, tts_chars, stt, llm_in, llm_out, tier):
    b = compute(CostInputs(
        sip_seconds=sip, tts_chars=tts_chars, stt_seconds=stt,
        llm_input_tokens=llm_in, llm_output_tokens=llm_out, llm_tier=tier,
    ))
    assert b.total_cost_cents == (
        b.sip_cost_cents + b.tts_cost_cents + b.stt_cost_cents + b.llm_cost_cents
    )


@pytest.mark.parametrize("tier", ["short", "long"])
def test_zero_inputs_zero_cost(tier):
    b = compute(CostInputs(llm_tier=tier))
    assert b.total_cost_cents == 0


@pytest.mark.parametrize("tier", ["short", "long"])
def test_monotonic_in_sip(tier):
    a = compute(CostInputs(sip_seconds=60, llm_tier=tier))
    b = compute(CostInputs(sip_seconds=120, llm_tier=tier))
    assert b.sip_cost_cents >= a.sip_cost_cents
    assert b.total_cost_cents >= a.total_cost_cents


@pytest.mark.parametrize("tier", ["short", "long"])
def test_monotonic_in_llm_tokens(tier):
    a = compute(CostInputs(llm_input_tokens=1000, llm_tier=tier))
    b = compute(CostInputs(llm_input_tokens=2000, llm_tier=tier))
    assert b.llm_cost_cents >= a.llm_cost_cents


def test_long_tier_at_least_as_expensive_as_short_for_same_tokens():
    short = compute(CostInputs(llm_input_tokens=10_000, llm_output_tokens=2_000, llm_tier="short"))
    long_ = compute(CostInputs(llm_input_tokens=10_000, llm_output_tokens=2_000, llm_tier="long"))
    assert long_.llm_cost_cents >= short.llm_cost_cents
