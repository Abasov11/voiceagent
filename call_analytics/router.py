"""FastAPI router для аналитики менеджерских звонков."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from shared.db import get_db
from shared.models import ManagerCall
from shared.onlinepbx import OnlinePbxClient
from shared.settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _onlinepbx() -> OnlinePbxClient:
    s = get_settings()
    return OnlinePbxClient(
        domain=s.onlinepbx_domain or "",
        user=s.onlinepbx_user,
        password=s.onlinepbx_password,
        webhook_secret=s.onlinepbx_webhook_secret,
        webhook_secret_required=s.onlinepbx_webhook_secret_required,
    )


@router.post("/onlinepbx", status_code=status.HTTP_202_ACCEPTED)
async def onlinepbx_webhook(
    request: Request,
    background: BackgroundTasks,
    x_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    raw = await request.body()
    content_type = request.headers.get("content-type", "")
    log.info("webhook raw content_type=%s body=%s", content_type, raw[:500])
    pbx = _onlinepbx()
    if not pbx.verify_webhook_signature(raw, x_signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        payload = await request.json()
    except Exception:
        # OnlinePBX may send form-urlencoded
        try:
            form = await request.form()
            payload = dict(form)
        except Exception as exc2:
            log.error("webhook parse fail: raw=%s", raw[:500])
            raise HTTPException(status_code=400, detail=f"bad json/form: {exc2}")

    onlinepbx_id = str(payload.get("call_id") or payload.get("id") or "")
    if not onlinepbx_id:
        raise HTTPException(status_code=400, detail="missing call_id")

    started_raw = payload.get("start") or payload.get("start_time")
    started_at = (
        datetime.fromtimestamp(int(started_raw), tz=timezone.utc)
        if isinstance(started_raw, (int, float))
        else datetime.now(tz=timezone.utc)
    )

    existing = (
        db.query(ManagerCall)
        .filter(ManagerCall.onlinepbx_id == onlinepbx_id)
        .one_or_none()
    )
    if existing:
        return {"status": "duplicate", "id": existing.id}

    call = ManagerCall(
        onlinepbx_id=onlinepbx_id,
        phone=payload.get("phone") or payload.get("from"),
        direction=payload.get("direction", "inbound"),
        started_at=started_at,
        duration_s=int(payload.get("duration", 0) or 0),
        recording_url_remote=payload.get("record_url") or payload.get("recording_url"),
        raw=payload,
    )
    db.add(call)
    db.commit()
    db.refresh(call)
    log.info("manager_call ingested id=%s onlinepbx_id=%s", call.id, onlinepbx_id)

    # Фоном: download → S3 upload → STT → LLM-оценка
    if call.recording_url_remote:
        from call_analytics.pipeline import process_manager_call

        background.add_task(_run_pipeline_safe, call.id)
    return {"status": "accepted", "id": call.id}


async def _run_pipeline_safe(call_id: int) -> None:
    """Обёртка: глотает исключения, чтобы фон не сваливал процесс."""
    from call_analytics.pipeline import process_manager_call

    try:
        await process_manager_call(call_id)
    except Exception:
        log.exception("pipeline failed for call_id=%s", call_id)
