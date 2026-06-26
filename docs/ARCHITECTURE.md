# Архитектура — VoiceAgent

## Общая картина

Три самостоятельных модуля, общая БД и общий дашборд:

```
┌──────────────────────────────┐         ┌────────────────────────────┐
│  AI-звонарь (zvonar)         │         │ Анализ менеджерских звонков│
│                              │         │ (call-analytics)           │
│  CSV-база → очередь          │         │                            │
│         ↓                    │         │  OnlinePBX webhook         │
│  Voximplant исходящий звонок │         │         ↓                  │
│         ↓                    │         │  скачать запись            │
│  STT (Voximplant/Whisper)    │         │         ↓                  │
│         ↓                    │         │  Cloudinary upload         │
│  LLM-диалог (GPT/Claude)     │         │         ↓                  │
│         ↓                    │         │  AssemblyAI/Whisper STT    │
│  ElevenLabs TTS              │         │         ↓                  │
│         ↓                    │         │  LLM-оценка (роутинг       │
│  Voximplant воспроизводит    │         │   по длине: <60s — Haiku,  │
│         ↓                    │         │   >60s — Sonnet)           │
│  Квалификация                │         │         ↓                  │
│  (interested/not/missed)     │         │  scores в БД               │
│         ↓                    │         └────────────────────────────┘
│  Если interested:            │                       │
│   - Green API → WhatsApp     │                       │
│   - Альфа CRM → лид          │                       │
└──────────────────────────────┘                       │
                │                                      │
                └──────────────┬───────────────────────┘
                               ↓
                    ┌──────────────────────┐
                    │ PostgreSQL (общая)   │
                    └──────────────────────┘
                               ↑
                    ┌──────────────────────┐
                    │ Dashboard            │
                    │ (4 роли, FastAPI +   │
                    │  SSR-frontend)       │
                    └──────────────────────┘
```

## Доменные сущности БД

| Таблица | Поля (ключевые) | Источник |
|---|---|---|
| `leads` | `id`, `alfa_crm_id`, `phone`, `name`, `segment` (наборки/академия/филиал/спецпроект), `status`, `interested`, `created_at` | sync с Альфа CRM |
| `manager_calls` | `id`, `manager_id`, `phone`, `direction`, `started_at`, `duration_s`, `recording_url` (Cloudinary), `onlinepbx_id` | OnlinePBX webhook |
| `transcripts` | `id`, `call_id`, `provider` (assemblyai/whisper), `text`, `lang`, `duration_s`, `cost_cents` | call-analytics |
| `llm_scores` | `id`, `call_id`, `criterion`, `score` (0-10), `comment`, `model` | call-analytics |
| `call_summaries` | `id`, `call_id`, `total_score`, `funnel_stage` (диалог/сделка), `created_at` | derived |
| `zvonar_calls` | `id`, `lead_id`, `started_at`, `duration_s`, `outcome` (interested/not/missed/no_answer), `transcript`, `voximplant_session_id` | zvonar |
| `whatsapp_sends` | `id`, `lead_id`, `template`, `sent_at`, `green_api_message_id`, `delivered`, `read` | zvonar |
| `managers` | `id`, `name`, `phone`, `onlinepbx_extension`, `role` (sales/rop/director) | curated (Данияр, Камила, Бекзат, Аскар) |
| `dashboard_users` | `id`, `email`, `password_hash`, `role` (owner/director/rop/manager), `manager_id` (если роль=manager) | manual seed |

## Поток данных AI-звонаря

1. `csv_loader.py` загружает CSV-базу клиента, нормализует, кладёт в `leads` (segment + phone).
2. `dialer.py` берёт пачку лидов с `interested IS NULL`, ставит в очередь Voximplant.
3. Voximplant сценарий вызывает webhook нашего бэкенда на каждый шаг диалога:
   - получили речь клиента → STT (внутри Voximplant либо Whisper API)
   - бэкенд отдаёт ответный текст (GPT/Claude по сценарию)
   - бэкенд просит TTS у ElevenLabs, отдаёт URL аудио — Voximplant воспроизводит
4. По окончанию звонка Voximplant шлёт финальный webhook с outcome.
5. Если outcome=interested → Green API отправляет WhatsApp + Альфа CRM создаёт/обновляет лид.

## Поток данных аналитики менеджерских звонков

1. OnlinePBX по завершении звонка дёргает наш webhook `/webhooks/onlinepbx`.
2. Бэкенд скачивает запись по URL из webhook.
3. Загружает в Cloudinary (folder=`manager-calls/YYYY-MM-DD/`).
4. Отправляет на транскрибацию (AssemblyAI primary; OpenAI Whisper fallback).
5. По длине звонка выбирает LLM:
   - `< 60s` → claude-haiku (≈90% звонков, дешёвая модель)
   - `≥ 60s` → claude-sonnet (длинные продающие диалоги)
6. Промпт LLM содержит критерии оценки + текст диалога. Возвращает JSON массив `{criterion, score, comment}` + `total_score` + `funnel_stage`.
7. Сохраняем в `transcripts`, `llm_scores`, `call_summaries`.

## Дашборд — роли и доступ

| Роль | Кому | Видит |
|---|---|---|
| owner | Аскар Демо | всё (включая стоимость API) |
| director | Бекзат | всё кроме стоимости |
| rop | Бекзат (та же учётка с ролью director — расширенный доступ) | звонки всех менеджеров, оценки, воронка |
| manager | Данияр, Камила | только свои звонки и свои оценки |

NB: Бекзат совмещает роли opera-директора и РОПа — ему дадим одну учётку с правами всех 3 верхних ролей. Технически это две учётки или флаг `also_director_view` — решим в Task #6.

## Внешние API — лимиты, что мониторить

| API | Что критично |
|---|---|
| Альфа CRM v2 | rate-limit, идемпотентность создания лидов (по phone) |
| OnlinePBX | webhook auth (HMAC?), доступ к URL записей |
| Cloudinary | квота (free 25GB) — может не хватить, отслеживать рост |
| AssemblyAI | ru-RU поддержка, цена $0.37/час |
| OpenAI Whisper | $0.006/min, fallback |
| Voximplant | cents/min исходящих, аренда SIP-номера |
| ElevenLabs | символьный лимит, выбор voice_id под русский |
| Green API | rate-limit на отправку, шаблоны WA |
| GPT-5 / Claude | стоимость токенов; кеширование промптов |
