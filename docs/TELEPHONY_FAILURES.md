# TELEPHONY_FAILURES — taxonomy сбоев AI-звонаря

> Применяется по bug-fix protocol: «root cause одной строкой ДО кода, обобщить в правило про КЛАСС ошибки, плохой фикс не патчить — откатывать».
>
>
> **Цель:** когда первый звонок упадёт в проде — не «оно не работает», а «класс N, root-cause известен, runbook ниже».

## Колонки

- **Class** — короткий идентификатор для логов / `outcome` поля
- **Root cause one-liner** — корневая причина, не симптом
- **Detection** — как код понимает что это случилось
- **Recovery** — что делает код автоматически
- **Manual action** — что должен сделать оператор / менеджер
- **Class rule** — generalized правило (что в feedback memory)

---

## 1. `no_answer` — клиент не взял трубку

| Поле | Значение |
|---|---|
| Root cause | SIP RING прозвонил полный таймаут, hangup без `200 OK` |
| Detection | Voximplant событие `Call.Disconnected` с `code=480/487` после ≥30s ringing |
| Recovery | Запись `outcome=no_answer`, лид остаётся `interested IS NULL`, дозвон через ≥4ч (политика клиента) |
| Manual | Если 3 попытки не ответил — менеджер вручную WhatsApp |
| Class rule | Любой звонок без user-speech → `no_answer`, не `not_interested`. Не учить LLM на «как мы говорили в прошлый раз» |

## 2. `voicemail_or_amd` — попал на автоответчик

| Поле | Значение |
|---|---|
| Root cause | Оператор/абонент включил голосовую почту или автоответ; AMD не сработал → агент пытается говорить с ботом |
| Detection | Voximplant AMD = `machine` ИЛИ длинный single-utterance >8s в первые 4s диалога (типичный «абонент недоступен») |
| Recovery | Hangup сразу, `outcome=voicemail`. Не оставлять сообщения. |
| Manual | Менеджер дозванивается лично, AI-звонарь молчит на этом лиде 24ч |
| Class rule | AMD должен быть включён в Voximplant scenario. False-positive (приняли человека за машину) лучше чем false-negative (агент рассказывает скрипт автоответчику) |

## 3. `busy` — занято

| Поле | Значение |
|---|---|
| Root cause | SIP `486 Busy Here` |
| Detection | Voximplant `Call.Disconnected code=486` |
| Recovery | Retry через 30 минут (max 3 попытки), потом `outcome=busy_persistent` |
| Manual | — |
| Class rule | `busy` ≠ `no_answer`. Разные retry-политики, разные следующие действия |

## 4. `spam_block` — оператор/абонент заблокировал номер

| Поле | Значение |
|---|---|
| Root cause | После N звонков с одной SIM на множество разных абонентов оператор (Билайн/Актив/SIP-оператор) или приложение типа Truecaller блокирует исходящий → вызов не доходит |
| Detection | Косвенно: процент `no_answer` за окно 1ч >60% ИЛИ среднее `ring_duration` <3s по серии |
| Recovery | Автоматически нет — нужна ротация SIP-номеров. Алёрт в дашборд + Telegram через `voiceagent-ops-bot` |
| Manual | Подключить новый SIP-номер, прогреть (≤20 звонков/день первые 3 дня), вывести подозрительный из ротации |
| Class rule | Один SIP-номер — лимит ~50-100 звонков/день в KZ. Прогрев новых обязателен. Метрика «процент дозвонов» — обязательно в дашборде |

## 5. `low_quality_audio` — VAD/STT-fail из-за качества записи

| Поле | Значение |
|---|---|
| Root cause | Шум фона / эхо / низкий битрейт SIP → VAD не отделяет речь, STT возвращает мусор или пусто |
| Detection | STT confidence <0.3 ИЛИ transcript = пустая строка / `[unintelligible]` ≥3 раза подряд |
| Recovery | Агент: «извините, плохая связь, перезвоню» → hangup, `outcome=low_quality`. Retry через 1ч. |
| Manual | Если повторяется на конкретном номере — вынести в `manual_call_required` |
| Class rule | Любой STT с confidence <0.3 — не отправлять в LLM. Голос плохой → лучше вежливо повесить трубку, чем нести околесицу |

## 6. `stt_provider_fail` — AssemblyAI/Whisper упал

| Поле | Значение |
|---|---|
| Root cause | API провайдер вернул 5xx / timeout / quota |
| Detection | Exception в `transcribe()` ИЛИ HTTP timeout >30s |
| Recovery | Fallback на secondary провайдер (AssemblyAI → OpenAI Whisper). Если оба упали — `outcome=technical_failure`, dialog переходит в «техническая пауза, перезвоним», hangup |
| Manual | Алёрт в Telegram, оператор проверяет статус провайдеров |
| Class rule | Cascade: primary → secondary → graceful. Никогда не оставлять диалог в подвешенном состоянии — клиент должен слышать осмысленный hangup |

## 7. `llm_provider_fail` — Claude/GPT упал посреди диалога

