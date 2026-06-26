---
name: backup-verify
description: Проверить что off-VPS бэкапы pg_dump свежие и реально восстанавливаются. Триггеры — «когда последний бэкап», «проверь бэкапы», еженедельная гигиена.
---

# Backup verify

## Когда использовать
- Раз в неделю автоматически (когда вернём cron через отдельный бот)
- Перед опасной schema-миграцией
- После «странного поведения» БД — убедиться что есть к чему откатиться
- Перед большим деплоем

## Pre-checks
- Локально на сервере
- `/var/voiceagent-ops/backups/` существует и содержит файлы

## Steps
```bash
# 1. Список последних 7 бэкапов
ls -lh /var/voiceagent-ops/backups/*.sql.gz | tail -7

# 2. Свежесть последнего (должен быть моложе 26 часов)
LATEST=$(ls -t /var/voiceagent-ops/backups/*.sql.gz | head -1)
AGE_H=$(( ( $(date +%s) - $(stat -c %Y "$LATEST") ) / 3600 ))
echo "Последний бэкап: $LATEST"
echo "Возраст: ${AGE_H}ч"

# 3. Целостность (gzip readable)
gunzip -t "$LATEST" && echo "gzip OK" || echo "GZIP BROKEN"

# 4. SQL внутри парсится (минимальная sanity check — есть CREATE TABLE)
gunzip -c "$LATEST" | grep -c "^CREATE TABLE" 
# Ожидание: ≥9 (по числу таблиц из ARCHITECTURE.md)

# 5. Размер не уменьшился внезапно (по сравнению с предыдущим)
PREV=$(ls -t /var/voiceagent-ops/backups/*.sql.gz | sed -n '2p')
SIZE_NEW=$(stat -c %s "$LATEST")
SIZE_PREV=$(stat -c %s "$PREV")
echo "New: $SIZE_NEW vs Prev: $SIZE_PREV"
# Если new < 80% prev — алёрт «бэкап подозрительно лёгкий»

# 6. (опционально, раз в месяц) Тестовое восстановление в одноразовый docker
docker run --rm -d --name voiceagent-restore-test -e POSTGRES_PASSWORD=test postgres:16
sleep 5
gunzip -c "$LATEST" | docker exec -i voiceagent-restore-test psql -U postgres
docker exec voiceagent-restore-test psql -U postgres -c "\dt"
docker stop voiceagent-restore-test
```

## Verify
- AGE_H ≤ 26
- "gzip OK"
- ≥9 CREATE TABLE
- SIZE_NEW в пределах 80-120% от SIZE_PREV
- (6) если делал — таблицы видны после восстановления

## Тревожные сигналы
- Бэкапы старше 48ч → cron упал (возможно из-за того что мы сняли cron'ы 28.04). Поднять отдельный бот и вернуть.
- Размер скачется на 50%+ вниз → schema migration с большим DROP, либо проблемы с pg_dump
- gzip broken → диск/сеть проблемы при копировании, проверить `voiceagent-ops/logs/backup.log`

## Связано
- `voiceagent-ops/bin/backup_pull.sh` — cron-скрипт (сейчас disabled)
