# RUNBOOK: первый реальный звонок реальному клиенту

> Чек-лист от состояния «всё разблокировано» до «agent звонит первому реальному клиенту».
> Использовать как пошаговый протокол. Каждый шаг — checkbox.

---

## Pre-flight (за день до)

### 1. Все ключи на месте

```bash
ssh -i ~/.ssh/voiceagent_ed25519 root@203.0.113.10 \
  'docker cp /opt/voiceagent/infra/scripts/precheck.py voiceagent-backend:/app/precheck.py 2>/dev/null; \
   docker exec voiceagent-backend python /app/precheck.py'
```

Все строки должны быть **✅** или явное **⚠️ accept-as-known-risk**. Ни одного **❌**.

### 2. Регрессионный прогон зелёный

```bash
pytest -q
```

Все тесты зелёные; известные риски помечены accept-as-known-risk
для production.

### 3. Voximplant SIP-trunk зарегистрирован

```bash
ssh -i ~/.ssh/voiceagent_ed25519 root@203.0.113.10 \
  'docker exec voiceagent-backend python -c "
import asyncio
from shared.voximplant import VoximplantClient
from shared.settings import get_settings
async def go():
    s = get_settings()
    c = VoximplantClient(s.voximplant_account_id, s.voximplant_api_key)
    info = await c.get_account_info()
    print(\"sip_max:\", info[\"result\"][\"max_sip_registrations\"])
    print(\"balance:\", info[\"result\"][\"balance\"])
    await c.aclose()
asyncio.run(go())
"'
```

`sip_max >= 1` и `balance >= 5.0`.

В Voximplant Console → SIP Registrations должно быть **Registered**.
Если **Unregistered** — IP в whitelist SIP-оператор не добавлен.

### 4. Запись на свой номер

Перед звонком клиенту — **минимум один тестовый звонок на свой мобильный**:

```bash
ssh -i ~/.ssh/voiceagent_ed25519 root@203.0.113.10 \
  'docker exec voiceagent-backend python -c "
import asyncio, json
from shared.voximplant import VoximplantClient
from shared.settings import get_settings
async def go():
    s = get_settings()
    c = VoximplantClient(s.voximplant_account_id, s.voximplant_api_key, s.voximplant_application_id)
    res = await c.start_outbound_call(
        rule_id=s.voximplant_rule_id,
        phone=\"+7XXXXXXXXXX\",  # свой мобильный
        custom_data=json.dumps({\"lead_id\": 1}),
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    await c.aclose()
asyncio.run(go())
"'
```

Что должно произойти:
- ваш телефон зазвонит
- агент приветствует, спрашивает удобно ли говорить
- разговор записывается в Voximplant Console (Calls History)
- бэкенд получает `/zvonar/dialogue/turn` POST и `/zvonar/dialogue/finish`

После звонка — проверить `/dashboard/zvonar` (под учёткой owner): должна появиться запись с
правильным `outcome` и `failure_class=None`.

### 5. Контроль расходов

После тестового звонка — глянуть стоимость:

```bash
ssh -i ~/.ssh/voiceagent_ed25519 root@203.0.113.10 \
  'docker cp /opt/voiceagent/skills/cost_report/run.py voiceagent-backend:/app/cost_run.py && \
   docker exec voiceagent-backend python /app/cost_run.py --period 24h'
```

Один тестовый звонок на 1-2 минуты должен стоить < $0.05.
Если больше — что-то не так с тарифами в `cost_calculator.py`.

---

## Day-of (день первого реального звонка)

### 6. Время

- 18:00-21:00 МСК / 21:00-24:00 Алматы.
- Не звонить в обед, в ранее утро, в выходные ночью.

### 7. Согласование с клиентом (Бекзат)

Бекзат должен **подтвердить** список из 5-10 первых лидов которым звоним. Это не cold-list,
это «знакомые» лиды из его базы которых мы предупредили что будет AI-звонок. Снижает риск
жалоб «странный звонок», «откуда у вас номер».

### 8. Pre-flight на VPS

```bash
docker exec voiceagent-backend python /app/precheck.py --strict
echo "Expected exit code: 0"
```

Если 0 — поехали. Если 1 — какие предупреждения накопились, читать.