| Поле | Значение |
|---|---|
| Root cause | Anthropic/OpenAI 5xx, rate-limit, taken-down model |
| Detection | Exception в `dialog_step()`; HTTP code ≥500 или 429 |
| Recovery | Retry до 2 раз с экспоненциальной паузой (1s, 3s). Если не помогло — fallback модель (claude-haiku → claude-sonnet → gpt-4o-mini → заранее записанный fallback-диалог). Если всё мертво — graceful exit с записанной фразой |
| Manual | Алёрт + проверить status.anthropic.com / status.openai.com |
| Class rule | LLM-fail не должен ронять Voximplant сессию — только текущий тур. Pre-recorded fallback message обязателен |

## 8. `voximplant_scenario_crash` — JS-сценарий упал

| Поле | Значение |
|---|---|
| Root cause | Exception в `voxengine_scenario.js` (typo, undefined property, network error в webhook) |
| Detection | Voximplant `Scenario.Failed` event |
| Recovery | Сценарий должен иметь `try/catch` на каждом шаге + emergency hangup с записанной фразой «технические неполадки» |
| Manual | Срочно — оператор смотрит логи Voximplant, фиксит сценарий, передеплой |
| Class rule | Любой `try/catch` без logging — silent fail, замаскирует баг. Логировать в наш бэкенд (`/webhooks/voximplant/error`) |

## 9. `elevenlabs_streaming_drop` — TTS оборвался

| Поле | Значение |
|---|---|
| Root cause | ElevenLabs streaming connection закрылся до конца фразы; rate-limit, временный fail, network |
| Detection | streaming chunk не получен >5s ИЛИ HTTP code ≥500 |
| Recovery | Retry без streaming (full-mp3 mode). Если фраза >5s — разбить на 2 предложения. |
| Manual | Если повторяется — переключить voice или quota check |
| Class rule | Streaming ускоряет TTFB но добавляет точку отказа. Always have non-streaming fallback path |

## 10. `crm_rate_limit` — Альфа CRM 429

| Поле | Значение |
|---|---|
| Root cause | Слишком частые запросы при создании/обновлении лида после диалога |
| Detection | HTTP 429 от Альфа CRM v2 |
| Recovery | Очередь с per-second throttle (≤5 r/s). На 429 — retry с exponential backoff. Запись `crm_sync_pending=true`, фоновый воркер дотолкает. |
| Manual | Если фоновый воркер не справляется >1ч — алёрт |
| Class rule | Запись звонка в нашу БД ВСЕГДА происходит. Sync в Альфа — eventually-consistent через очередь. Никогда не блокировать closeCall на Альфу |

## 11. `whatsapp_send_fail` — Green API не отправил

| Поле | Значение |
|---|---|
| Root cause | Green API quota / номер не WhatsApp / шаблон не одобрен |
| Detection | API response без `messageId` или `status=failed` |
| Recovery | 1 retry через 5 минут. После — `whatsapp_sends.delivered=false`, ручная отправка менеджером |
| Manual | Менеджер видит в дашборде «WA не доставлен» → отправляет вручную |
| Class rule | WhatsApp не должен блокировать pipeline. `outcome=interested` + `whatsapp_sends.delivered=false` — нормальное состояние, не ошибка |

## 12. `dialog_loop` — диалог не продвигается

| Поле | Значение |
|---|---|
| Root cause | LLM зацикливается на уточняющих вопросах, клиент не даёт чётких ответов, hard-cap не сработал |
| Detection | Счётчик ходов диалога превысил `MAX_TURNS` (по умолчанию 12) или total duration >180s |
| Recovery | Принудительный exit: «спасибо за разговор, перезвоню позднее», hangup, `outcome=dialog_timeout` |
| Manual | Менеджер видит transcript, решает прозванивать или нет |
| Class rule | Любой LLM-диалог должен иметь TWO hard caps: количество ходов И длительность. Не доверять LLM завершить разговор сам |

## 13. `dashboard_db_down` — дашборд не отвечает потому что БД мертва

| Поле | Значение |
|---|---|
| Root cause | PostgreSQL контейнер упал / disk full / OOM |
| Detection | Healthcheck endpoint возвращает not-ok на ping БД |
| Recovery | Дашборд показывает «сервис временно недоступен» вместо 500 stack-trace |
| Manual | Cron-healthcheck алёртит → оператор проверяет VPS, restart docker-compose |
| Class rule | Никогда не показывать stack-trace клиенту/owner'у. Любой 500 → friendly error page |

---

## Применение

1. **При новом классе сбоя** — добавь строку в эту таблицу. Root-cause one-liner ДО любых правок кода.
2. **При фиксе** — generalize в class rule, обнови соответствующее поле. Не патчь поверх плохого фикса — откати и переделай.
3. **При деплое** — каждый класс из таблицы должен быть либо обработан в коде, либо явно помечен `accept-as-known-risk`.
4. **При post-mortem** — incident должен попасть в один из существующих классов. Если не попал — новый класс, ни-в-коем случае «прочее».

## История изменений

- **2026-04-29** — создан как часть workflow-апгрейда (мультипромпт /Cat). 13 классов на старте; ожидается рост по мере живых инцидентов.
