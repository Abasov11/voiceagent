# Voximplant — runbook настройки SIP-trunk и AI-звонаря

Контекст: клиент уже завёл аккаунт на `voximplant.kz` (Platform, **не Kit**) и
прислал учётные данные. SIP-номер — SIP-оператор (см. photo_25 от 2026-04-30 и
`shared/sip_settings.py`). Мы заходим в готовый аккаунт и собираем сценарий.

## 0. Pre-check (один раз)

- [ ] Войти на `https://manage.voximplant.kz` логином клиента
      (`your-voximplant-login@example.com / YOUR_VOXIMPLANT_PASSWORD`).
- [ ] Подтвердить, что выбран продукт **Platform**, а не **Kit**
      (если показывает Kit-интерфейс — пересоздать с правильным выбором).
- [ ] Profile → Service → API Keys: получить `Account ID` и `Api Key`.
- [ ] Положить в `/opt/voiceagent/.env`:
      ```
      VOXIMPLANT_ACCOUNT_ID=...
      VOXIMPLANT_API_KEY=...
      VOXIMPLANT_EMAIL=your-voximplant-login@example.com
      ```
- [ ] Перезапустить backend: `cd /opt/voiceagent/infra && docker compose --env-file ../.env up -d backend`
- [ ] Проверить: `curl http://127.0.0.1/debug/integrations | jq` — ключ `voximplant: true`.

## 1. SIP-trunk (SIP-оператор)

В личном кабинете Voximplant → **SIP Registration**:

| Поле | Значение |
|---|---|
| Name | `sip_provider-almaty-main` |
| Proxy | `almpbx.example.com` |
| Outbound proxy | `almpbx.example.com` |
| Username | `sip_login_1` (или один из других логинов из письма) |
| Password | `sip_password` |
| Auth User | (то же что Username) |
| Expires | `120` |
| Caller ID | `+7707XXXXXXX` (один из 3 номеров от SIP-оператор) |

После сохранения:
- статус должен стать **Registered** в течение ~30 секунд;
- если `Failed` — наш Voximplant gateway-IP не в whitelist SIP-оператор.
  Нужно отправить письмо менеджеру SIP-оператор.
- наш публичный SIP-source IP в Voximplant можно посмотреть в их docs:
  `Documentation → SIP signaling IP ranges`. Записать его в
  `SIP_PUBLIC_ADDRESS` в `.env`.

## 2. Application + Rule + Scenario

1. **Applications → Create Application** → name: `voiceagent-zvonar`,
   `*.voximplant.com` сабдомен оставить по умолчанию.
2. **Scenarios → Create Scenario** → name: `voiceagent-outbound`,
   вставить содержимое `zvonar/voxengine_scenario.js`.
   - Перед заливкой заменить:
     - `BACKEND_URL` → `https://voiceagent.example.com` (или `http://203.0.113.10` пока нет HTTPS).
     - `SHARED_TOKEN` → значение `SECRET_KEY` из `/opt/voiceagent/.env`.
3. **Rules → Create Rule** в приложении `voiceagent-zvonar`:
   - Name: `outbound-rule`
   - Pattern: `.*` (применяется ко всем номерам, разводка идёт по `customData.phone`)
   - Scenario: `voiceagent-outbound`
4. Скопировать `rule_id` → положить в `.env`:
   ```
   VOXIMPLANT_APPLICATION_ID=...
   VOXIMPLANT_RULE_ID=...
   ```

## 3. Тестовый звонок (без LLM)

```bash
ssh -i ~/.ssh/voiceagent_ed25519 root@203.0.113.10 \
  docker exec voiceagent-backend python -c "
import asyncio
from shared.settings import get_settings
from shared.voximplant import VoximplantClient
s = get_settings()
async def main():
    c = VoximplantClient(s.voximplant_account_id, s.voximplant_api_key, s.voximplant_application_id)
    print(await c.start_outbound_call(rule_id=s.voximplant_rule_id, phone='+77071234567', custom_data='{\"lead_id\":1}'))
    await c.aclose()
asyncio.run(main())
"
```

Ожидаемое поведение:
- Voximplant примет сценарий, начнёт звонок.
- VoxEngine обратится к нашему `/zvonar/dialogue/turn`.
- Если `ANTHROPIC_API_KEY` не задан → ответ из FAKE_PROVIDERS, диалог пройдёт по rule-based ветке.
- Запись звонка появится в Voximplant Console → Calls History.

## 4. Что блокирует production-вызовы (статус 2026-04-30)

| Блок | Кто разблокирует |
|---|---|
| IP Voximplant gateway не в whitelist SIP-оператор | Клиент (письмо в SIP-оператор) |
| `ANTHROPIC_API_KEY` пуст → FAKE-диалог | команда |
| Cloudinary upload скрытно отключён → запись разговора нигде не остаётся | Клиент (API Key+Secret) |
| Нет реального скрипта от ОП → промпты на generic-описании | Клиент |

## 5. Откат к FAKE_PROVIDERS (если signup сорвётся)

```bash
ssh -i ~/.ssh/voiceagent_ed25519 root@203.0.113.10 \
  'echo "FAKE_PROVIDERS=true" >> /opt/voiceagent/.env && \
   docker compose -f /opt/voiceagent/infra/docker-compose.yml --env-file /opt/voiceagent/.env up -d backend'
```

После этого `python -m zvonar.simulate` работает локально без Voximplant.
