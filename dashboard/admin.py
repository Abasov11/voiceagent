"""Self-service админка: клиент сам редактирует скрипты, акции, фразы.

Доступ — только `owner` (Аскар) и `director` (Бекзат). Остальные роли
получают 403. После сохранения — `agent_config.invalidate()` сбрасывает
кэш, чтобы изменения подхватились немедленно (без TTL-окна 60с).

Маршруты:
  GET  /admin/                       — лендинг с разделами
  GET  /admin/scripts                — список content_blocks
  GET  /admin/scripts/new            — форма нового блока
  POST /admin/scripts                — создать блок
  GET  /admin/scripts/{id}/edit      — форма редактирования
  POST /admin/scripts/{id}           — сохранить (создаёт версию-снимок)
  POST /admin/scripts/{id}/delete    — удалить (только не is_system)
  GET  /admin/scripts/{id}/history   — список версий
  POST /admin/scripts/{id}/restore/{version_id}  — откатиться на версию
  POST /admin/scripts/{id}/restore-default  — вернуть default_body
  GET  /admin/promotions             — список промо
  GET  /admin/promotions/new         — форма
  POST /admin/promotions             — создать
  GET  /admin/promotions/{id}/edit   — форма редактирования
  POST /admin/promotions/{id}        — сохранить
  POST /admin/promotions/{id}/delete — удалить
  GET  /admin/qualification          — список категорий
  GET  /admin/qualification/new      — форма
  POST /admin/qualification          — создать
  GET  /admin/qualification/{id}/edit — форма
  POST /admin/qualification/{id}     — сохранить
  POST /admin/qualification/{id}/delete — удалить (только не is_system)
  POST /admin/qualification/{id}/restore-default — вернуть default_phrases
  GET  /admin/settings               — настройки агента
  POST /admin/settings               — сохранить настройки
  POST /admin/preview                — прогон тестовой фразы
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared import agent_config
from shared.auth import current_user, require_role
from shared.db import get_db
from shared.models import (
    AgentSetting,
    ContentBlock,
    ContentBlockVersion,
    DashboardRole,
    DashboardUser,
    Promotion,
    QualificationCategory,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_ROLES = (DashboardRole.owner.value, DashboardRole.director.value)
require_admin = require_role(*ADMIN_ROLES)


# ---------- helpers ------------------------------------------------------

def _parse_scopes(raw: str | list[str] | None) -> list[str]:
    """Принимает 'voice,whatsapp', 'voice', список или None."""
    if not raw:
        return []
    if isinstance(raw, list):
        scopes = raw
    else:
        scopes = [s.strip() for s in raw.split(",") if s.strip()]
    valid = {"voice", "whatsapp"}
    return [s for s in scopes if s in valid] or ["voice"]


def _parse_phrases(raw: str | None) -> list[str]:
    """Принимает фразы по строке. Пустые/повторы игнорируем."""
    if not raw:
        return []
    seen: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if s and s not in seen:
            seen.append(s)
    return seen


def _parse_dt(raw: str | None) -> datetime | None:
    """ISO-строка в UTC datetime. Пустое → None."""
    if not raw or not raw.strip():
        return None
    s = raw.strip().replace("T", " ")
    # Поддержка "YYYY-MM-DD HH:MM" и "YYYY-MM-DD"
    fmts = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail=f"Неверная дата: {raw}")


def _flash(ok: str | None = None, err: str | None = None) -> dict[str, str | None]:
    return {"ok": ok, "err": err}


# ---------- лендинг ------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def admin_home(
    request: Request,
    user: DashboardUser = Depends(require_admin),
) -> Response:
    return templates.TemplateResponse(request, "admin/home.html", {"active_page": "admin", "user": user})


@router.get("/help", response_class=HTMLResponse)
def admin_help(
    request: Request,
    user: DashboardUser = Depends(require_admin),
) -> Response:
    return templates.TemplateResponse(request, "admin/help.html", {"active_page": "help", "user": user})


# ---------- /admin/scripts -----------------------------------------------

@router.get("/scripts", response_class=HTMLResponse)
def scripts_list(
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
    ok: str | None = None,
) -> Response:
    blocks = db.execute(
        select(ContentBlock).order_by(ContentBlock.order_index, ContentBlock.id)
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "admin/scripts_list.html",
        {"user": user, "blocks": blocks, **_flash(ok=ok)},
    )


@router.get("/scripts/new", response_class=HTMLResponse)
def scripts_new(
    request: Request,
    user: DashboardUser = Depends(require_admin),
) -> Response:
    return templates.TemplateResponse(
        request, "admin/scripts_form.html",
        {"user": user, "block": None, **_flash()},
    )


@router.post("/scripts")
def scripts_create(
    key: str = Form(...),
    label: str = Form(...),
    description: str = Form(""),
    body: str = Form(...),
    order_index: int = Form(100),
    scopes: str = Form("voice"),
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    if db.scalar(select(ContentBlock).where(ContentBlock.key == key.strip())):
        raise HTTPException(status_code=400, detail=f"Блок с ключом '{key}' уже есть")
    block = ContentBlock(
        key=key.strip(),
        label=label.strip(),
        description=description.strip() or None,
        body=body,
        order_index=order_index,
        scopes=_parse_scopes(scopes),
        is_system=False,
        is_active=True,
        updated_by=user.email,
    )
    db.add(block)
    db.commit()
    agent_config.invalidate()
    return RedirectResponse(url="/admin/scripts?ok=Блок+создан", status_code=303)


@router.get("/scripts/{block_id}/edit", response_class=HTMLResponse)
def scripts_edit(
    block_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    block = db.get(ContentBlock, block_id)
    if not block:
        raise HTTPException(status_code=404, detail="Блок не найден")
    return templates.TemplateResponse(
        request, "admin/scripts_form.html",
        {"user": user, "block": block, **_flash()},
    )


@router.post("/scripts/{block_id}")
def scripts_save(
    block_id: int,
    label: str = Form(...),
    description: str = Form(""),
    body: str = Form(...),
    order_index: int = Form(100),
    scopes: str = Form("voice"),
    is_active: str = Form("on"),
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    block = db.get(ContentBlock, block_id)
    if not block:
        raise HTTPException(status_code=404, detail="Блок не найден")
    # Снимок ДО изменений → в версии
    if block.body != body:
        version = ContentBlockVersion(
            block_id=block.id, body=block.body, format=block.format,
            updated_by=user.email,
        )
        db.add(version)
    block.label = label.strip()
    block.description = description.strip() or None
    block.body = body
    block.order_index = order_index
    block.scopes = _parse_scopes(scopes)
    block.is_active = is_active == "on"
    block.updated_by = user.email
    db.commit()
    agent_config.invalidate()
    return RedirectResponse(url="/admin/scripts?ok=Сохранено", status_code=303)


@router.post("/scripts/{block_id}/delete")
def scripts_delete(
    block_id: int,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    block = db.get(ContentBlock, block_id)
    if not block:
        raise HTTPException(status_code=404, detail="Блок не найден")
    if block.is_system:
        raise HTTPException(
            status_code=400,
            detail="Системный блок нельзя удалить — выключите is_active или восстановите дефолт",
        )
    db.delete(block)
    db.commit()
    agent_config.invalidate()
    return RedirectResponse(url="/admin/scripts?ok=Удалено", status_code=303)


@router.get("/scripts/{block_id}/history", response_class=HTMLResponse)
def scripts_history(
    block_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    block = db.get(ContentBlock, block_id)
    if not block:
        raise HTTPException(status_code=404, detail="Блок не найден")
    versions = db.execute(
        select(ContentBlockVersion)
        .where(ContentBlockVersion.block_id == block_id)
        .order_by(ContentBlockVersion.created_at.desc())
    ).scalars().all()
    return templates.TemplateResponse(
        request, "admin/scripts_history.html",
        {"user": user, "block": block, "versions": versions, **_flash()},
    )


@router.post("/scripts/{block_id}/restore/{version_id}")
def scripts_restore(
    block_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    block = db.get(ContentBlock, block_id)
    version = db.get(ContentBlockVersion, version_id)
    if not block or not version or version.block_id != block_id:
        raise HTTPException(status_code=404, detail="Не найдено")
    # Сохраняем текущее тело как версию
    if block.body != version.body:
        snapshot = ContentBlockVersion(
            block_id=block.id, body=block.body, format=block.format,
            updated_by=user.email,
        )
        db.add(snapshot)
    block.body = version.body
    block.format = version.format
    block.updated_by = user.email
    db.commit()
    agent_config.invalidate()
    return RedirectResponse(
        url=f"/admin/scripts/{block_id}/edit?ok=Восстановлена+версия", status_code=303,
    )


@router.post("/scripts/{block_id}/restore-default")
def scripts_restore_default(
    block_id: int,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    block = db.get(ContentBlock, block_id)
    if not block:
        raise HTTPException(status_code=404, detail="Блок не найден")
    if not block.default_body:
        raise HTTPException(status_code=400, detail="У блока нет дефолта (не системный)")
    if block.body != block.default_body:
        snapshot = ContentBlockVersion(
            block_id=block.id, body=block.body, format=block.format,
            updated_by=user.email,
        )
        db.add(snapshot)
    block.body = block.default_body
    block.is_active = True
    block.updated_by = user.email
    db.commit()
    agent_config.invalidate()
    return RedirectResponse(
        url=f"/admin/scripts/{block_id}/edit?ok=Восстановлен+дефолт", status_code=303,
    )


# ---------- /admin/promotions --------------------------------------------

@router.get("/promotions", response_class=HTMLResponse)
def promos_list(
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
    ok: str | None = None,
) -> Response:
    promos = db.execute(
        select(Promotion).order_by(Promotion.is_active.desc(), Promotion.id.desc())
    ).scalars().all()
    return templates.TemplateResponse(
        request, "admin/promos_list.html",
        {"user": user, "promos": promos, "now": datetime.now(timezone.utc), **_flash(ok=ok)},
    )


@router.get("/promotions/new", response_class=HTMLResponse)
def promos_new(
    request: Request,
    user: DashboardUser = Depends(require_admin),
) -> Response:
    return templates.TemplateResponse(
        request, "admin/promos_form.html",
        {"user": user, "promo": None, **_flash()},
    )


@router.post("/promotions")
def promos_create(
    title: str = Form(...),
    body: str = Form(...),
    active_from: str = Form(""),
    active_to: str = Form(""),
    scopes: str = Form("voice,whatsapp"),
    is_active: str = Form("on"),
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    promo = Promotion(
        title=title.strip(),
        body=body,
        active_from=_parse_dt(active_from),
        active_to=_parse_dt(active_to),
        is_active=is_active == "on",
        scopes=_parse_scopes(scopes),
        updated_by=user.email,
    )
    db.add(promo)
    db.commit()
    agent_config.invalidate()
    return RedirectResponse(url="/admin/promotions?ok=Акция+создана", status_code=303)


@router.get("/promotions/{promo_id}/edit", response_class=HTMLResponse)
def promos_edit(
    promo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    promo = db.get(Promotion, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Акция не найдена")
    return templates.TemplateResponse(
        request, "admin/promos_form.html",
        {"user": user, "promo": promo, **_flash()},
    )


@router.post("/promotions/{promo_id}")
def promos_save(
    promo_id: int,
    title: str = Form(...),
    body: str = Form(...),
    active_from: str = Form(""),
    active_to: str = Form(""),
    scopes: str = Form("voice,whatsapp"),
    is_active: str = Form("off"),
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    promo = db.get(Promotion, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Акция не найдена")
    promo.title = title.strip()
    promo.body = body
    promo.active_from = _parse_dt(active_from)
    promo.active_to = _parse_dt(active_to)
    promo.scopes = _parse_scopes(scopes)
    promo.is_active = is_active == "on"
    promo.updated_by = user.email
    db.commit()
    agent_config.invalidate()
    return RedirectResponse(url="/admin/promotions?ok=Сохранено", status_code=303)


@router.post("/promotions/{promo_id}/delete")
def promos_delete(
    promo_id: int,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    promo = db.get(Promotion, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Акция не найдена")
    db.delete(promo)
    db.commit()
    agent_config.invalidate()
    return RedirectResponse(url="/admin/promotions?ok=Удалено", status_code=303)


# ---------- /admin/qualification -----------------------------------------

@router.get("/qualification", response_class=HTMLResponse)
def quali_list(
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
    ok: str | None = None,
) -> Response:
    cats = db.execute(
        select(QualificationCategory)
        .order_by(QualificationCategory.kind, QualificationCategory.key)
    ).scalars().all()
    return templates.TemplateResponse(
        request, "admin/quali_list.html",
        {"user": user, "categories": cats, **_flash(ok=ok)},
    )


@router.get("/qualification/new", response_class=HTMLResponse)
def quali_new(
    request: Request,
    user: DashboardUser = Depends(require_admin),
) -> Response:
    return templates.TemplateResponse(
        request, "admin/quali_form.html",
        {"user": user, "category": None, **_flash()},
    )


@router.post("/qualification")
def quali_create(
    key: str = Form(...),
    label: str = Form(...),
    kind: str = Form(...),
    phrases: str = Form(""),
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    if db.scalar(
        select(QualificationCategory).where(QualificationCategory.key == key.strip())
    ):
        raise HTTPException(status_code=400, detail=f"Категория '{key}' уже есть")
    if kind not in ("interest", "not_interested", "callback", "custom"):
        raise HTTPException(status_code=400, detail=f"Неверный kind: {kind}")
    cat = QualificationCategory(
        key=key.strip(),
        label=label.strip(),
        kind=kind,
        phrases=_parse_phrases(phrases),
        is_system=False,
        is_active=True,
        updated_by=user.email,
    )
    db.add(cat)
    db.commit()
    agent_config.invalidate()
    return RedirectResponse(
        url="/admin/qualification?ok=Категория+создана", status_code=303,
    )


@router.get("/qualification/{cat_id}/edit", response_class=HTMLResponse)
def quali_edit(
    cat_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    cat = db.get(QualificationCategory, cat_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    return templates.TemplateResponse(
        request, "admin/quali_form.html",
        {"user": user, "category": cat, **_flash()},
    )


@router.post("/qualification/{cat_id}")
def quali_save(
    cat_id: int,
    label: str = Form(...),
    kind: str = Form(...),
    phrases: str = Form(""),
    is_active: str = Form("off"),
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    cat = db.get(QualificationCategory, cat_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    if kind not in ("interest", "not_interested", "callback", "custom"):
        raise HTTPException(status_code=400, detail=f"Неверный kind: {kind}")
    cat.label = label.strip()
    cat.kind = kind
    cat.phrases = _parse_phrases(phrases)
    cat.is_active = is_active == "on"
    cat.updated_by = user.email
    db.commit()
    agent_config.invalidate()
    return RedirectResponse(url="/admin/qualification?ok=Сохранено", status_code=303)


@router.post("/qualification/{cat_id}/delete")
def quali_delete(
    cat_id: int,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    cat = db.get(QualificationCategory, cat_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    if cat.is_system:
        raise HTTPException(
            status_code=400,
            detail="Системную категорию нельзя удалить — выключите is_active или восстановите дефолт",
        )
    db.delete(cat)
    db.commit()
    agent_config.invalidate()
    return RedirectResponse(url="/admin/qualification?ok=Удалено", status_code=303)


@router.post("/qualification/{cat_id}/restore-default")
def quali_restore_default(
    cat_id: int,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    cat = db.get(QualificationCategory, cat_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    if cat.default_phrases is None:
        raise HTTPException(status_code=400, detail="У категории нет дефолта")
    cat.phrases = list(cat.default_phrases)
    cat.is_active = True
    cat.updated_by = user.email
    db.commit()
    agent_config.invalidate()
    return RedirectResponse(
        url=f"/admin/qualification/{cat_id}/edit?ok=Восстановлен+дефолт",
        status_code=303,
    )


# ---------- /admin/settings ----------------------------------------------

_SETTINGS_KEYS = ("agent_name", "school_name", "city", "voice_id")


@router.get("/settings", response_class=HTMLResponse)
def settings_view(
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
    ok: str | None = None,
) -> Response:
    rows = db.execute(select(AgentSetting)).scalars().all()
    values = {r.key: r.value for r in rows}
    # Дополним отсутствующие ключи дефолтами для отображения
    for k in _SETTINGS_KEYS:
        values.setdefault(k, "")
    return templates.TemplateResponse(
        request, "admin/settings.html",
        {"user": user, "values": values, **_flash(ok=ok)},
    )


@router.post("/settings")
def settings_save(
    request: Request,
    agent_name: str = Form(""),
    school_name: str = Form(""),
    city: str = Form(""),
    voice_id: str = Form(""),
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    pairs = [
        ("agent_name", agent_name.strip()),
        ("school_name", school_name.strip()),
        ("city", city.strip()),
        ("voice_id", voice_id.strip()),
    ]
    for key, value in pairs:
        if not value:
            continue
        row = db.get(AgentSetting, key)
        if row:
            row.value = value
            row.updated_by = user.email
        else:
            db.add(AgentSetting(key=key, value=value, updated_by=user.email))
    db.commit()
    agent_config.invalidate()
    return RedirectResponse(url="/admin/settings?ok=Сохранено", status_code=303)


# ---------- /admin/preview -----------------------------------------------

@router.get("/preview", response_class=HTMLResponse)
def preview_form(
    request: Request,
    user: DashboardUser = Depends(require_admin),
) -> Response:
    return templates.TemplateResponse(
        request, "admin/preview.html",
        {"user": user, "result": None, **_flash()},
    )


@router.post("/preview", response_class=HTMLResponse)
def preview_run(
    request: Request,
    transcript: str = Form(""),
    client_name: str = Form(""),
    user: DashboardUser = Depends(require_admin),
) -> Response:
    """Прогон тестовой реплики через текущий конфиг — что увидит/ответит агент.

    Возвращает: (а) полный собранный system_prompt, (б) результат
    qualification.classify(), (в) пример WhatsApp-сообщения.
    """
    from shared.qualification import classify
    from shared.whatsapp_template import WhatsAppContext, render_lead_message
    from zvonar.prompts import system_prompt

    sp = system_prompt(client_name=client_name.strip() or None)
    qr = classify(transcript) if transcript.strip() else None
    wa = render_lead_message(WhatsAppContext(lead_name=client_name.strip() or None))

    return templates.TemplateResponse(
        request, "admin/preview.html",
        {
            "user": user,
            "result": {
                "transcript": transcript,
                "client_name": client_name,
                "system_prompt": sp,
                "qualification": qr,
                "whatsapp": wa,
            },
            **_flash(),
        },
    )
