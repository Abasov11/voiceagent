"""Сессии дашборда: cookie с подписью itsdangerous + bcrypt."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request, status
import bcrypt
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from shared.db import get_db
from shared.models import DashboardRole, DashboardUser
from shared.settings import get_settings

COOKIE_NAME = "voiceagent_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 дней

def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="dashboard")


def hash_password(plain: str) -> str:
    # bcrypt лимит — 72 байта
    return bcrypt.hashpw(plain.encode("utf-8")[:72], bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def make_session_cookie(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def parse_session_cookie(value: str) -> dict[str, Any] | None:
    try:
        return _serializer().loads(value, max_age=COOKIE_MAX_AGE)
    except (BadSignature, Exception):
        return None


def current_user(
    request: Request, db: Session = Depends(get_db)
) -> DashboardUser:
    raw = request.cookies.get(COOKIE_NAME)
    payload = parse_session_cookie(raw) if raw else None
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not logged in")
    user = db.get(DashboardUser, payload["uid"])
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user inactive")
    return user


def require_role(*roles: str):
    def _dep(user: DashboardUser = Depends(current_user)) -> DashboardUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role {user.role} not in {list(roles)}",
            )
        return user

    return _dep


# Helpers — кто может видеть что
def can_see_costs(user: DashboardUser) -> bool:
    return user.role == DashboardRole.owner.value


def can_see_all_managers(user: DashboardUser) -> bool:
    return user.role in (
        DashboardRole.owner.value,
        DashboardRole.director.value,
        DashboardRole.rop.value,
    )
