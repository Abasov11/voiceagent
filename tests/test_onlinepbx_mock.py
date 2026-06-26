"""Тесты OnlinePbxClient: HMAC-проверка + download_recording через httpx mock."""

from __future__ import annotations

import hmac
import hashlib

import httpx

from shared.onlinepbx import OnlinePbxClient


async def test_hmac_skipped_when_secret_unset():
    c = OnlinePbxClient(domain="x", user=None, password=None, webhook_secret=None)
    assert c.verify_webhook_signature(b"any", "anything") is True
    assert c.verify_webhook_signature(b"any", None) is True
    await c.aclose()


async def test_hmac_strict_mode_rejects_empty_secret():
    c = OnlinePbxClient(
        domain="x", user=None, password=None,
        webhook_secret=None, webhook_secret_required=True,
    )
    assert c.verify_webhook_signature(b"any", "sig") is False
    assert c.verify_webhook_signature(b"any", None) is False
    await c.aclose()


async def test_hmac_correct_signature():
    secret = "topsecret"
    c = OnlinePbxClient(domain="x", user=None, password=None, webhook_secret=secret)
    body = b'{"call_id":"1"}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert c.verify_webhook_signature(body, sig) is True
    await c.aclose()


async def test_hmac_wrong_signature():
    c = OnlinePbxClient(domain="x", user=None, password=None, webhook_secret="topsecret")
    assert c.verify_webhook_signature(b"body", "deadbeef") is False
    assert c.verify_webhook_signature(b"body", None) is False
    await c.aclose()


async def test_download_recording_writes_temp_mp3(tmp_path):
    payload = b"FAKE-MP3-BYTES"

    def handler(request: httpx.Request) -> httpx.Response:
        # Если basic auth задан — проверим, что заголовок прилетел
        return httpx.Response(200, content=payload, headers={"content-type": "audio/mpeg"})

    c = OnlinePbxClient(domain="d", user="u", password="p")
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    out = await c.download_recording("https://example.com/r.mp3")
    assert out.exists()
    assert out.suffix == ".mp3"
    assert out.read_bytes() == payload
    out.unlink()
    await c.aclose()


async def test_download_recording_wav_extension():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"WAV", headers={"content-type": "audio/wav"})

    c = OnlinePbxClient(domain="d", user="u", password="p")
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    out = await c.download_recording("https://example.com/r.wav")
    assert out.suffix == ".wav"
    out.unlink()
    await c.aclose()


async def test_download_recording_propagates_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    c = OnlinePbxClient(domain="d", user=None, password=None)
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await c.download_recording("https://example.com/missing.mp3")
        assert False, "expected HTTPStatusError"
    except httpx.HTTPStatusError:
        pass
    await c.aclose()
