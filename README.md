# VoiceAgent — AI-звонарь и аналитика звонков

Производственный backend для **исходящих AI-звонков** по тёплым лидам и
**автоматической оценки** входящих менеджерских звонков. Голосовой агент сам
звонит, ведёт диалог на русском, квалифицирует лида и при интересе отправляет
WhatsApp и заводит карточку в CRM. Параллельно второй модуль скачивает записи
звонков менеджеров, транскрибирует их и выставляет LLM-оценки по воронке продаж.

> Кейс на примере детской спортивной школы. Все имена, домены, телефоны и ключи
> в репозитории — обезличенные демо-данные.

---

## Что умеет

- **AI-звонарь (`zvonar/`)** — исходящий звонок через Voximplant, распознавание
  речи, диалог на LLM по сценарию продаж (приветствие → подтверждение заявки →
  квалификация → презентация → отработка возражений → закрытие), синтез речи
  ElevenLabs, классификация исхода (`interested / not_interested / no_answer`).
- **Авто-WhatsApp + CRM** — при `interested` уходит шаблон в WhatsApp (Green API)
  и создаётся/обновляется лид в Альфа CRM (идемпотентно по телефону).
- **Аналитика менеджерских звонков (`call_analytics/`)** — webhook от телефонии,
  скачивание записи, загрузка в облако, транскрибация (AssemblyAI + Whisper
  fallback), LLM-оценка по критериям с роутингом модели по длительности звонка.
- **Дашборд (`dashboard/`)** — FastAPI + SSR, 4 роли доступа (owner / director /
  rop / manager), карточки звонков, транскрипты, оценки, юнит-экономика, а также
  self-service редактор сценария, промо и квалификационных вопросов.
- **Режим `FAKE_PROVIDERS`** — весь пайплайн прогоняется на фейковых провайдерах
  и фикстурах диалогов, без единого живого ключа. Основа для тестов и разработки.

## Стек

Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL · Pydantic Settings ·
Jinja2 (SSR) · Docker Compose · nginx.
Интеграции: Voximplant, ElevenLabs, AssemblyAI / OpenAI Whisper, Anthropic Claude
и OpenAI (LLM-роутинг), Green API (WhatsApp), Альфа CRM, Cloudinary, OnlinePBX.

## Архитектура

Подробная схема, доменные таблицы и потоки данных — в
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

```
CSV/CRM → очередь → Voximplant → STT → LLM-диалог → ElevenLabs TTS →
   квалификация → (interested) → WhatsApp + CRM → PostgreSQL → Dashboard
```

## Структура репозитория

```
zvonar/          AI-звонарь: сценарий диалога, промпты, роутер реплик, VoxEngine
call_analytics/  пайплайн оценки менеджерских звонков
dashboard/       FastAPI-дашборд (SSR-шаблоны, роли, self-service)
shared/          модели, настройки, клиенты интеграций, миграции Alembic
skills/          операционные runbook-скрипты (healthcheck, backup, cost-report)
infra/           docker-compose, Dockerfile, nginx, deploy-скрипты
docs/            архитектура, runbook'и, таксономия телефонных сбоев
tests/           pytest + фикстуры диалогов и golden-файлы исходов
```

## Локальный запуск (offline, без ключей)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r shared/requirements.txt
cp .env.example .env          # значения-плейсхолдеры можно не менять для тестов

# тесты гоняются в FAKE_PROVIDERS-режиме на отдельной test-БД в Postgres
export FAKE_PROVIDERS=true
export DATABASE_URL="postgresql+psycopg://voiceagent:voiceagent@localhost:5432/voiceagent"
export SECRET_KEY=dev
pytest -q
```

Полный прод-стенд (backend + Postgres + nginx) поднимается через
[`infra/docker-compose.yml`](infra/docker-compose.yml); пошаговая настройка
телефонии — в [`docs/VOXIMPLANT_SETUP.md`](docs/VOXIMPLANT_SETUP.md).

## Тестирование

`pytest` покрывает квалификацию диалогов (golden-файлы исходов), парсинг
CSV-базы, моки всех внешних интеграций, роли и доступ дашборда, расчёт стоимости
звонка и e2e-симуляцию диалога на фикстурах. Сетевые вызовы в тестах замоканы.

## Документация

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — архитектура, БД, потоки данных
- [`docs/VOXIMPLANT_SETUP.md`](docs/VOXIMPLANT_SETUP.md) — настройка SIP-trunk и Application
- [`docs/TELEPHONY_FAILURES.md`](docs/TELEPHONY_FAILURES.md) — таксономия классов сбоев телефонии
- [`docs/RUNBOOK_FIRST_PRODUCTION_CALL.md`](docs/RUNBOOK_FIRST_PRODUCTION_CALL.md) — чек-лист первого боевого звонка
- [`docs/CLIENT_SELF_SERVICE.md`](docs/CLIENT_SELF_SERVICE.md) — self-service возможности дашборда
