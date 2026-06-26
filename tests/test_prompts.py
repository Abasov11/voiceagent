"""Snapshot-тесты для zvonar.prompts.

Цель: ловить случайные правки в формулировках. Если правка осознанная —
обновить ожидаемые маркеры ниже.

Скрипт «по заявке» от клиента (Скрипт.docx 2026-05-02) — single source of
truth, см. docs/SCRIPT_INBOUND_LEAD.md.
"""
from __future__ import annotations

import pytest

from zvonar.prompts import Stage, stage_instruction, system_prompt


def test_system_prompt_contains_brand_and_tone():
    sp = system_prompt()
    assert "Олимп" in sp
    assert "Алматы" in sp
    assert "по-русски" in sp.lower() or "русски" in sp
    # Цены: только из PRODUCT_FACTS
    assert "30 000" in sp
    assert "90 000" in sp
    assert "Kaspi" in sp or "kaspi" in sp.lower()


def test_system_prompt_includes_safety_rules():
    sp = system_prompt()
    # Не выдумывать цен, не давать скидок
    assert "скидок" in sp
    assert "выдумывай" in sp


def test_system_prompt_has_script_verbatim():
    sp = system_prompt()
    # Пять обязательных квалификационных вопросов (из Скрипт.docx)
    assert "квалификационн" in sp.lower()
    assert "Ребенок ранее тренировался" in sp
    assert "Возраст ребенка и район" in sp
    assert "Когда хотите на пробную" in sp
    # Шаблоны возражений
    assert "Дорого" in sp
    assert "Подумаем" in sp


def test_system_prompt_uses_warm_lead_framing():
    sp = system_prompt()
    # Это исходящий звонок ПО ЗАЯВКЕ, не cold-call
    assert "заявк" in sp.lower()
    assert "Камила" in sp


def test_client_name_injection():
    sp = system_prompt(client_name="Динара")
    assert "Динара" in sp


@pytest.mark.parametrize(
    "stage",
    ["greet", "confirm_request", "qualify", "present", "objection", "close", "goodbye"],
)
def test_stage_instructions_non_empty(stage: Stage):
    s = stage_instruction(stage)
    assert s, f"empty instruction for {stage}"
    assert len(s) > 20


def test_greet_introduces_agent_and_school():
    g = stage_instruction("greet")
    assert "Камила" in g
    assert "Олимп" in g


def test_confirm_request_asks_about_application():
    c = stage_instruction("confirm_request")
    assert "заявк" in c.lower()


def test_qualify_lists_five_questions():
    q = stage_instruction("qualify")
    assert "тренировался" in q
    assert "Возраст" in q
    assert "район" in q.lower()
    assert "пробную" in q
    assert "Почему" in q


def test_close_confirms_whatsapp():
    c = stage_instruction("close")
    assert "WhatsApp" in c or "whatsapp" in c.lower()
    assert "пробн" in c.lower() or "тренер" in c.lower()