### 9. Запуск обзвона

В дашборде `/dashboard/zvonar` нажать «Запустить» (если кнопка готова) или
запустить через CLI:

```bash
docker exec voiceagent-backend python -c "
import asyncio
from shared.alfacrm_sync import sync_all
asyncio.run(sync_all())  # на всякий обновим лиды
"
```

Затем — выбрать N подтверждённых лидов и в дашборде через ручной trigger вызвать обзвон.
**На MVP пока CLI**:

```bash
docker exec voiceagent-backend python -c "
import asyncio, json
from shared.voximplant import VoximplantClient
from shared.settings import get_settings
APPROVED = [123, 456, 789]  # ID из dashboard/leads
async def go():
    s = get_settings()
    c = VoximplantClient(s.voximplant_account_id, s.voximplant_api_key, s.voximplant_application_id)
    for lead_id in APPROVED:
        # тут SQL get phone by lead_id
        ...
asyncio.run(go())
"
```

### 10. Мониторинг во время

В отдельном терминале:

```bash
ssh -i ~/.ssh/voiceagent_ed25519 root@203.0.113.10 \
  'docker logs -f voiceagent-backend' | grep -iE "zvonar|finish|failure"
```

Также — `/dashboard/zvonar` обновлять каждые 30 секунд: видеть outcome'ы по мере прихода.

### 11. После окончания

- Прослушать 1-2 записи в Voximplant Console (вручную).
- Проверить дашборд: `interested` = ожидаемое число (из 10 ~3-5 разумно).
- Глянуть `cost-report --period 24h`: cost-per-call в пределах оценки.
- Telegram-уведомление: «прогон N звонков, M interested, $X total». **TODO** когда вернётся ops-bot.

---

## Critical aborts (когда ОСТАНОВИТЬСЯ)

🔴 **Если в первые 3 звонка:**
- 100% no_answer — проверить SIP-trunk (Voximplant Console → SIP Registrations);
  возможно whitelist SIP-оператор не работает.
- Каждый звонок длится <5 секунд — VAD ловит шум, либо клиент сразу кладёт.
- В логах backend сыплются `failure_class=llm_fail` — Anthropic упал, выключить обзвон.
- Stack trace в логах больше 5 раз подряд — точно баг, остановиться, разобраться.

**Команда экстренной остановки:**

```bash
ssh -i ~/.ssh/voiceagent_ed25519 root@203.0.113.10 \
  'docker exec voiceagent-backend python -c "
import asyncio
from shared.voximplant import VoximplantClient
from shared.settings import get_settings
async def go():
    s = get_settings()
    c = VoximplantClient(s.voximplant_account_id, s.voximplant_api_key)
    # TODO: получить активные сессии и завершить через StopScenarios
    await c.aclose()
asyncio.run(go())
"'
```

(Кода `StopScenarios` пока нет — TODO добавить в `shared/voximplant.py` перед prod.)

Альтернатива — выключить SIP-trunk вручную в Voximplant Console (одна кнопка) → новые звонки
не пройдут, текущие закончатся естественно.

---

## После первого боевого прогона

1. Сделать commit с тегом `first-prod-call-2026-XX-XX` в git.
2. Сохранить логи `docker logs voiceagent-backend` за окно ±1 час обзвона в `/var/backups/voiceagent-snapshots/logs-YYYY-MM-DD.txt`.
3. Прослушать **ВСЕ** записи (если их 5-10), отметить:
   - голос Eric — норм / поменять?
   - tempo / latency — есть ли тишина перед ответом?
   - агент уходит ли в петлю на нестандартных ответах?
4. Зафиксировать новые edge-case'ы регресс-тестами в `tests/`.
5. Обсудить с Бекзатом результаты — `interested`-конверсия (это база для прогноза).

---

## Связанные документы

- `docs/TELEPHONY_FAILURES.md` — таксономия 13 классов сбоев
- `docs/VOXIMPLANT_SETUP.md` — runbook Application/Rule/SIP-trunk
- `skills/voximplant-trunk-setup/SKILL.md` — runbook повторной регистрации
- `skills/cost-report/SKILL.md` — отчёт по unit-economics
