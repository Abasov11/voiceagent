"""Тесты shared/seed: idempotent upsert, hash паролей, привязка manager_id."""

from __future__ import annotations

from sqlalchemy import select

from shared import seed as seed_mod
from shared.auth import verify_password
from shared.models import DashboardRole, DashboardUser, Manager


def test_upsert_managers_creates_curated_team(session):
    out = seed_mod.upsert_managers()
    assert set(out) == {"Аскар Демо", "Бекзат", "Данияр", "Камила"}
    rows = session.scalars(select(Manager)).all()
    assert len(rows) == 4
    by_name = {m.name: m for m in rows}
    assert by_name["Аскар Демо"].role == "owner"
    assert by_name["Бекзат"].role == "rop"


def test_upsert_managers_idempotent(session):
    seed_mod.upsert_managers()
    seed_mod.upsert_managers()  # второй вызов не должен создавать дубли
    assert session.scalar(select(Manager).where(Manager.name == "Бекзат")) is not None
    assert session.query(Manager).count() == 4


def test_upsert_users_creates_passwords(session, monkeypatch):
    # Фиксируем пароль через env, чтобы тест был детерминированным
    monkeypatch.setenv("SEED_PASSWORD_owner@example.com", "test_owner_pw")
    mgr_ids = seed_mod.upsert_managers()
    created = seed_mod.upsert_users(mgr_ids)
    by_email = dict(created)
    assert by_email["owner@example.com"] == "test_owner_pw"

    user = session.scalar(
        select(DashboardUser).where(DashboardUser.email == "owner@example.com")
    )
    assert user is not None
    assert user.role == DashboardRole.owner.value
    assert verify_password("test_owner_pw", user.password_hash)
    assert user.manager_id == mgr_ids["Аскар Демо"]


def test_upsert_users_idempotent(session):
    mgr_ids = seed_mod.upsert_managers()
    first = seed_mod.upsert_users(mgr_ids)
    second = seed_mod.upsert_users(mgr_ids)
    assert len(first) == 4
    assert second == []  # все уже есть


def test_initial_users_cover_all_roles():
    roles = {role for _, _, role, _ in seed_mod.INITIAL_USERS}
    assert DashboardRole.owner.value in roles
    assert DashboardRole.director.value in roles
    assert DashboardRole.manager.value in roles
