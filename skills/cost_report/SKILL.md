# Skill: cost-report

**Когда использовать:**
- После 1-2 недель работы — посмотреть unit-economics.
- Перед увеличением объёма обзвона (дать клиенту прогноз стоимости).
- При жалобах «дорого получается» — разложить на компоненты (SIP / TTS / STT / LLM).
- Раз в месяц для отчёта Бекзату/Аскару.

## Источник данных

Таблица `call_cost_breakdown` (alembic `9c1e2f3a8b7d`).
Каждый ряд — один обработанный звонок (manager или zvonar).
Тарифы — `shared/cost_calculator.py` (оценочные, обновлять при изменении прайсов).

## Быстрый отчёт через UI

`http://203.0.113.10/dashboard/` под учёткой owner — секция «Unit-economics звонков»
показывает разбивку за 24h / 7d / 30d.

## Ad-hoc CLI отчёт

```bash
ssh -i ~/.ssh/voiceagent_ed25519 root@203.0.113.10 \
  'docker exec voiceagent-backend python -m skills.cost_report.run --period 7d'
```

Параметры:
- `--period` = `24h` / `7d` / `30d` / `90d` / `all`
- `--by` = `day` / `week` / `provider` (default = period total)
- `--csv` = вывод в CSV (для копирования в Google Sheets)

## Что показывать клиенту

Метрики, которые имеет смысл показать клиенту:
1. **Cost per dialing** — `total_cost_cents / count(zvonar_calls)`.
   Это «сколько стоит одна попытка холодного обзвона».
2. **Cost per interested** — `total_cost_cents / count(outcome=interested)`.
   Это «сколько стоит привлечение одного заинтересованного клиента».
3. **Breakdown** — какая доля падает на SIP / TTS / STT / LLM. Помогает решить, что
   оптимизировать (часто LLM = 60% от total, и можно сократить за счёт haiku-роутинга).

## Известные ограничения

- TTS/SIP-стоимость — оценочные тарифы, реальные ElevenLabs/Voximplant счета сравнивать
  раз в месяц вручную.
- LLM-стоимость берётся из `api_call_log.cost_cents` (короткий = 1¢, длинный = 5¢, упрощение).
  Точная стоимость считается из `usage.input_tokens + output_tokens` × per-Mtok тариф.
- Для записей в FAKE_PROVIDERS режиме `provider_notes.fake = true` — отчёт исключает
  такие записи, чтобы не искажать реальные суммы (TODO: добавить `--include-fake`).

## Связанные

- `shared/cost_calculator.py` — формулы и тарифы (обновлять при смене прайсов)
- `tests/test_cost_calculator.py` + `tests/test_property_qualification.py` (часть про cost) — гарантируют монотонность и `total = sum(components)`
- `dashboard/router.py:home` — owner-only sparkline на главной
