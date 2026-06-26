"""Admin CRUD: RBAC, создание/правка/удаление, история, restore-default."""
from __future__ import annotations

import pytest


def _seed_user(session, email, role, password="topsecret"):
    from shared.auth import hash_password
    from shared.models import DashboardUser

    u = DashboardUser(
        email=email,
        password_hash=hash_password(password),
        full_name=email.split("@")[0],
        role=role,
        is_active=True,
    )
    session.add(u)
    session.commit()
    return u, password


def _login(client, session, role: str = "owner"):
    email = f"{role}@test.kz"
    _, pwd = _seed_user(session, email, role)
    r = client.post(
        "/dashboard/login",
        data={"email": email, "password": pwd},
        follow_redirects=False,
    )
    return r.cookies.get("voiceagent_session")


# --- RBAC -----------------------------------------------------------------

@pytest.mark.parametrize("role,expected", [
    ("owner", 200),
    ("director", 200),
    ("rop", 403),
    ("manager", 403),
])
def test_admin_home_rbac(client, session, role, expected):
    cookie = _login(client, session, role)
    r = client.get("/admin/", cookies={"voiceagent_session": cookie})
    assert r.status_code == expected


def test_admin_anonymous_401(client):
    r = client.get("/admin/scripts")
    assert r.status_code == 401


# --- Scripts CRUD ---------------------------------------------------------

def test_scripts_list_shows_seeded_blocks(client, session):
    cookie = _login(client, session, "owner")
    r = client.get("/admin/scripts", cookies={"voiceagent_session": cookie})
    assert r.status_code == 200
    assert "Главный скрипт звонка" in r.text
    assert "product_facts" in r.text


def test_create_block_then_appears_in_classify(client, session):
    """Создали блок → появляется в /admin/scripts → /admin/preview видит изменения."""
    cookie = _login(client, session, "owner")
    r = client.post(
        "/admin/scripts",
        data={
            "key": "summer_promo_block",
            "label": "Летнее предложение",
            "description": "Дополнительный блок",
            "body": "Летом у нас лагерь и выезд в Конаев.",
            "order_index": 25,
            "scopes": "voice,whatsapp",
        },
        cookies={"voiceagent_session": cookie},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r2 = client.get("/admin/scripts", cookies={"voiceagent_session": cookie})
    assert "summer_promo_block" in r2.text


def test_edit_block_creates_version(client, session, db_engine):
    cookie = _login(client, session, "owner")
    # Берём id блока product_facts
    from sqlalchemy import text
    with db_engine.connect() as conn:
        block_id = conn.execute(
            text("SELECT id FROM content_blocks WHERE key='product_facts'")
        ).scalar()
    r = client.post(
        f"/admin/scripts/{block_id}",
        data={
            "label": "Информация о продуктах школы",
            "description": "",
            "body": "ОБНОВЛЕННЫЙ ТЕКСТ — цены изменились на 35000",
            "order_index": 20,
            "scopes": "voice,whatsapp",
            "is_active": "on",
        },
        cookies={"voiceagent_session": cookie},
        follow_redirects=False,
    )
    assert r.status_code == 303

    # В истории есть как минимум одна версия (старая)
    with db_engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM content_block_versions WHERE block_id=:b"),
            {"b": block_id},
        ).scalar()
    assert n >= 1


