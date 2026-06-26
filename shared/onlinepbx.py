"""OnlinePBX клиент: скачивание записей звонков.

Webhook от OnlinePBX отдаёт нам:
- call_id
- ext (внутренний номер менеджера)
- phone (внешний номер)
- start, duration
- record_url (HTTP(S) ссылка с basic-auth) или путь, который надо склеить с domain

Эта обёртка занимается:
- скачиванием бинарника записи в /tmp
- проверкой (опционально) HMAC подписи входящего webhook
"""
from __future__ import annotations

import hmac
import hashlib
import logging
import tempfile
from pathlib import Path

import httpx

log = logging.getLogger(__name__)


class OnlinePbxClient:
    def __init__(
        self,
        domain: str,
        user: str | None,
        password: str | None,
        webhook_secret: str | None = None,
        webhook_secret_required: bool = False,
        timeout: float = 60.0,
    ) -> None:
        self.domain = domain
        self.user = user
        self.password = password
        self.webhook_secret = webhook_secret
        self.webhook_secret_required = webhook_secret_required
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    def verify_webhook_signature(self, raw_body: bytes, signature_header: str | None) -> bool:
        if not self.webhook_secret:
            if self.webhook_secret_required:
                # strict-mode: пустой секрет — это ошибка конфигурации
                log.error("onlinepbx webhook_secret is empty BUT *_REQUIRED=1 → reject")
                return False
            # legacy/dev режим: пропускаем
            log.warning("onlinepbx webhook_secret is not set — skipping signature check")
            return True
        if not signature_header:
            return False
        expected = hmac.new(
            self.webhook_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    async def download_recording(self, record_url: str) -> Path:
        auth = (self.user, self.password) if self.user and self.password else None
        r = await self._client.get(record_url, auth=auth)
        r.raise_for_status()
        # Определим расширение из content-type / url
        ext = ".mp3"
        if "wav" in (r.headers.get("content-type") or "") or record_url.endswith(".wav"):
            ext = ".wav"
        tmp = tempfile.NamedTemporaryFile(prefix="opbx-", suffix=ext, delete=False)
        tmp.write(r.content)
        tmp.flush()
        tmp.close()
        log.info("downloaded recording %s → %s (%d bytes)", record_url, tmp.name, len(r.content))
        return Path(tmp.name)
