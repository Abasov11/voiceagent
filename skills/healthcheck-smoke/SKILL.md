---
name: healthcheck-smoke
description: Быстрый smoke стека VoiceAgentа на VPS клиента (postgres, backend, dashboard, nginx). Триггеры — «жив ли стек», «после рестарта VPS», «алёрт от cron-мониторинга».
---

# Healthcheck smoke

## Когда использовать
- Утром перед началом сессии — убедиться что VPS не упал ночью
- После любого `docker compose restart` или рестарта VPS
- Получили алёрт от `voiceagent-ops/bin/healthcheck.sh` (когда вернём cron через отдельный бот)
- Перед демо клиенту — за 30 минут до созвона

## Pre-checks
- SSH на VPS клиента работает: `ssh app-user@203.0.113.10`

## Steps
```bash
# 1. Контейнеры живы и healthy
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
# Ожидание: voiceagent-postgres Up, voiceagent-backend Up, voiceagent-nginx Up

# 2. Бэкенд отвечает на /health
curl -sS http://127.0.0.1:8000/health | head -5
# Ожидание: {"status":"ok",...}

# 3. БД отвечает
docker exec voiceagent-postgres pg_isready -U voiceagent
# Ожидание: accepting connections

# 4. Дашборд отвечает на главную
curl -sSI http://127.0.0.1/ | head -3
# Ожидание: HTTP/1.1 200 OK или 302 на /login

# 5. Cloudinary upload работоспособен (если ключи в .env)
docker exec voiceagent-backend python -c "from shared.cloudinary import client; print(client.ping())" 2>&1 | tail -3

# 6. Альфа CRM достижим
docker exec voiceagent-backend python -c "from shared.alfacrm_client import AlfaCRM; import asyncio; c = AlfaCRM.from_env(); print(asyncio.run(c.ping()))" 2>&1 | tail -3

# 7. Свободное место на диске
df -h /opt/voiceagent /var/lib/docker | tail -3
# Ожидание: ≥30% свободно

# 8. Свежесть бэкапов (последний pg_dump моложе 26 часов)
ls -lt /opt/voiceagent/backups/*.sql.gz | head -3
```

## Verify
- Все 8 пунктов зелёные
- При любой жёлтой/красной — НЕ восстанавливать молча. Записать в лог "ALERT 2026-XX-XX: <класс>" и спросить команды

## Возможные классы сбоев (см. TELEPHONY_FAILURES.md)
- (4) красное → `dashboard_db_down` либо nginx config сломан
- (5) ошибка → `cloudinary` quota / wrong key
- (6) ошибка → `crm_rate_limit` либо ключ просрочен
- (7) <20% → срочно чистить `/var/lib/docker` (старые images) или расширять диск

## Связано
- `voiceagent-ops/bin/healthcheck.sh` — cron версия (сейчас disabled)
