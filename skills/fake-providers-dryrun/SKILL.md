---
name: fake-providers-dryrun
description: Прогон pipeline без реальных внешних API (FAKE_PROVIDERS=true). Триггеры — «проверь что pipeline жив без ключей», «прогон после правки кода», «smoke перед коммитом».
---

# Fake-providers dry-run

## Когда использовать
- После любой правки в `zvonar/`, `call_analytics/`, `shared/` — убедиться что pipeline не сломался
- Перед коммитом: smoke-проверка дешевле полных тестов
- Когда нет/закончились реальные API-ключи (Cloudinary, AssemblyAI, Anthropic), но надо проверить логику

## Pre-checks
- На VPS клиента, контейнер `voiceagent-backend` живой
- В `tests/fixtures/` есть `dialog_interested.txt`, `dialog_not_interested.txt`, `sample_call.mp3.txt`, `leads_sample.csv`

## Steps
```bash
# 1. Pipeline call-analytics с фейковым звонком (manager_call id=1)
docker exec -e FAKE_PROVIDERS=true voiceagent-backend python -c \
  "from call_analytics.pipeline import process_manager_call; import asyncio; asyncio.run(process_manager_call(1))"

# 2. Симулятор диалога звонаря (rule-based, без LLM)
docker exec -it voiceagent-backend python -m zvonar.simulate

# 3. Симулятор на конкретной фикстуре
docker exec -it voiceagent-backend python -m zvonar.simulate \
  --transcript /app/tests/fixtures/dialog_interested.txt
docker exec -it voiceagent-backend python -m zvonar.simulate \
  --transcript /app/tests/fixtures/dialog_not_interested.txt

# 4. Тесты (быстрые)
docker exec voiceagent-backend pytest /app/tests -x -q
```

## Verify
- (1) выводит `processed manager_call id=1, transcript_id=..., score=...` без exception
- (2) и (3) проходят 3 диалога без exception, печатают финальный outcome
- (4) **41/41 passed** (или больше, если добавили тесты). Меньше 41 — регрессия.

## Что проверять руками после dry-run
- Дашборд (http://203.0.113.10) показывает обновлённые цифры на home — кол-во лидов, заинтересованные, расход API
- `docker logs voiceagent-backend --tail 50` — нет ERROR/CRITICAL
- `docker exec voiceagent-postgres psql -U voiceagent -c "SELECT * FROM api_call_log ORDER BY id DESC LIMIT 5"` — fake-провайдер записывает строки с `cost_cents=0`

## Связано
- `shared/fakes.py` — реализация
