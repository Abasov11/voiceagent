"""ElevenLabs TTS клиент.

Используется AI-звонарём, чтобы отдать аудио для воспроизведения через Voximplant.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


async def synthesize(
    text: str, *, api_key: str | None, voice_id: str | None, model_id: str = "eleven_multilingual_v2"
) -> Path:
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")
    if not voice_id:
        raise RuntimeError("ELEVENLABS_VOICE_ID is not set")
    from elevenlabs.client import ElevenLabs
    import anyio

    client = ElevenLabs(api_key=api_key)

    def _gen() -> bytes:
        audio_iter = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=model_id,
            output_format="mp3_44100_128",
        )
        return b"".join(audio_iter)

    audio = await anyio.to_thread.run_sync(_gen)
    tmp = tempfile.NamedTemporaryFile(prefix="el-", suffix=".mp3", delete=False)
    tmp.write(audio)
    tmp.flush()
    tmp.close()
    log.info("elevenlabs synth: text_len=%d → %s (%d bytes)", len(text), tmp.name, len(audio))
    return Path(tmp.name)
