"""Тесты ElevenLabs клиента: raise-семантика без ключа/voice_id.

Реальный SDK не мокаем — это интеграционная зависимость, проверяется
вручную через `/voices/` (4 mp3 семпла на VPS клиента).
"""

from __future__ import annotations

import pytest

from shared import elevenlabs_client


async def test_synthesize_raises_without_api_key():
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        await elevenlabs_client.synthesize(
            "Привет", api_key=None, voice_id="any"
        )


async def test_synthesize_raises_without_voice_id():
    with pytest.raises(RuntimeError, match="ELEVENLABS_VOICE_ID"):
        await elevenlabs_client.synthesize(
            "Привет", api_key="sk_xxx", voice_id=None
        )


async def test_synthesize_raises_with_empty_voice():
    with pytest.raises(RuntimeError, match="ELEVENLABS_VOICE_ID"):
        await elevenlabs_client.synthesize(
            "Привет", api_key="sk_xxx", voice_id=""
        )
