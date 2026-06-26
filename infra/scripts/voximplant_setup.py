"""Идемпотентный setup Voximplant Application + Scenario + Rule + (best-effort) SIP Registration.

Запуск (внутри контейнера):
    docker exec voiceagent-backend python -m infra.scripts.voximplant_setup

Использует:
    VOXIMPLANT_ACCOUNT_ID  — числовой ID аккаунта
    VOXIMPLANT_API_KEY     — UUID, обычный legacy api_key
    DASHBOARD_BASE_URL     — http://203.0.113.10 (или https://voiceagent.example.com)
    SECRET_KEY             — токен для X-Token в /zvonar/dialogue/turn

Источники:
    https://voximplant.com/docs/references/httpapi/applications
    https://voximplant.com/docs/references/httpapi/scenarios
    https://voximplant.com/docs/references/httpapi/rules
    https://voximplant.com/docs/references/httpapi/sip-registrations
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx

from shared.settings import get_settings

log = logging.getLogger("voximplant_setup")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

API = "https://api.voximplant.com/platform_api"

APP_NAME = "voiceagent-zvonar"
SCENARIO_NAME = "voiceagent-outbound"
RULE_NAME = "outbound-rule"
SIP_REG_NAME = "sip_provider-almaty-main"

# SIP-оператор SIP — primary account из письма (photo_25 от 2026-04-30)
SIP_PROVIDER_PROXY = "almpbx.example.com"
SIP_PROVIDER_LOGIN = "sip_login_1"
SIP_PROVIDER_PASSWORD = "sip_password"


def _scenario_path() -> Path:
    """В контейнере код смонтирован в /app — пробуем сначала контейнерный путь."""
    candidates = [
        Path("/app/zvonar/voxengine_scenario.js"),
        Path(__file__).resolve().parent.parent.parent / "zvonar" / "voxengine_scenario.js",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"voxengine_scenario.js not found, tried: {candidates}")


def _prepare_scenario_text(backend_url: str, shared_token: str) -> str:
    raw = _scenario_path().read_text(encoding="utf-8")
    return (
        raw.replace('const BACKEND_URL = "https://CHANGE_ME";',
                    f'const BACKEND_URL = "{backend_url}";')
           .replace('const SHARED_TOKEN = "CHANGE_ME";',
                    f'const SHARED_TOKEN = "{shared_token}";')
    )


class Vox:
    def __init__(self, account_id: str, api_key: str) -> None:
        self.account_id = account_id
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=30)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(self, op: str, **params) -> dict:
        params.setdefault("account_id", self.account_id)
        params.setdefault("api_key", self.api_key)
        # Большие поля (scenario_script) в form-data, иначе в query
        big = any(isinstance(v, str) and len(v) > 1500 for v in params.values())
        if big:
            r = await self._client.post(f"{API}/{op}/", data=params)
        else:
            r = await self._client.get(f"{API}/{op}/", params=params)
        try:
            data = r.json()
        except Exception:
            data = {"http_text": r.text}
        if "error" in data and data["error"]:
            log.warning("vox.%s error: %s", op, data["error"])
        return data

    # ---------- Application ----------
    async def get_or_create_app(self, name: str) -> int:
        existing = await self._call("GetApplications", application_name=name)
        for it in existing.get("result", []) or []:
            if it.get("application_name") == name:
                log.info("application '%s' exists: id=%s", name, it["application_id"])
                return int(it["application_id"])
        added = await self._call("AddApplication", application_name=name)
        if "application_id" not in added:
            raise RuntimeError(f"AddApplication failed: {added}")
        log.info("application '%s' created: id=%s", name, added["application_id"])
        return int(added["application_id"])

    # ---------- Scenario ----------
    async def get_or_create_scenario(self, name: str, script_text: str) -> int:
        existing = await self._call("GetScenarios", scenario_name=name)
        for it in existing.get("result", []) or []:
            if it.get("scenario_name") == name:
                log.info("scenario '%s' exists: id=%s — обновляю текст", name, it["scenario_id"])
                upd = await self._call(
                    "SetScenarioInfo",
                    scenario_id=it["scenario_id"],
                    scenario_script=script_text,
                )
                if "result" not in upd:
                    raise RuntimeError(f"SetScenarioInfo failed: {upd}")
                return int(it["scenario_id"])
        added = await self._call(
            "AddScenario", scenario_name=name, scenario_script=script_text
        )
        if "scenario_id" not in added:
            raise RuntimeError(f"AddScenario failed: {added}")
        log.info("scenario '%s' created: id=%s", name, added["scenario_id"])
        return int(added["scenario_id"])

    # ---------- Rule ----------
    async def get_or_create_rule(self, app_id: int, name: str, scenario_id: int) -> int:
        existing = await self._call("GetRules", application_id=app_id, rule_name=name)
        for it in existing.get("result", []) or []:
            if it.get("rule_name") == name:
                log.info("rule '%s' exists: id=%s — переподключаю scenario", name, it["rule_id"])
                upd = await self._call(
                    "SetRuleInfo",
                    rule_id=it["rule_id"],
                    scenario_id=str(scenario_id),
                )
                return int(it["rule_id"])
        added = await self._call(
            "AddRule",
            application_id=app_id,
            rule_name=name,
            rule_pattern=".*",
            scenario_id=str(scenario_id),
        )
        if "rule_id" not in added:
            raise RuntimeError(f"AddRule failed: {added}")
        log.info("rule '%s' created: id=%s", name, added["rule_id"])
        return int(added["rule_id"])

    # ---------- SIP Registration (best-effort) ----------
    async def try_create_sip_registration(self, name: str) -> dict:
        return await self._call(
            "CreateSipRegistration",
            sip_username=SIP_PROVIDER_LOGIN,
            proxy=SIP_PROVIDER_PROXY,
            outbound_proxy=SIP_PROVIDER_PROXY,
            auth_user=SIP_PROVIDER_LOGIN,
            password=SIP_PROVIDER_PASSWORD,
            is_persistent=True,
            # Имя для удобства (поле необязательно, но удобно):
            registration_name=name,
        )


async def main() -> int:
    s = get_settings()
    if not s.voximplant_account_id or not s.voximplant_api_key:
        log.error("VOXIMPLANT_ACCOUNT_ID / VOXIMPLANT_API_KEY not set in env")
        return 2

    backend_url = s.dashboard_base_url.rstrip("/")
    shared_token = s.secret_key
    script_text = _prepare_scenario_text(backend_url, shared_token)
    log.info("scenario length: %d chars", len(script_text))

    v = Vox(s.voximplant_account_id, s.voximplant_api_key)
    try:
        app_id = await v.get_or_create_app(APP_NAME)
        sc_id = await v.get_or_create_scenario(SCENARIO_NAME, script_text)
        rule_id = await v.get_or_create_rule(app_id, RULE_NAME, sc_id)

        log.info("=== READY: app_id=%s scenario_id=%s rule_id=%s",
                 app_id, sc_id, rule_id)

        # Best-effort SIP Registration (может упасть если лимит = 0)
        sip = await v.try_create_sip_registration(SIP_REG_NAME)
        log.info("sip_reg result: %s", json.dumps(sip, ensure_ascii=False)[:600])

        out = {
            "VOXIMPLANT_APPLICATION_ID": app_id,
            "VOXIMPLANT_SCENARIO_ID":   sc_id,
            "VOXIMPLANT_RULE_ID":       rule_id,
            "sip_registration":         sip.get("result") or sip.get("error"),
        }
        print("\nRESULT:\n" + json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    finally:
        await v.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
