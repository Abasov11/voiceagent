"""Seed: команда клиента (Аскар, Бекзат, Данияр, Камила) + начальные учётки дашборда.

Запуск (внутри контейнера):
    docker exec voiceagent-backend python -m shared.seed
"""
from __future__ import annotations

import os
import secrets

from sqlalchemy import select

from shared.auth import hash_password
from shared.db import db_session
from shared.models import DashboardRole, DashboardUser, Manager


CURATED_TEAM = [
    # name, role, onlinepbx_extension (если знаем — пока нет, оставляем None)
    ("Аскар Демо", "owner", None),
    ("Бекзат", "rop", None),
    ("Данияр", "sales", None),
    ("Камила", "sales", None),
]

# email → (full_name, role, manager_name_or_None)
INITIAL_USERS = [
    ("owner@example.com", "Аскар Демо", DashboardRole.owner.value, "Аскар Демо"),
    ("director@example.com", "Бекзат", DashboardRole.director.value, "Бекзат"),
    # Менеджеры:
    ("manager1@example.com", "Данияр", DashboardRole.manager.value, "Данияр"),
    ("manager2@example.com", "Камила", DashboardRole.manager.value, "Камила"),
]


def upsert_managers() -> dict[str, int]:
    """Создаёт/находит менеджеров. Возвращает {name: id}."""
    out: dict[str, int] = {}
    with db_session() as db:
        for name, role, ext in CURATED_TEAM:
            existing = db.scalar(select(Manager).where(Manager.name == name))
            if existing:
                out[name] = existing.id
                continue
            m = Manager(name=name, role=role, onlinepbx_extension=ext, is_active=True)
            db.add(m)
            db.flush()
            out[name] = m.id
    return out


def upsert_users(manager_ids: dict[str, int]) -> list[tuple[str, str]]:
    """Создаёт учётки. Возвращает [(email, generated_password)]."""
    created: list[tuple[str, str]] = []
    with db_session() as db:
        for email, full_name, role, manager_name in INITIAL_USERS:
            existing = db.scalar(select(DashboardUser).where(DashboardUser.email == email))
            if existing:
                continue
            password = os.environ.get(f"SEED_PASSWORD_{email}", secrets.token_urlsafe(10))
            db.add(
                DashboardUser(
                    email=email.lower(),
                    password_hash=hash_password(password),
                    full_name=full_name,
                    role=role,
                    manager_id=manager_ids.get(manager_name) if manager_name else None,
                    is_active=True,
                )
            )
            created.append((email, password))
    return created


def main() -> None:
    mgrs = upsert_managers()
    users = upsert_users(mgrs)
    if users:
        print("Создал учётки (запиши пароли — больше не показываем):")
        for email, pwd in users:
            print(f"  {email:30s} {pwd}")
    else:
        print("Учётки уже существуют — пропуск.")
    print(f"Менеджеров в БД: {len(mgrs)}")


if __name__ == "__main__":
    main()
