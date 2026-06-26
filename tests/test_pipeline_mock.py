"""End-to-end прогон call_analytics pipeline через FAKE_PROVIDERS.

Не требует OPENAI_API_KEY / ASSEMBLYAI_API_KEY / Cloudinary.
Мокает download_recording (т.к. реальный OnlinePBX не доступен в тесте).
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture
def fake_mode(monkeypatch):
    monkeypatch.setenv("FAKE_PROVIDERS", "true")


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


def test_pipeline_e2e_through_fakes(fake_mode, fixtures_dir, monkeypatch, tmp_path):
    from shared.db import db_session
    from shared.models import CallSummary, ManagerCall, Transcript

    # Мокаем download_recording → возвращает путь к нашему mp3 (используется как audio path).
    # Fake-STT прочитает sample_call.mp3.txt рядом с ним.
    fake_audio = tmp_path / "sample_call.mp3"
    fake_audio.write_bytes(b"\x00")  # пустой файл-плейсхолдер
    sidecar_text = (fixtures_dir / "sample_call.mp3.txt").read_text(encoding="utf-8")
    (Path(str(fake_audio) + ".txt")).write_text(sidecar_text, encoding="utf-8")

    async def _fake_download(self, url):
        return str(fake_audio)

    async def _fake_close(self):
        return None

    from shared import onlinepbx as pbx_mod
    monkeypatch.setattr(pbx_mod.OnlinePbxClient, "download_recording", _fake_download)
    monkeypatch.setattr(pbx_mod.OnlinePbxClient, "aclose", _fake_close)

    # Создаём ManagerCall в БД
    with db_session() as db:
        mc = ManagerCall(
            onlinepbx_id="test-call-001",
            phone="+77001112233",
            direction="inbound",
            started_at=datetime.now(timezone.utc),
            duration_s=120,
            recording_url_remote="https://onlinepbx.example/rec/001.mp3",
        )
        db.add(mc)
        db.flush()
        call_id = mc.id

    # Гоняем pipeline
    from call_analytics.pipeline import process_manager_call
    asyncio.run(process_manager_call(call_id))

    # Проверяем что транскрипт + скоры + summary записались
    with db_session() as db:
        mc = db.get(ManagerCall, call_id)
        assert mc is not None
        assert mc.recording_url_cloudinary, "fake cloudinary URL должен записаться"
        assert mc.recording_url_cloudinary.startswith("file://")

        tx = db.query(Transcript).filter_by(call_id=call_id).one()
        assert "VoiceAgent" in tx.text
        assert tx.provider in ("assemblyai", "whisper")  # fake — провайдер пишет 'assemblyai'
        assert tx.duration_s and tx.duration_s > 0

        summary = db.query(CallSummary).filter_by(call_id=call_id).one()
        assert summary.funnel_stage in ("dialog", "deal", "lost")
        assert summary.total_score is not None
        # Двухтрековые отчёты должны записаться обоими полями
        assert summary.report_for_manager and "Длительность" in summary.report_for_manager
        assert summary.report_for_rop and "Диагностика компетенций" in summary.report_for_rop


def test_fake_llm_scores_higher_for_positive_dialog():
    """Fake LLM-анализ должен давать выше total_score для „да/хорошо/запиши“."""
    from shared.fakes import FakeLlmClient

    async def _go(text: str) -> float:
        c = FakeLlmClient()
        out = await c.analyze_dialog(transcript=text, duration_s=120)
        import json
        return json.loads(out["raw_text"])["total_score"]

    pos = asyncio.run(_go("Да-да, хорошо. Запишите нас. Очень интересно, придём."))
    neg = asyncio.run(_go("Нет, не интересно. Перезвоните потом."))
    assert pos > neg
