"""Тесты local fallback для хранения записей."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from shared.storage_client import upload_recording_local


def test_upload_to_local_creates_dated_folder(tmp_path):
    src = tmp_path / "src.mp3"
    src.write_bytes(b"FAKE_MP3")
    base = tmp_path / "recordings"
    when = datetime(2026, 4, 30, 10, 15, tzinfo=timezone.utc)

    res = upload_recording_local(
        src, "call-001", when, base_dir=str(base), url_prefix="/recordings"
    )

    assert res["local"] is True
    assert res["secure_url"] == "/recordings/2026-04-30/call-001.mp3"
    target = base / "2026-04-30" / "call-001.mp3"
    assert target.exists()
    assert target.read_bytes() == b"FAKE_MP3"


def test_upload_local_preserves_extension(tmp_path):
    src = tmp_path / "src.wav"
    src.write_bytes(b"WAV")
    res = upload_recording_local(
        src, "x-2", datetime(2026, 1, 1, tzinfo=timezone.utc),
        base_dir=str(tmp_path / "rec"), url_prefix="/rec",
    )
    assert res["secure_url"].endswith(".wav")


def test_upload_local_idempotent_for_same_target(tmp_path):
    src = tmp_path / "src.mp3"
    src.write_bytes(b"A")
    base = tmp_path / "r"
    when = datetime(2026, 4, 30, tzinfo=timezone.utc)
    upload_recording_local(src, "id", when, base_dir=str(base), url_prefix="/r")
    src.write_bytes(b"BB")
    upload_recording_local(src, "id", when, base_dir=str(base), url_prefix="/r")
    target = base / "2026-04-30" / "id.mp3"
    assert target.read_bytes() == b"BB"


def test_url_prefix_normalized(tmp_path):
    src = tmp_path / "s.mp3"
    src.write_bytes(b"x")
    res = upload_recording_local(
        src, "id", datetime(2026, 1, 1, tzinfo=timezone.utc),
        base_dir=str(tmp_path / "r"), url_prefix="/recordings/",  # trailing slash
    )
    # без двойного слэша
    assert "//" not in res["secure_url"].replace("https://", "").replace("http://", "")
    assert res["secure_url"].startswith("/recordings/")
