"""Pipeline: download → S3 upload → STT → LLM-анализ → запись в БД.

Запускается фоном после получения webhook (или ретроспективно из CLI).
LLM-анализ — двухтрековый коучинговый отчёт (ФВР/STAR/GROW) через
`LlmClient.analyze_dialog`, отчёты пишутся в CallSummary.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from typing import Any

from shared.storage_client import configure_s3, upload_recording, upload_recording_local
from shared.cost_calculator import for_manager_call as compute_manager_cost
from shared.db import db_session
from shared.fakes import FakeLlmClient, fake_transcribe, fake_upload_recording, is_fake_mode
from shared.llm import LlmClient, pick_tier
from shared.models import (
    ApiCallLog,
    CallCostBreakdown,
    CallSummary,
    ManagerCall,
    Transcript,
)
from shared.onlinepbx import OnlinePbxClient
from shared.settings import get_settings
from shared.stt import transcribe

log = logging.getLogger(__name__)


async def process_manager_call(call_id: int) -> None:
    s = get_settings()
    if s.s3_access_key and s.s3_secret_key:
        configure_s3(s.s3_endpoint_url, s.s3_access_key, s.s3_secret_key, s.s3_region)

    with db_session() as db:
        call: ManagerCall | None = db.get(ManagerCall, call_id)
        if not call:
            log.error("call %s not found", call_id)
            return
        recording_url = call.recording_url_remote
        if not recording_url:
            log.warning("call %s has no recording_url", call_id)
            return

        pbx = OnlinePbxClient(
            domain=s.onlinepbx_domain or "",
            user=s.onlinepbx_user,
            password=s.onlinepbx_password,
        )
        local_path = await pbx.download_recording(recording_url)
        await pbx.aclose()

        fake = is_fake_mode()
        if fake:
            up = fake_upload_recording(local_path, call.onlinepbx_id, call.started_at)
            call.recording_url_cloudinary = up.get("secure_url")
            db.add(call)
            db.flush()
        elif s.s3_access_key:
            up = upload_recording(local_path, call.onlinepbx_id, call.started_at, bucket=s.s3_bucket)
            call.recording_url_cloudinary = up.get("secure_url")
            db.add(call)
            db.flush()
        else:
            up = upload_recording_local(
                local_path, call.onlinepbx_id, call.started_at,
                base_dir=s.local_recordings_dir,
                url_prefix=s.local_recordings_url_prefix,
            )
            call.recording_url_cloudinary = up.get("secure_url")
            db.add(call)
            db.flush()

        if fake:
            stt = await fake_transcribe(local_path, language="ru")
        else:
            stt = await transcribe(
                local_path,
                assemblyai_key=s.assemblyai_api_key,
                openai_key=s.openai_api_key,
                language="ru",
            )
        tx = Transcript(
            call_id=call.id,
            provider=stt.provider,
            text=stt.text,
            lang=stt.lang,
            duration_s=stt.duration_s,
            cost_cents=stt.cost_cents,
            raw=stt.raw,
        )
        db.add(tx)
        db.add(ApiCallLog(
            provider=stt.provider,
            operation="transcribe",
            duration_ms=None,
            cost_cents=stt.cost_cents,
            status="ok",
            request={"call_id": call.id, "fake": fake},
        ))
        db.flush()

        if fake or s.openai_api_key:
            llm: Any
            if fake:
                llm = FakeLlmClient()
            else:
                llm = LlmClient(
                    openai_api_key=s.openai_api_key,
                    short_model=s.llm_short_model,
                    long_model=s.llm_long_model,
                )
            tier = pick_tier(stt.duration_s)
            try:
                analysis = await llm.analyze_dialog(
                    transcript=stt.text, duration_s=stt.duration_s, tier=tier
                )
            except Exception as exc:
                log.error("LLM analyze_dialog failed: %s", exc)
                db.add(ApiCallLog(
                    provider="openai",
                    operation="analyze_dialog",
                    status="error",
                    error=str(exc)[:2048],
                    request={"call_id": call.id, "tier": tier},
                ))
                db.flush()
                analysis = None
                parsed = None
            else:
                # цена: ~$0.002/short; ~$0.012/long запрос (грубая оценка,
                # двухтрековый отчёт длиннее legacy score_dialog)
                cost_cents = 2 if tier == "short" else 12
                db.add(ApiCallLog(
                    provider="openai",
                    operation="analyze_dialog",
                    cost_cents=cost_cents,
                    status="ok",
                    request={"call_id": call.id, "tier": tier, "model": analysis["model"]},
                    response={"usage": analysis.get("usage")},
                ))
                try:
                    parsed = json.loads(analysis["raw_text"])
                except Exception as exc:
                    log.warning("LLM analyze JSON parse failed: %s", exc)
                    parsed = None

            if parsed:
                total_score = parsed.get("total_score")
                db.add(
                    CallSummary(
                        call_id=call.id,
                        total_score=float(total_score) if total_score is not None else None,
                        funnel_stage=str(parsed.get("funnel_stage") or "")[:32] or None,
                        summary=analysis["raw_text"][:4000],
                        report_for_manager=parsed.get("for_manager") or None,
                        report_for_rop=parsed.get("for_rop") or None,
                    )
                )

        breakdown = compute_manager_cost(
            duration_s=call.duration_s or stt.duration_s or 0,
            stt_cost_cents=stt.cost_cents,
            llm_cost_cents=(1 if pick_tier(stt.duration_s) == "short" else 5)
                if (fake or s.openai_api_key) else 0,
        )
        db.add(CallCostBreakdown(
            manager_call_id=call.id,
            zvonar_call_id=None,
            sip_seconds=call.duration_s or stt.duration_s or 0,
            tts_seconds=0,
            stt_seconds=stt.duration_s or 0,
            llm_input_tokens=0,
            llm_output_tokens=0,
            sip_cost_cents=breakdown.sip_cost_cents,
            tts_cost_cents=breakdown.tts_cost_cents,
            stt_cost_cents=breakdown.stt_cost_cents,
            llm_cost_cents=breakdown.llm_cost_cents,
            total_cost_cents=breakdown.total_cost_cents,
            provider_notes={"fake": fake, "stt_provider": stt.provider},
        ))
        db.flush()

        try:
            Path(local_path).unlink(missing_ok=True)
        except Exception:
            pass
        log.info("processed manager_call %s (provider=%s)", call.id, stt.provider)
