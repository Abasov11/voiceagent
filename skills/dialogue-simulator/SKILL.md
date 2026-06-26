---
name: dialogue-simulator
description: Прогон zvonar/simulate.py на фикстурах + edge case'ах для проверки логики диалога. Триггеры — «прогони диалоги», «проверь что dialog_state не уехал», «новый сценарий от клиента».
---

# Dialogue simulator

## Когда использовать
- После правки `zvonar/dialog_state.py`, `zvonar/prompts.py`, `zvonar/simulate.py`
- После получения нового скрипта разговора от клиента
- При подозрении на `dialog_loop` (см. TELEPHONY_FAILURES.md #12)
- Перед демо — убедиться что 3+ синтетических диалога не уезжают

## Pre-checks
- Контейнер `voiceagent-backend` живой
- Фикстуры в `tests/fixtures/dialog_*.txt` существуют

## Steps
```bash
# 1. Базовый rule-based (без LLM, для регрессионных проверок)
docker exec -it voiceagent-backend python -m zvonar.simulate --transcript /app/tests/fixtures/dialog_interested.txt
docker exec -it voiceagent-backend python -m zvonar.simulate --transcript /app/tests/fixtures/dialog_not_interested.txt

# 2. С реальным Claude (если ANTHROPIC_API_KEY в .env)
docker exec -it -e USE_LLM=true voiceagent-backend python -m zvonar.simulate \
  --transcript /app/tests/fixtures/dialog_interested.txt

# 3. Stress-кейсы (создать если их нет в fixtures/):
#    - dialog_silence.txt — клиент молчит / отвечает «...»
#    - dialog_rude.txt — мат / агрессия
#    - dialog_busy.txt — «занят, перезвоните» — должен закрыться корректно
#    - dialog_loop_bait.txt — клиент даёт неоднозначные ответы, провоцирует петлю
docker exec -it voiceagent-backend python -m zvonar.simulate --transcript /app/tests/fixtures/dialog_silence.txt
# (и т.д.)

# 4. Hard-cap проверка
docker exec -it voiceagent-backend python -m zvonar.simulate \
  --transcript /app/tests/fixtures/dialog_loop_bait.txt --max-turns 12
# Должен завершиться через ≤12 ходов с outcome=dialog_timeout
```

## Verify
- Все диалоги завершаются с явным `outcome ∈ {interested, not_interested, no_answer, dialog_timeout}`. Никаких `outcome=None`, никаких exception.
- Длина диалога (число ходов) ≤ MAX_TURNS из config (по умолчанию 12).
- В transcript нет «галлюцинаций» вида «как мы и договаривались» если предыдущего звонка не было.
- При `dialog_busy.txt` агент вежливо завершает в ≤2 хода — не пытается продавать насильно.

## Что чинить если что-то не так
- Если outcome=None → класс `dialog_loop`, см. TELEPHONY_FAILURES.md #12. Hard-cap не сработал — починить в `dialog_state.py`.
- Если LLM продолжает после «занят» → промпт в `prompts.py` не учит агента вежливому отказу. Доработать.
- Если exception → класс `llm_provider_fail` (#7). Проверить ключи и retry.

## Связано
- `docs/TELEPHONY_FAILURES.md` #12 — dialog_loop class
