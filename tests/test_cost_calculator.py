"""Тесты unit-economics-калькулятора shared/cost_calculator."""

from __future__ import annotations

from shared.cost_calculator import CostInputs, compute, for_manager_call


def test_zero_inputs_zero_cost():
    b = compute(CostInputs())
    assert b.total_cost_cents == 0
    assert b.sip_cost_cents == 0
    assert b.llm_cost_cents == 0


def test_60s_sip_call():
    b = compute(CostInputs(sip_seconds=60))
    # 1 минута × 0.012 USD = 0.012 USD = 1.2 цента → ceil = 2
    assert b.sip_cost_cents == 2


def test_short_llm_uses_haiku_pricing():
    b = compute(CostInputs(llm_input_tokens=1_000_000, llm_output_tokens=0, llm_tier="short"))
    # 1M токенов × $0.80 = $0.80 = 80 центов
    assert b.llm_cost_cents == 80


def test_long_llm_uses_sonnet_pricing():
    b = compute(CostInputs(llm_input_tokens=1_000_000, llm_output_tokens=0, llm_tier="long"))
    # 1M токенов × $3.00 = $3.00 = 300 центов
    assert b.llm_cost_cents == 300


def test_total_is_sum_of_components():
    b = compute(CostInputs(
        sip_seconds=120, tts_chars=2000, stt_seconds=120,
        llm_input_tokens=10_000, llm_output_tokens=2_000, llm_tier="short",
    ))
    assert b.total_cost_cents == (
        b.sip_cost_cents + b.tts_cost_cents + b.stt_cost_cents + b.llm_cost_cents
    )


def test_for_manager_call_uses_provided_costs():
    b = for_manager_call(duration_s=180, stt_cost_cents=4, llm_cost_cents=5)
    assert b.stt_cost_cents == 4
    assert b.llm_cost_cents == 5
    assert b.tts_cost_cents == 0
    assert b.sip_cost_cents > 0
    assert b.total_cost_cents == b.sip_cost_cents + 4 + 5
