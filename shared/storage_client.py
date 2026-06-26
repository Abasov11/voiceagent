"""S3-совместимое хранилище записей (PS.kz Object Storage).

Структура: manager-calls/YYYY-MM-DD/{onlinepbx_id}.{ext}

Local fallback: если S3-ключи не заданы — копирует в LOCAL_RECORDINGS_DIR.
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

log = logging.getLogger(__name__)

_s3_client = None


def configure_s3(
    endpoint_url: str,
    access_key: str,
    secret_key: str,
    region: str = "us-east-1",
) -> None:
    global _s3_client
    _s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(
            s3={"addressing_style": "path", "payload_signing_enabled": True},
        ),
    )


def get_s3_client():
    if _s3_client is None:
        raise RuntimeError("S3 not configured — call configure_s3() first")
    return _s3_client


def upload_recording(
    local_path: Path,
    onlinepbx_id: str,
    when: datetime | None = None,
    *,
    bucket: str = "voiceagent-recordings",
) -> dict[str, Any]:
    when = when or datetime.utcnow()
    day = when.strftime("%Y-%m-%d")
    ext = local_path.suffix or ".mp3"
    key = f"manager-calls/{day}/{onlinepbx_id}{ext}"

    s3 = get_s3_client()
    data = local_path.read_bytes()
    content_type = "audio/mpeg" if ext in (".mp3",) else "application/octet-stream"

    log.info("s3 upload: %s → %s/%s (%d bytes)", local_path, bucket, key, len(data))
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

    url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=7 * 86400
    )
    return {"secure_url": url, "public_id": key, "bucket": bucket}


def upload_recording_local(
    local_path: Path,
    onlinepbx_id: str,
    when: datetime | None = None,
    *,
    base_dir: str,
    url_prefix: str,
) -> dict[str, Any]:
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
    return {"secure_url": url, "public_id": f"manager-calls/{day}/{onlinepbx_id}", "local": True, "path": str(target)}
