"""Speech-to-text роутинг: AssemblyAI primary, OpenAI Whisper fallback."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

Provider = Literal["assemblyai", "whisper"]


@dataclass
class TranscriptResult:
    provider: Provider
    text: str
    lang: str | None
    duration_s: int | None
    cost_cents: int | None
    raw: dict


async def transcribe(
    path: Path,
    *,
    assemblyai_key: str | None,
    openai_key: str | None,
    language: str = "ru",
) -> TranscriptResult:
    """Пытается AssemblyAI; при отсутствии ключа или ошибке — OpenAI Whisper."""
    if assemblyai_key:
        try:
            return await _assemblyai(path, assemblyai_key, language)
        except Exception as exc:
            log.warning("assemblyai failed (%s) → fallback whisper", exc)
    if not openai_key:
        raise RuntimeError("Neither ASSEMBLYAI_API_KEY nor OPENAI_API_KEY is set")
    return await _whisper(path, openai_key, language)


async def _assemblyai(path: Path, key: str, language: str) -> TranscriptResult:
    import assemblyai as aai

    aai.settings.api_key = key
    transcriber = aai.Transcriber()
    config = aai.TranscriptionConfig(language_code=language, speaker_labels=True)
    # SDK синхронный, выполнить в thread-pool
    import anyio

    transcript = await anyio.to_thread.run_sync(
        lambda: transcriber.transcribe(str(path), config=config)
    )
    if transcript.error:
        raise RuntimeError(f"assemblyai error: {transcript.error}")
    duration_s = int((transcript.audio_duration or 0))
    # цена $0.37/час → 1.03 цента/мин ≈ ceil(d/60)*1
    cost_cents = max(1, (duration_s + 59) // 60)
    return TranscriptResult(
        provider="assemblyai",
        text=transcript.text or "",
        lang=language,
        duration_s=duration_s,
        cost_cents=cost_cents,
        raw={"id": transcript.id, "status": str(transcript.status)},
    )


async def _whisper(path: Path, key: str, language: str) -> TranscriptResult:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=key)
    with open(path, "rb") as f:
        resp = await client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language=language,
            response_format="verbose_json",
        )
    text = getattr(resp, "text", "") or ""
    duration_s = int(getattr(resp, "duration", 0) or 0)
    cost_cents = max(1, (duration_s + 59) // 60 * 1)  # ~$0.006/min ≈ 0.6¢
    return TranscriptResult(
        provider="whisper",
        text=text,
        lang=language,
        duration_s=duration_s,
        cost_cents=cost_cents,
        raw={"model": "whisper-1"},
    )
