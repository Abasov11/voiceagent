"""Фейковые провайдеры внешних сервисов для dev-прогонов без API ключей.

Активация: env `FAKE_PROVIDERS=true` (читает is_fake_mode()).

Заменяют:
  - STT (AssemblyAI/Whisper)  → читают .txt рядом с аудио, либо отдают синтетический
  - S3 upload                 → возвращают локальный file:// URL
  - LLM (OpenAI)              → возвращают детерминированный JSON-скоринг
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from shared.stt import TranscriptResult

log = logging.getLogger(__name__)


def is_fake_mode() -> bool:
    return os.getenv("FAKE_PROVIDERS", "").lower() in {"1", "true", "yes"}


# ---------- STT ----------

async def fake_transcribe(path: Path, *, language: str = "ru") -> TranscriptResult:
    """Если рядом с аудио есть .txt — берём его. Иначе синтетический транскрипт."""
    txt_candidate = Path(str(path) + ".txt")
    if txt_candidate.exists():
        text = txt_candidate.read_text(encoding="utf-8").strip()
    else:
        text = (
            "— Здравствуйте! Это VoiceAgent, школа детского футбола. "
            "Скажите, рассматриваете ли тренировки для ребёнка?\n"
            "— Да, нам было бы интересно. Сколько стоит и куда подойти?\n"
            "— Абонемент тридцать тысяч в месяц, первая тренировка бесплатная. "
            "Я могу записать на пробную, удобно завтра в семнадцать ноль-ноль?\n"
            "— Хорошо, давайте."
        )
    duration_s = max(30, len(text) // 8)
    return TranscriptResult(
        provider="assemblyai",
        text=text,
        lang=language,
        duration_s=duration_s,
        cost_cents=1,
        raw={"fake": True, "source": str(txt_candidate) if txt_candidate.exists() else "synthetic"},
    )


# ---------- S3 Storage ----------

def fake_upload_recording(local_path: Path, onlinepbx_id: str, when=None) -> dict[str, Any]:
    return {
        "secure_url": f"file://{local_path}",
        "public_id": f"manager-calls/fake/{onlinepbx_id}",
        "fake": True,
    }


# ---------- LLM ----------

class FakeLlmClient:
    """Возвращает детерминированный JSON-скоринг — для e2e тестов pipeline."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.short_model = "fake-haiku"
        self.long_model = "fake-sonnet"

    @staticmethod
    def _heuristic(transcript: str) -> tuple[float, str]:
        """Простая эвристика: позитивные слова → выше total_score; → funnel_stage."""
        positive_markers = sum(transcript.lower().count(w) for w in ("да", "хорошо", "запиш", "интересн", "приду"))
        negative_markers = sum(transcript.lower().count(w) for w in ("нет", "не интересно", "перезвон"))
        base = min(8.5, 4.0 + positive_markers * 0.6 - negative_markers * 0.4)
        funnel_stage = "deal" if base >= 6.0 else "dialog" if base >= 4.5 else "lost"
        return round(base, 2), funnel_stage

    async def score_dialog(
        self,
        *,
        transcript: str,
        criteria: list[str],
        tier: str = "short",
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """Legacy режим — числовые баллы по критериям. Оставлен для тестов backfill."""
        base, funnel_stage = self._heuristic(transcript)
        items = [
            {"criterion": c, "score": round(min(10.0, base + (i % 3) * 0.5), 1), "comment": "fake"}
            for i, c in enumerate(criteria)
        ]
        payload = {"items": items, "total_score": base, "funnel_stage": funnel_stage}
        return {
            "model": self.short_model if tier == "short" else self.long_model,
            "raw_text": json.dumps(payload, ensure_ascii=False),
            "usage": {"input_tokens": len(transcript) // 4, "output_tokens": 200, "fake": True},
        }

    async def analyze_dialog(
        self,
        *,
        transcript: str,
        duration_s: int | None,
        tier: str = "short",
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Фейковый двухтрековый коучинговый анализ — детерминированный текст для тестов."""
        base, funnel_stage = self._heuristic(transcript)
        for_manager = (
            "Ключевая информация о звонке:\n"
            f"- Длительность: {(duration_s or 0) // 60}:{(duration_s or 0) % 60:02d}\n"
            "- Соотношение речи (Менеджер/Клиент): 55/45\n\n"
            "Основная цель клиента в этом звонке:\n"
            "- Родитель интересуется тренировками для ребёнка (fake).\n\n"
            "Разбор ключевых моментов диалога:\n"
            "- Момент 1: Установление контакта (fake-анализ)\n\n"
            "Идеи для усиления на будущее:\n"
            "- Управление диалогом: больше открытых вопросов (fake)."
        )
        for_rop = (
            "Общая информация:\n"
            f"- Исход звонка: {'Запись на пробную' if funnel_stage == 'deal' else 'Думает' if funnel_stage == 'dialog' else 'Отказ'}\n\n"
            "Диагностика компетенций менеджера:\n"
            "- Квалификация клиента: норма (fake)\n"
            "- Презентация продукта: норма (fake)\n\n"
            "Ключевые инсайты по клиенту: возраст ребёнка не выявлен (fake).\n\n"
            "Сигналы для руководителя:\n"
            "- Сигнал 1 (Обучение): дополнительный тренинг по работе с возражениями (fake)."
        )
        payload = {
            "for_manager": for_manager,
            "for_rop": for_rop,
            "total_score": base,
            "funnel_stage": funnel_stage,
        }
        return {
            "model": self.short_model if tier == "short" else self.long_model,
            "raw_text": json.dumps(payload, ensure_ascii=False),
            "usage": {"input_tokens": len(transcript) // 4, "output_tokens": 800, "fake": True},
        }
