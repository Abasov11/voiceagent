"""push outcome звонаря в карточку лида Альфа CRM.

Поведение:
  - выключено по умолчанию (`alfa_crm_push_outcome=False`)
  - включается env-toggle `ALFA_CRM_PUSH_OUTCOME=1`
  - маппинг outcome → status_id берётся из `ALFA_CRM_OUTCOME_STATUS_JSON`
    (формат: {"interested":12,"callback":7,"not_interested":15,"no_answer":3})
  - всегда добавляет заметку `note` с outcome и timestamp
  - если status_id задан — обновляет lead_status_id

Если у лида нет `alfa_crm_id` (лид загружен из CSV, не из Альфа CRM) — push пропускается.
Если push выключен или нет ключа — функция возвращает `{"skipped": ...}` без ошибки.

Тесты подменяют `_make_alfacrm_client` через monkeypatch.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from shared.alfacrm import AlfaCrmClient
from shared.db import db_session
from shared.models import Lead, ZvonarCall
from shared.settings import get_settings

log = logging.getLogger(__name__)


def _outcome_status_map() -> dict[str, int]:
    raw = get_settings().alfa_crm_outcome_status_json
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("ALFA_CRM_OUTCOME_STATUS_JSON is not valid JSON; ignoring")
        return {}
    return {str(k): int(v) for k, v in data.items() if isinstance(v, (int, str))}


def _make_alfacrm_client() -> AlfaCrmClient:
    """Hook для тестов — monkeypatch на этой функции инжектит мок-клиент."""
    s = get_settings()
    return AlfaCrmClient(
        base_url=s.alfa_crm_base_url,
        api_key=s.alfa_crm_api_key,
        email=s.alfa_crm_email,
        branch_id=s.alfa_crm_branch_id,
    )


async def push_outcome(zvonar_call_id: int) -> dict[str, Any]:
    s = get_settings()
    if not s.alfa_crm_push_outcome:
        return {"skipped": "push_disabled"}
    if not s.alfa_crm_api_key:
        return {"skipped": "no_credentials"}

    with db_session() as db:
        z = db.get(ZvonarCall, zvonar_call_id)
        if not z:
            return {"skipped": "zvonar_call_not_found", "id": zvonar_call_id}
        lead = db.get(Lead, z.lead_id)
        if not lead:
            return {"skipped": "lead_not_found", "lead_id": z.lead_id}
        if not lead.alfa_crm_id:
            return {"skipped": "lead_has_no_alfa_crm_id", "lead_id": lead.id}
        # Извлекаем все нужные поля ДО выхода из сессии (instance detach).
        lead_db_id = lead.id
        outcome = z.outcome
        started_at = z.started_at
        alfa_crm_id = lead.alfa_crm_id

    status_id = _outcome_status_map().get(outcome)
    note = (
        f"AI-звонарь {started_at:%Y-%m-%d %H:%M UTC}: outcome={outcome}"
        + (f", status_id={status_id}" if status_id else "")
    )

    client = _make_alfacrm_client()
    try:
        payload: dict[str, Any] = {"note": note}
        if status_id is not None:
            payload["lead_status_id"] = status_id
        result = await client._request(
            "POST",
            f"/v2api/{client.branch_id}/customer/update?id={alfa_crm_id}",
            json=payload,
        )
        log.info(
            "alfacrm_push lead=%s alfa_crm_id=%s outcome=%s status_id=%s",
            lead_db_id, alfa_crm_id, outcome, status_id,
        )
        return {"ok": True, "outcome": outcome, "status_id": status_id, "alfa_crm_id": alfa_crm_id, "result": result}
    except Exception as exc:
        log.error("alfacrm_push failed for zvonar_call=%s: %s", zvonar_call_id, exc)
        return {"error": str(exc)[:512], "outcome": outcome, "alfa_crm_id": alfa_crm_id}
    finally:
        await client.aclose()
