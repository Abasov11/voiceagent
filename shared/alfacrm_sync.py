"""Sync лидов из Альфа CRM в нашу БД.

CLI:  docker exec voiceagent-backend python -m shared.alfacrm_sync
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select, or_

from shared.alfacrm import AlfaCrmClient
from shared.db import db_session
from shared.models import Lead, LeadSegment
from shared.settings import get_settings


def normalize_phone(p: str | None) -> str | None:
    if not p:
        return None
    digits = "".join(ch for ch in p if ch.isdigit())
    if not digits:
        return None
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    return "+" + digits

log = logging.getLogger(__name__)


def _phone_of(cust: dict[str, Any]) -> str | None:
    """Альфа CRM хранит phone как list[str] либо string."""
    p = cust.get("phone")
    if isinstance(p, list):
        return p[0] if p else None
    if isinstance(p, str):
        return p or None
    return None


def _segment_of(cust: dict[str, Any]) -> str:
    """Маппинг сегментов клиентов на наш enum.

    Выгрузим всё что есть как unknown — потом, когда увидим реальные данные
    (custom_fields в их CRM), допишем маппинг под `naborki|academy|branch|special`.
    """
    legal_type = cust.get("legal_type")
    if legal_type == 1:
        return LeadSegment.unknown.value
    return LeadSegment.unknown.value


async def sync_all() -> dict[str, int]:
    s = get_settings()
    client = AlfaCrmClient(
        base_url=s.alfa_crm_base_url,
        api_key=s.alfa_crm_api_key,
        email=s.alfa_crm_email,
        branch_id=s.alfa_crm_branch_id,
    )
    inserted = 0
    updated = 0
    skipped = 0
    total = 0
    try:
        async for cust in client.iter_all_customers(page_size=100):
            total += 1
            phone = normalize_phone(_phone_of(cust))
            if not phone:
                skipped += 1
                continue
            alfa_id = str(cust.get("id"))
            name = (cust.get("name") or "")[:256] or None
            status = (cust.get("study_status_name") or "")[:64] or None
            with db_session() as db:
                existing = db.scalar(
                    select(Lead).where(
                        or_(Lead.alfa_crm_id == alfa_id, Lead.phone == phone)
                    )
                )
                if existing:
                    # Если попали по phone, но без alfa_crm_id — заполним
                    if not existing.alfa_crm_id:
                        existing.alfa_crm_id = alfa_id
                    existing.phone = phone
                    existing.name = name or existing.name
                    existing.status = status or existing.status
                    existing.raw = cust
                    updated += 1
                else:
                    db.add(
                        Lead(
                            alfa_crm_id=alfa_id,
                            phone=phone,
                            name=name,
                            segment=_segment_of(cust),
                            status=status,
                            raw=cust,
                        )
                    )
                    inserted += 1
    finally:
        await client.aclose()
    log.info(
        "alfa-crm sync done: total=%d inserted=%d updated=%d skipped=%d",
        total, inserted, updated, skipped,
    )
    return {"total": total, "inserted": inserted, "updated": updated, "skipped": skipped}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    out = asyncio.run(sync_all())
    print(out)


if __name__ == "__main__":
    main()
