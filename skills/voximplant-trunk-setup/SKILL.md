# Skill: voximplant-trunk-setup

**Когда использовать:**
- После пополнения баланса Voximplant (когда `Insufficient funds` пропадёт)
- При падении SIP Registration / `unregistered` статусе
- Когда меняем SIP-логин (например, переключаемся между 3 SIP-оператор аккаунтами)
- После замены креденшелов SIP-trunk (если SIP-оператор пришлёт новые)

## Pre-check

```bash
# Тест что `.env` не пустой
ssh -i ~/.ssh/voiceagent_ed25519 root@203.0.113.10 \
  'grep -E "^VOXIMPLANT_(ACCOUNT_ID|API_KEY)=" /opt/voiceagent/.env | sed -E "s/=(.+)/=<set>/"'
```

Должно показать оба значения. Если пусто — см. `docs/VOXIMPLANT_SETUP.md` § «Pre-check».

## Запуск

```bash
# 1) Скопировать setup-скрипт внутрь контейнера
scp -i ~/.ssh/voiceagent_ed25519 \
    /opt/voiceagent/infra/scripts/voximplant_setup.py \
    root@203.0.113.10:/tmp/voximplant_setup.py

ssh -i ~/.ssh/voiceagent_ed25519 root@203.0.113.10 \
  'docker cp /tmp/voximplant_setup.py voiceagent-backend:/app/voximplant_setup.py && \
   docker exec voiceagent-backend python /app/voximplant_setup.py'
```

## Что делает скрипт

1. Идемпотентно создаёт **Application** `voiceagent-zvonar` (если уже есть — берёт существующий).
2. Идемпотентно создаёт **Scenario** `voiceagent-outbound` (с подставленным `BACKEND_URL` + `SHARED_TOKEN`); существующий обновляется через `SetScenarioInfo`.
3. Идемпотентно создаёт **Rule** `outbound-rule` с pattern `.*`, привязанной к scenario.
4. **Best-effort SIP Registration** на `almpbx.example.com` с логином `sip_login_1`. Если баланс < $5 — Voximplant вернёт `code 127 Insufficient funds`, и SIP не зарегистрируется. Application/Scenario/Rule при этом создаются нормально.

## Ожидаемый ответ

```
=== READY: app_id=11127802 scenario_id=915856 rule_id=1510371
sip_reg result: {"result": {"sip_registration_id": ...}, ...}
```

Если sip_reg упал на `Insufficient funds` — попросите Бекзата/Аскара пополнить баланс
Voximplant минимум на $10 и повторите запуск.

## После успешной SIP Registration

1. Проверьте статус в Voximplant Console → SIP Registrations → должно быть **Registered**.
2. Если `Unregistered` — наш Voximplant signaling-IP не в whitelist SIP-оператор.
   Передайте Voximplant signaling-IP менеджеру SIP-оператора для whitelist.
3. После whitelist'а — нажать **Re-register** в Console.

## Smoke test после регистрации

```bash
ssh -i ~/.ssh/voiceagent_ed25519 root@203.0.113.10 \
  'docker exec voiceagent-backend python -c "
import asyncio
from shared.settings import get_settings
from shared.voximplant import VoximplantClient
async def go():
    s = get_settings()
    c = VoximplantClient(s.voximplant_account_id, s.voximplant_api_key, s.voximplant_application_id)
    info = await c.get_account_info()
    print({k:v for k,v in info[\"result\"].items() if k in (\"balance\",\"max_sip_registrations\",\"active\",\"frozen\")})
    await c.aclose()
asyncio.run(go())
"'
```

`max_sip_registrations` должно быть >= 1 после пополнения.
