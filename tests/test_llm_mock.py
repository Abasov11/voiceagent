"""Тесты shared/llm: pick_tier и raise без ключа."""

from __future__ import annotations

import pytest

from shared.llm import LlmClient, pick_tier


def test_pick_tier_short_for_none():
    assert pick_tier(None) == "short"


def test_pick_tier_short_for_under_60s():
    assert pick_tier(0) == "short"
    assert pick_tier(59) == "short"


def test_pick_tier_long_for_60s_plus():
    assert pick_tier(60) == "long"
    assert pick_tier(3600) == "long"


def test_short_long_models_picked_correctly():
    c = LlmClient(openai_api_key=None, short_model="gpt-mini", long_model="gpt-1")
    assert c._model("short") == "gpt-mini"
    assert c._model("long") == "gpt-1"


async def test_score_dialog_raises_without_key():
    c = LlmClient(openai_api_key=None, short_model="gpt-mini", long_model="gpt-1")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await c.score_dialog(transcript="hi", criteria=["c1"], tier="short")


async def test_analyze_dialog_raises_without_key():
    c = LlmClient(openai_api_key=None, short_model="gpt-mini", long_model="gpt-1")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await c.analyze_dialog(transcript="hi", duration_s=120, tier="short")


def test_analyze_dialog_system_prompt_has_required_sections():
    """Безопасность контракта prompt'а: ключевые методологические блоки на месте."""
    from shared.llm import ANALYZE_DIALOG_SYSTEM_PROMPT as p
    for marker in (
        "ФВР", "STAR", "GROW",
        "for_manager", "for_rop", "total_score", "funnel_stage",
        "Никаких баллов",
        "VoiceAgent",
    ):
        assert marker in p, f"prompt missing required section: {marker}"
