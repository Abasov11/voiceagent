"""Калькулятор стоимости звонка по компонентам.

Тарифы — оценочные, пересчитываются при изменении прайсов провайдеров.
Все возвращаемые значения в центах (USD * 100), округление вверх.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# Грубые тарифы (USD), обновлять при изменении прайсов.
SIP_USD_PER_MINUTE = 0.012        # Voximplant outbound RU/KZ avg
TTS_USD_PER_1K_CHARS = 0.18       # ElevenLabs Multilingual v2 (paid tier)
STT_USD_PER_MINUTE = 0.0036       # AssemblyAI universal-2
LLM_HAIKU_INPUT_USD_PER_MTOK = 0.80    # claude-haiku
LLM_HAIKU_OUTPUT_USD_PER_MTOK = 4.00
LLM_SONNET_INPUT_USD_PER_MTOK = 3.00   # claude-sonnet
LLM_SONNET_OUTPUT_USD_PER_MTOK = 15.00


def _ceil_cents(usd: float) -> int:
    return int(math.ceil(usd * 100))


@dataclass(frozen=True)
class CostInputs:
    sip_seconds: int = 0
    tts_seconds: int = 0
    tts_chars: int = 0
    stt_seconds: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_tier: str = "short"  # short → haiku, long → sonnet


@dataclass(frozen=True)
class CostBreakdown:
    sip_cost_cents: int
    tts_cost_cents: int
    stt_cost_cents: int
    llm_cost_cents: int
    total_cost_cents: int


def compute(inp: CostInputs) -> CostBreakdown:
    sip = _ceil_cents((inp.sip_seconds / 60.0) * SIP_USD_PER_MINUTE)
    tts = _ceil_cents((inp.tts_chars / 1000.0) * TTS_USD_PER_1K_CHARS)
    stt = _ceil_cents((inp.stt_seconds / 60.0) * STT_USD_PER_MINUTE)
    if inp.llm_tier == "long":
        llm_in = LLM_SONNET_INPUT_USD_PER_MTOK
        llm_out = LLM_SONNET_OUTPUT_USD_PER_MTOK
    else:
        llm_in = LLM_HAIKU_INPUT_USD_PER_MTOK
        llm_out = LLM_HAIKU_OUTPUT_USD_PER_MTOK
    llm = _ceil_cents(
        (inp.llm_input_tokens / 1_000_000.0) * llm_in
        + (inp.llm_output_tokens / 1_000_000.0) * llm_out
    )
    return CostBreakdown(
        sip_cost_cents=sip,
        tts_cost_cents=tts,
        stt_cost_cents=stt,
        llm_cost_cents=llm,
        total_cost_cents=sip + tts + stt + llm,
    )


def for_manager_call(
    *,
    duration_s: int,
    stt_cost_cents: Optional[int],
    llm_cost_cents: Optional[int],
) -> CostBreakdown:
    """Лёгкий путь: реальные cost_cents из api_call_log + SIP считаем по duration."""
    sip = _ceil_cents((duration_s / 60.0) * SIP_USD_PER_MINUTE)
    return CostBreakdown(
        sip_cost_cents=sip,
        tts_cost_cents=0,  # менеджерские звонки не используют TTS
        stt_cost_cents=int(stt_cost_cents or 0),
        llm_cost_cents=int(llm_cost_cents or 0),
        total_cost_cents=sip + int(stt_cost_cents or 0) + int(llm_cost_cents or 0),
    )
