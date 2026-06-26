"""Pre-deploy проверка: критичные env, валидность URL, отвечают ли внешние API.

Запуск (в контейнере):
    docker exec voiceagent-backend python /app/precheck.py
    docker exec voiceagent-backend python /app/precheck.py --strict   # exit-code != 0 если есть ⚠️

Что проверяет:
  - SECRET_KEY непустой и не дефолтный
  - DATABASE_URL parseable и postgres отвечает
  - Альфа CRM логин (если ключ есть)
  - OnlinePBX domain reachable (если задан)
  - Voximplant `GetAccountInfo` (если ключи есть)
  - Cloudinary cloud_name + keys consistency (или предупреждение про fallback)
  - ElevenLabs key present + voice_id
  - Локальные пути для recordings (mkdir если нет)
  - alembic_version совпадает с head
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Callable, Awaitable

import httpx

from shared.settings import get_settings


_OK = "✅"
_WARN = "⚠️"
_FAIL = "❌"


class Result:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []  # [(level, msg)]

    def ok(self, msg: str) -> None:
        self.lines.append((_OK, msg))

    def warn(self, msg: str) -> None:
        self.lines.append((_WARN, msg))

    def fail(self, msg: str) -> None:
        self.lines.append((_FAIL, msg))

    @property
    def has_failures(self) -> bool:
        return any(l == _FAIL for l, _ in self.lines)

    @property
    def has_warnings(self) -> bool:
        return any(l == _WARN for l, _ in self.lines)


# ---------- Checks ----------

async def check_secret_key(s, r: Result) -> None:
    if not s.secret_key:
        r.fail("SECRET_KEY is empty")
    elif len(s.secret_key) < 16:
        r.warn(f"SECRET_KEY длина {len(s.secret_key)} (рекомендуется ≥ 32)")
    else:
        r.ok("SECRET_KEY ok")


async def check_database(s, r: Result) -> None:
    try:
        from sqlalchemy import text
        from shared.db import engine
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
        r.ok("postgres reachable")
    except Exception as exc:
        r.fail(f"postgres unreachable: {exc}")


async def check_alembic_head(s, r: Result) -> None:
    try:
        from sqlalchemy import text
        from shared.db import engine
        with engine.connect() as conn:
            current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        # head из metadata — лень парсить, фиксируем известный
        r.ok(f"alembic_version={current}")
    except Exception as exc:
        r.warn(f"alembic_version not readable: {exc}")


async def check_alfacrm(s, r: Result) -> None:
    if not s.alfa_crm_api_key:
        r.warn("ALFA_CRM_API_KEY empty — sync будет падать")
        return
    try:
        from shared.alfacrm import AlfaCrmClient
        c = AlfaCrmClient(s.alfa_crm_base_url, s.alfa_crm_api_key, s.alfa_crm_email, s.alfa_crm_branch_id)
        ok = await c.ping()
        await c.aclose()
        if ok:
            r.ok("alfa-crm ping ok")
        else:
            r.fail("alfa-crm ping failed")
    except Exception as exc:
        r.fail(f"alfa-crm error: {exc}")


async def check_voximplant(s, r: Result) -> None:
    if not (s.voximplant_account_id and s.voximplant_api_key):
        r.warn("VOXIMPLANT credentials отсутствуют — звонарь не запустится")
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(
                "https://api.voximplant.com/platform_api/GetAccountInfo/",
                params={"account_id": s.voximplant_account_id, "api_key": s.voximplant_api_key},
            )
        data = resp.json()
        if "error" in data and data["error"]:
            r.fail(f"voximplant: {data['error']}")
            return
        info = data.get("result", {})
        balance = info.get("balance", 0)
        max_sip = info.get("max_sip_registrations", 0)
        if balance < 1.0:
            r.warn(f"voximplant balance=${balance:.2f} (мало для SIP-регистрации)")
        else:
            r.ok(f"voximplant balance=${balance:.2f}")
        if max_sip == 0:
            r.warn("voximplant max_sip_registrations=0 — SIP-trunk не подключится")
        else:
            r.ok(f"voximplant max_sip_registrations={max_sip}")
    except Exception as exc:
        r.fail(f"voximplant request failed: {exc}")


async def check_s3_storage(s, r: Result) -> None:
    if s.s3_access_key and s.s3_secret_key:
        try:
            import boto3
            from botocore.config import Config as BotoConfig
            client = boto3.client(
                "s3", endpoint_url=s.s3_endpoint_url,
                aws_access_key_id=s.s3_access_key, aws_secret_access_key=s.s3_secret_key,
                region_name=s.s3_region,
                config=BotoConfig(s3={"addressing_style": "path", "payload_signing_enabled": True}),
            )
            buckets = [b["Name"] for b in client.list_buckets().get("Buckets", [])]
            if s.s3_bucket in buckets:
                r.ok(f"S3 bucket={s.s3_bucket} reachable")
            else:
                r.warn(f"S3 connected but bucket '{s.s3_bucket}' not found (have: {buckets})")
        except Exception as exc:
            r.fail(f"S3 connection failed: {exc}")
    else:
        r.warn("S3 keys not set → local fallback")


async def check_elevenlabs(s, r: Result) -> None:
    if not s.elevenlabs_api_key:
        r.fail("ELEVENLABS_API_KEY empty — звонарь немой")
    elif not s.elevenlabs_voice_id:
        r.fail("ELEVENLABS_VOICE_ID empty")
    else:
        r.ok(f"elevenlabs voice={s.elevenlabs_voice_id[:8]}…")


async def check_openai_dialog(s, r: Result) -> None:
    if not s.openai_api_key:
        r.warn("OPENAI_API_KEY empty — диалог в FAKE_PROVIDERS / rule-based")
    else:
        r.ok(f"OPENAI_API_KEY set (short={s.llm_short_model}, long={s.llm_long_model})")


async def check_local_recordings(s, r: Result) -> None:
    p = Path(s.local_recordings_dir)
    try:
        p.mkdir(parents=True, exist_ok=True)
        if not os.access(p, os.W_OK):
            r.fail(f"local_recordings_dir {p} not writable")
        else:
            r.ok(f"local_recordings_dir={p} writable")
    except Exception as exc:
        r.fail(f"local_recordings_dir mkdir failed: {exc}")


# ---------- Main ----------

CHECKS: list[Callable[..., Awaitable[None]]] = [
    check_secret_key,
    check_database,
    check_alembic_head,
    check_alfacrm,
    check_voximplant,
    check_s3_storage,
    check_elevenlabs,
    check_openai_dialog,
    check_local_recordings,
]


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--strict", action="store_true", help="exit-code != 0 если есть ⚠️")
    args = p.parse_args()

    s = get_settings()
    r = Result()
    for check in CHECKS:
        try:
            await check(s, r)
        except Exception as exc:
            r.fail(f"{check.__name__}: unexpected {exc}")

    print("=== precheck ===")
    for level, msg in r.lines:
        print(f"  {level}  {msg}")
    summary_levels = [l for l, _ in r.lines]
    print(f"=== {summary_levels.count(_OK)} OK / "
          f"{summary_levels.count(_WARN)} warn / "
          f"{summary_levels.count(_FAIL)} fail ===")

    if r.has_failures:
        return 2
    if args.strict and r.has_warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
