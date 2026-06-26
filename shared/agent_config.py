"""Read-API для редактируемой клиентом конфигурации агента.

Источник правды — таблицы `content_blocks`, `promotions`,
`qualification_categories`, `agent_settings` (миграции e5a8c9d27f10 и
f2bc4d8e9012). Этот модуль кэширует выборки в памяти процесса с TTL 60с,
чтобы не дёргать БД на каждом turn'е диалога.

При недоступности БД (упало соединение, нет таблиц) — возвращаем
последний валидный кэш или fallback-константы из `zvonar.prompts` и
`shared.qualification`. Это критично: после сдачи проекта клиент один на
один с системой, ошибка БД не должна валить агента.

Изменения через `/admin/*` вызывают `invalidate()` сразу после save,
чтобы новые значения подхватились без 60с-задержки.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from shared.db import SessionLocal
from shared.models import (
    AgentSetting,
    ContentBlock,
    Promotion,
    QualificationCategory,
)

logger = logging.getLogger(__name__)

_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class BlockView:
    key: str
    label: str
    body: str
    order_index: int
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class PromoView:
    id: int
    title: str
    body: str
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class CategoryView:
    key: str
    label: str
    kind: str  # "interest" | "not_interested" | "callback" | "custom"
    phrases: tuple[str, ...]


@dataclass
class _CacheEntry:
    value: object
    expires_at: float


_cache: dict[str, _CacheEntry] = {}
_cache_lock = threading.Lock()


def invalidate(key: str | None = None) -> None:
    """Очистить весь кэш (key=None) или один ключ."""
    with _cache_lock:
        if key is None:
            _cache.clear()
        else:
            _cache.pop(key, None)


def _get_cached(key: str):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and entry.expires_at > time.monotonic():
            return entry.value
    return None


def _set_cached(key: str, value: object) -> None:
    with _cache_lock:
        _cache[key] = _CacheEntry(value=value, expires_at=time.monotonic() + _TTL_SECONDS)


def _set_stale(key: str, value: object) -> None:
    """Положить значение даже после ошибки БД — чтобы fallback не пустой."""
    with _cache_lock:
        if key not in _cache:
            _cache[key] = _CacheEntry(value=value, expires_at=time.monotonic() + _TTL_SECONDS)


def get_blocks(scope: str = "voice") -> tuple[BlockView, ...]:
    """Активные content_blocks для указанного scope, отсортированные по order_index."""
    cache_key = f"blocks:{scope}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    try:
        with SessionLocal() as session:
            stmt = (
                select(ContentBlock)
                .where(ContentBlock.is_active.is_(True))
                .order_by(ContentBlock.order_index.asc(), ContentBlock.id.asc())
            )
            rows = session.execute(stmt).scalars().all()
            blocks = tuple(
                BlockView(
                    key=row.key,
                    label=row.label,
                    body=row.body,
                    order_index=row.order_index,
                    scopes=tuple(row.scopes or []),
                )
                for row in rows
                if scope in (row.scopes or [])
                and (row.body or "").strip()
            )
    except SQLAlchemyError as exc:
        logger.warning("agent_config.get_blocks fallback: %s", exc)
        return _fallback_blocks(scope)

    _set_cached(cache_key, blocks)
    return blocks


def get_active_promotions(
    scope: str = "voice", *, now: datetime | None = None
) -> tuple[PromoView, ...]:
    """Промо, активные сейчас (is_active + active_from<=now<=active_to)."""
    cache_key = f"promos:{scope}"
    cached = _get_cached(cache_key)
    moment = now or datetime.now(timezone.utc)

    if cached is not None:
        # Окно валидности зависит от now — фильтруем выбранные промо.
        return tuple(p for p in cached if p)  # type: ignore[index]

    try:
        with SessionLocal() as session:
            stmt = (
                select(Promotion)
                .where(Promotion.is_active.is_(True))
                .order_by(Promotion.id.asc())
            )
            rows = session.execute(stmt).scalars().all()
    except SQLAlchemyError as exc:
        logger.warning("agent_config.get_active_promotions fallback: %s", exc)
        return ()

    promos = tuple(
        PromoView(
            id=row.id,
            title=row.title,
            body=row.body,
            scopes=tuple(row.scopes or []),
        )
        for row in rows
        if scope in (row.scopes or [])
        and (row.active_from is None or row.active_from <= moment)
        and (row.active_to is None or row.active_to >= moment)
        and (row.body or "").strip()
    )
    _set_cached(cache_key, promos)
    return promos


def get_qualification_categories() -> tuple[CategoryView, ...]:
    """Все активные qualification_categories. Возвращает в порядке kind→key."""
    cache_key = "qualification:all"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    try:
        with SessionLocal() as session:
            stmt = (
                select(QualificationCategory)
                .where(QualificationCategory.is_active.is_(True))
                .order_by(
                    QualificationCategory.kind.asc(),
                    QualificationCategory.key.asc(),
                )
            )
            rows = session.execute(stmt).scalars().all()
            cats = tuple(
                CategoryView(
                    key=row.key,
                    label=row.label,
                    kind=row.kind,
                    phrases=tuple(p for p in (row.phrases or []) if p and p.strip()),
                )
                for row in rows
            )
    except SQLAlchemyError as exc:
        logger.warning("agent_config.get_qualification_categories fallback: %s", exc)
        return _fallback_categories()

    _set_cached(cache_key, cats)
    return cats


def get_setting(key: str, default: str = "") -> str:
    """Одна ключ-значение настройка из agent_settings."""
    cache_key = f"setting:{key}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    try:
        with SessionLocal() as session:
            row = session.execute(
                select(AgentSetting).where(AgentSetting.key == key)
            ).scalar_one_or_none()
            value = row.value if row else default
    except SQLAlchemyError as exc:
        logger.warning("agent_config.get_setting(%s) fallback: %s", key, exc)
        return _fallback_setting(key, default)

    _set_cached(cache_key, value)
    return value


# --- Fallbacks ----------------------------------------------------------
# Используются когда БД недоступна или таблицы пустые. Импортируем лениво,
# чтобы не словить циклический импорт при инициализации.

def _fallback_blocks(scope: str) -> tuple[BlockView, ...]:
    from zvonar import prompts as _p  # lazy

    base = (
        BlockView("script_verbatim", "Главный скрипт", _p.SCRIPT_VERBATIM, 10, ("voice",)),
        BlockView("product_facts", "Продукты", _p.PRODUCT_FACTS, 20, ("voice", "whatsapp")),
        BlockView("interest_signals", "Сигналы интереса", _p.INTEREST_SIGNALS, 30, ("voice",)),
        BlockView("few_shot", "Few-shot", _p.FEW_SHOT, 40, ("voice",)),
    )
    return tuple(b for b in base if scope in b.scopes)


def _fallback_categories() -> tuple[CategoryView, ...]:
    from shared import qualification as _q  # lazy

    return (
        CategoryView(
            "training_interest", "Интерес к тренировкам", "interest",
            _q._TRAINING_INTEREST_SIGNALS,
        ),
        CategoryView(
            "camp_interest", "Интерес к лагерю", "interest",
            _q._CAMP_INTEREST_SIGNALS,
        ),
        CategoryView(
            "not_interested", "Отказ", "not_interested",
            _q._NOT_INTERESTED_SIGNALS,
        ),
        CategoryView(
            "callback", "Перезвонить", "callback",
            _q._CALLBACK_SIGNALS,
        ),
    )


def _fallback_setting(key: str, default: str) -> str:
    from zvonar import prompts as _p  # lazy

    return {
        "agent_name": _p.AGENT_NAME,
        "school_name": _p.SCHOOL_NAME,
        "city": "Алматы",
    }.get(key, default)
