"""Cloudinary upload — записи менеджерских звонков.

Структура хранения (Cloudinary): manager-calls/YYYY-MM-DD/{onlinepbx_id}.{ext}

Local fallback (когда Cloudinary keys не заданы):
  - копирует файл в `LOCAL_RECORDINGS_DIR/YYYY-MM-DD/{onlinepbx_id}{ext}`
  - возвращает URL формата `{LOCAL_RECORDINGS_URL_PREFIX}/YYYY-MM-DD/{onlinepbx_id}{ext}`

Назначение fallback'а — позволить pipeline нормально работать пока клиент не пришлёт
Cloudinary API Key+Secret. Записи лежат на VPS, доступны под basic-auth (см. nginx конф).
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import cloudinary
import cloudinary.uploader

log = logging.getLogger(__name__)


def configure_cloudinary(cloud_name: str, api_key: str, api_secret: str) -> None:
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )


def upload_recording(local_path: Path, onlinepbx_id: str, when: datetime | None = None) -> dict[str, Any]:
    when = when or datetime.utcnow()
    folder = f"manager-calls/{when.strftime('%Y-%m-%d')}"
    public_id = f"{folder}/{onlinepbx_id}"
    log.info("cloudinary upload: %s → %s", local_path, public_id)
    return cloudinary.uploader.upload(
        str(local_path),
        public_id=public_id,
        resource_type="video",  # для аудио тоже video в Cloudinary
        overwrite=False,
        unique_filename=False,
        use_filename=False,
    )


def upload_recording_local(
    local_path: Path,
    onlinepbx_id: str,
    when: datetime | None = None,
    *,
    base_dir: str,
    url_prefix: str,
) -> dict[str, Any]:
    """Сохраняет файл в локальной директории и возвращает Cloudinary-совместимый dict.

    Структура: {base_dir}/{YYYY-MM-DD}/{onlinepbx_id}{ext}
    URL:       {url_prefix}/{YYYY-MM-DD}/{onlinepbx_id}{ext}
    """
    when = when or datetime.utcnow()
    day = when.strftime("%Y-%m-%d")
    ext = local_path.suffix or ".mp3"
    target_dir = Path(base_dir) / day
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{onlinepbx_id}{ext}"
    if local_path.resolve() != target.resolve():
        shutil.copy2(local_path, target)
    url = f"{url_prefix.rstrip('/')}/{day}/{onlinepbx_id}{ext}"
    log.info("local recording saved: %s → %s", local_path, target)
    return {
        "secure_url": url,
        "public_id": f"manager-calls/{day}/{onlinepbx_id}",
        "local": True,
        "path": str(target),
    }
