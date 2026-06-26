"""Pytest фикстуры. БД для тестов — отдельная test_voiceagent в том же Postgres.

ВАЖНО: подмена DATABASE_URL делается на module-level до любого `shared.*`-импорта,
иначе `shared.db.engine` закэшируется с прод-DSN и TRUNCATE поедет в прод.
"""
from __future__ import annotations

import os

TEST_DB_NAME = "test_voiceagent"


def _switch_env_to_test_db() -> str:
    """Создаёт test_voiceagent (если ещё нет) и подменяет DATABASE_URL.

    Должно вызываться до любого импорта shared.*.
    """
    main_url = os.environ.get("DATABASE_URL")
    if not main_url:
        raise RuntimeError("DATABASE_URL must be set in env before running tests")
    base, _, current_db = main_url.rpartition("/")
    if current_db == TEST_DB_NAME:
        # уже подменено (например, повторный сбор pytest)
        return main_url
    test_url = f"{base}/{TEST_DB_NAME}"
    admin_url = f"{base}/postgres"

    from sqlalchemy import create_engine, text  # локальный импорт — не shared.*

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname=:n"),
                {"n": TEST_DB_NAME},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    finally:
        admin_engine.dispose()

    os.environ["DATABASE_URL"] = test_url
    return test_url


_TEST_DB_URL = _switch_env_to_test_db()


# --- ниже уже можно импортировать shared.*, engine будет привязан к test-БД --

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402


def _assert_test_db_only(engine) -> None:
    """Защита: операции массовой очистки разрешены только на test_voiceagent.

    Если по какой-то причине engine привязан к другой БД — кидаем, чтобы не
    полить прод.
    """
    db_name = engine.url.database
    if db_name != TEST_DB_NAME:
        raise RuntimeError(
            f"Refusing to mutate non-test DB: engine bound to '{db_name}', "
            f"expected '{TEST_DB_NAME}'. Test isolation is broken — abort.",
        )


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_db():
    """Накатывает alembic upgrade head на тестовую БД (один раз за сессию)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config("/app/shared/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", _TEST_DB_URL)
    command.upgrade(cfg, "head")
    yield


@pytest.fixture()
def db_engine(_migrate_test_db):
    from shared.db import engine

    _assert_test_db_only(engine)
    return engine


@pytest.fixture(autouse=True)
def _truncate_all(_migrate_test_db):
    """Перед каждым тестом — очищаем таблицы и пересеиваем self-service дефолты."""
    from shared.db import engine

    _assert_test_db_only(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE leads, manager_calls, transcripts, llm_scores, "
                "call_summaries, zvonar_calls, whatsapp_sends, dashboard_users, "
                "managers, api_call_log, existing_clients, call_cost_breakdown, "
                "content_blocks, content_block_versions, promotions, "
                "qualification_categories, agent_settings RESTART IDENTITY CASCADE"
            )
        )
    from shared import agent_config
    agent_config.invalidate()

    _reseed_self_service_defaults()
    yield


def _reseed_self_service_defaults() -> None:
    """Пересеивает данные из миграции f2bc4d8e9012 (системные блоки/категории)."""
    import importlib.util
    from pathlib import Path

    mig_path = Path("/app/shared/alembic/versions/f2bc4d8e9012_seed_self_service_defaults.py")
    if not mig_path.exists():
        return
    spec = importlib.util.spec_from_file_location("seed_mig", mig_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    import json
    from shared.db import engine
    from sqlalchemy import text as sql_text

    _assert_test_db_only(engine)
    with engine.begin() as conn:
        for block in mod.CONTENT_BLOCKS:
            conn.execute(
                sql_text(
                    "INSERT INTO content_blocks "
                    "(key, label, description, body, format, order_index, scopes, "
                    " is_system, is_active, default_body, updated_by) "
                    "VALUES (:key, :label, :description, :body, 'text', :order_index, "
                    "        CAST(:scopes AS jsonb), TRUE, TRUE, :body, 'system') "
                    "ON CONFLICT (key) DO NOTHING"
                ),
                {
                    "key": block["key"],
                    "label": block["label"],
                    "description": block["description"],
                    "body": block["body"],
                    "order_index": block["order_index"],
                    "scopes": json.dumps(block["scopes"]),
                },
            )
        for key, value in mod.AGENT_SETTINGS:
            conn.execute(
                sql_text(
                    "INSERT INTO agent_settings (key, value, updated_by) "
                    "VALUES (:key, :value, 'system') "
                    "ON CONFLICT (key) DO NOTHING"
                ),
                {"key": key, "value": value},
            )
        for cat in mod.QUALIFICATION_CATEGORIES:
            conn.execute(
                sql_text(
                    "INSERT INTO qualification_categories "
                    "(key, label, kind, phrases, is_system, is_active, "
                    " default_phrases, updated_by) "
                    "VALUES (:key, :label, :kind, CAST(:phrases AS jsonb), "
                    "        TRUE, TRUE, CAST(:phrases AS jsonb), 'system') "
                    "ON CONFLICT (key) DO NOTHING"
                ),
                {
                    "key": cat["key"],
                    "label": cat["label"],
                    "kind": cat["kind"],
                    "phrases": json.dumps(cat["phrases"], ensure_ascii=False),
                },
            )


@pytest.fixture()
def client(_migrate_test_db) -> TestClient:
    from shared.app import app

    return TestClient(app)


@pytest.fixture()
def session():
    from shared.db import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
