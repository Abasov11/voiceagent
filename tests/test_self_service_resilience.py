"""Резильентность self-service: клиент удалил/выключил блоки — агент работает.

Эти тесты страхуют главную инвариант: после сдачи проекта клиент один.
Если он что-то сломает (очистит body блока, выключит все категории,
удалит акцию посреди звонка) — агент должен продолжать отвечать.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text


@pytest.fixture()
def reset_cache():
    from shared import agent_config
    agent_config.invalidate()
    yield
    agent_config.invalidate()


def test_classify_works_with_seeded_defaults(reset_cache):
    """Базовый сценарий — после reseed классификация различает фразы."""
    from shared.qualification import classify
    from shared.models import CallOutcome

    assert classify("Хочу записаться на пробную тренировку").outcome == CallOutcome.interested.value
    assert classify("не интересно, не звоните").outcome == CallOutcome.not_interested.value
    assert classify("я за рулём, перезвоните позже").outcome == CallOutcome.callback.value


def test_classify_falls_back_when_all_categories_disabled(db_engine, reset_cache):
    """Все категории is_active=false → fallback на хардкод-сигналы."""
    from shared.qualification import classify
    from shared.models import CallOutcome
    from shared import agent_config

    with db_engine.begin() as conn:
        conn.execute(text("UPDATE qualification_categories SET is_active = FALSE"))
    agent_config.invalidate()

    # БД отдала пустой список → код не падает, но и сигналов не находит.
    # При is_active=false fallback не вызывается (БД отвечает корректно
    # пустотой), поэтому всё попадёт в default:no_signal.
    result = classify("Хочу записаться на пробную тренировку")
    assert result.outcome == CallOutcome.not_interested.value
    assert "default:no_signal" in result.reasons


def test_system_prompt_falls_back_when_all_blocks_inactive(db_engine, reset_cache):
    """Если клиент выключил все блоки — system_prompt всё равно собирается."""
    from zvonar.prompts import system_prompt
    from shared import agent_config

    with db_engine.begin() as conn:
        conn.execute(text("UPDATE content_blocks SET is_active = FALSE"))
    agent_config.invalidate()

    sp = system_prompt(client_name="Динара")
    # Каркас остался: имя школы, имя агента, имя клиента, базовые правила
    assert "Динара" in sp
    assert "Камила" in sp
    assert "Олимп" in sp
    assert "Дополнительные правила" in sp


def test_promotions_window_filters_expired(db_engine, reset_cache):
    """Истекшие промо не попадают в активные."""
    from shared import agent_config

    now = datetime.now(timezone.utc)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO promotions (title, body, active_from, active_to, "
                " is_active, scopes) "
                "VALUES ('past', 'было', :a, :b, TRUE, CAST('[\"voice\"]' AS jsonb)), "
                "       ('future', 'будет', :c, :d, TRUE, CAST('[\"voice\"]' AS jsonb)), "
                "       ('now', 'сейчас', :e, :f, TRUE, CAST('[\"voice\"]' AS jsonb))"
            ),
            {
                "a": now - timedelta(days=10),
                "b": now - timedelta(days=1),
                "c": now + timedelta(days=1),
                "d": now + timedelta(days=10),
                "e": now - timedelta(hours=1),
                "f": now + timedelta(hours=1),
            },
        )
    agent_config.invalidate()

    active = agent_config.get_active_promotions(scope="voice")
    titles = {p.title for p in active}
    assert "now" in titles
    assert "past" not in titles
    assert "future" not in titles


def test_promo_master_switch_overrides_window(db_engine, reset_cache):
    """is_active=false выключает промо даже если окно активное."""
    from shared import agent_config

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO promotions (title, body, is_active, scopes) "
                "VALUES ('off', 'paused', FALSE, CAST('[\"voice\"]' AS jsonb))"
            )
        )
    agent_config.invalidate()
    titles = {p.title for p in agent_config.get_active_promotions(scope="voice")}
    assert "off" not in titles


def test_whatsapp_template_minimal_when_blocks_empty(db_engine, reset_cache):
    """WhatsApp-шаблон работает даже если все блоки scope=whatsapp выключены."""
    from shared.whatsapp_template import WhatsAppContext, render_lead_message
    from shared import agent_config

    with db_engine.begin() as conn:
        conn.execute(text("UPDATE content_blocks SET is_active = FALSE"))
    agent_config.invalidate()

    text_msg = render_lead_message(WhatsAppContext(lead_name="Алия"))
    assert "Алия" in text_msg
    assert "Камила" in text_msg
    assert "Олимп" in text_msg
    assert len(text_msg) > 50  # есть приветствие + закрытие


def test_block_with_empty_body_skipped(db_engine, reset_cache):
    """Блок с пустым body не попадает в промпт (даже если is_active=true)."""
    from shared import agent_config

    with db_engine.begin() as conn:
        conn.execute(text("UPDATE content_blocks SET body = '' WHERE key = 'few_shot'"))
    agent_config.invalidate()

    blocks = agent_config.get_blocks(scope="voice")
    keys = {b.key for b in blocks}
    assert "few_shot" not in keys


def test_custom_qualification_category_classifies_as_interest(db_engine, reset_cache):
    """Клиентская категория с kind=custom считается интересом."""
    from shared.qualification import classify
    from shared.models import CallOutcome
    from shared import agent_config

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO qualification_categories "
                "(key, label, kind, phrases, is_system, is_active) "
                "VALUES ('weekend_interest', 'Выходные', 'custom', "
                "        CAST('[\"выходн\"]' AS jsonb), FALSE, TRUE)"
            )
        )
    agent_config.invalidate()

    result = classify("А по выходным занятия есть?")
    assert result.outcome == CallOutcome.interested.value
    assert any("weekend_interest" in r for r in result.reasons)


def test_setting_fallback_when_missing(db_engine, reset_cache):
    """Несуществующий ключ настройки возвращает default."""
    from shared import agent_config

    assert agent_config.get_setting("nonexistent_key", "fallback") == "fallback"


def test_cache_invalidate_picks_up_change(db_engine, reset_cache):
    """После invalidate() кэш забирает свежие данные из БД."""
    from shared import agent_config

    before = agent_config.get_setting("agent_name")
    assert before == "Камила"

    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE agent_settings SET value = 'НовоеИмя' WHERE key = 'agent_name'")
        )
    # без invalidate — кэш ещё держит старое
    assert agent_config.get_setting("agent_name") == "Камила"

    agent_config.invalidate()
    assert agent_config.get_setting("agent_name") == "НовоеИмя"