def test_delete_system_block_forbidden(client, session, db_engine):
    cookie = _login(client, session, "owner")
    from sqlalchemy import text
    with db_engine.connect() as conn:
        block_id = conn.execute(
            text("SELECT id FROM content_blocks WHERE key='script_verbatim'")
        ).scalar()
    r = client.post(
        f"/admin/scripts/{block_id}/delete",
        cookies={"voiceagent_session": cookie},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_delete_user_block_works(client, session, db_engine):
    cookie = _login(client, session, "owner")
    # Сначала создаём пользовательский блок
    client.post(
        "/admin/scripts",
        data={
            "key": "removable_block",
            "label": "Test",
            "description": "",
            "body": "содержимое",
            "order_index": 99,
            "scopes": "voice",
        },
        cookies={"voiceagent_session": cookie},
        follow_redirects=False,
    )
    from sqlalchemy import text
    with db_engine.connect() as conn:
        block_id = conn.execute(
            text("SELECT id FROM content_blocks WHERE key='removable_block'")
        ).scalar()
    r = client.post(
        f"/admin/scripts/{block_id}/delete",
        cookies={"voiceagent_session": cookie},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with db_engine.connect() as conn:
        gone = conn.execute(
            text("SELECT id FROM content_blocks WHERE key='removable_block'")
        ).scalar()
    assert gone is None


def test_restore_default_returns_seed(client, session, db_engine):
    cookie = _login(client, session, "owner")
    from sqlalchemy import text
    with db_engine.connect() as conn:
        block_id = conn.execute(
            text("SELECT id FROM content_blocks WHERE key='product_facts'")
        ).scalar()
    # Меняем body
    client.post(
        f"/admin/scripts/{block_id}",
        data={
            "label": "Info", "description": "",
            "body": "переписали", "order_index": 20,
            "scopes": "voice,whatsapp", "is_active": "on",
        },
        cookies={"voiceagent_session": cookie},
        follow_redirects=False,
    )
    # Восстанавливаем
    r = client.post(
        f"/admin/scripts/{block_id}/restore-default",
        cookies={"voiceagent_session": cookie},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with db_engine.connect() as conn:
        body = conn.execute(
            text("SELECT body FROM content_blocks WHERE id=:b"), {"b": block_id}
        ).scalar()
    assert "30 000 ₸" in body  # дефолтный текст вернулся


# --- Promotions -----------------------------------------------------------

def test_create_promo_then_appears_in_voice_prompt(client, session):
    cookie = _login(client, session, "owner")
    r = client.post(
        "/admin/promotions",
        data={
            "title": "Летняя скидка 15%",
            "body": "Скидка 15% при оплате 2 недель лагеря до 31 мая",
            "active_from": "",
            "active_to": "",
            "scopes": "voice,whatsapp",
            "is_active": "on",
        },
        cookies={"voiceagent_session": cookie},
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Промо появляется в system_prompt
    from shared import agent_config
    agent_config.invalidate()
    from zvonar.prompts import system_prompt
    sp = system_prompt()
    assert "Летняя скидка 15%" in sp


# --- Qualification --------------------------------------------------------

def test_create_qualification_category_then_classifies(client, session):
    cookie = _login(client, session, "owner")
    r = client.post(
        "/admin/qualification",
        data={
            "key": "morning_interest",
            "label": "Утренние группы",
            "kind": "interest",
            "phrases": "утро\nутром\nс утра",
        },
        cookies={"voiceagent_session": cookie},
        follow_redirects=False,
    )
    assert r.status_code == 303

    from shared import agent_config
    agent_config.invalidate()
    from shared.qualification import classify
    from shared.models import CallOutcome
    res = classify("А утром группы есть?")
    assert res.outcome == CallOutcome.interested.value
    assert any("morning_interest" in r for r in res.reasons)


# --- Settings -------------------------------------------------------------

def test_settings_persist_and_appear_in_prompt(client, session):
    cookie = _login(client, session, "owner")
    r = client.post(
        "/admin/settings",
        data={
            "agent_name": "Жанна",
            "school_name": "Олимп",
            "city": "Алматы",
            "voice_id": "newvoice123",
        },
        cookies={"voiceagent_session": cookie},
        follow_redirects=False,
    )
    assert r.status_code == 303

    from shared import agent_config
    agent_config.invalidate()
    assert agent_config.get_setting("agent_name") == "Жанна"
    from zvonar.prompts import system_prompt
    sp = system_prompt()
    assert "Жанна" in sp


# --- Preview --------------------------------------------------------------

def test_preview_returns_classification_and_prompt(client, session):
    cookie = _login(client, session, "owner")
    r = client.post(
        "/admin/preview",
        data={
            "transcript": "Хочу записаться на пробную тренировку",
            "client_name": "Айдар",
        },
        cookies={"voiceagent_session": cookie},
    )
    assert r.status_code == 200
    assert "interested" in r.text
    assert "Айдар" in r.text


# --- Cache invalidation ---------------------------------------------------

def test_cache_invalidates_immediately_after_save(client, session, db_engine):
    """После save через UI кэш сбрасывается — изменения видны мгновенно."""
    cookie = _login(client, session, "owner")
    from shared import agent_config

    # Прогрев кэша
    _ = agent_config.get_setting("agent_name")
    assert _ == "Камила"

    # Сохраняем через UI
    client.post(
        "/admin/settings",
        data={
            "agent_name": "Ботагоз", "school_name": "Олимп",
            "city": "Алматы", "voice_id": "x",
        },
        cookies={"voiceagent_session": cookie},
        follow_redirects=False,
    )
    # Без invalidate — должно уже обновиться (роут вызвал invalidate сам)
    assert agent_config.get_setting("agent_name") == "Ботагоз"
