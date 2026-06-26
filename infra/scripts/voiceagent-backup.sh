#!/usr/bin/env bash
# pg_dump → /var/backups/voiceagent/, ротация 30 дней.
# Запускается из cron под root, чтобы директорию не мог удалить app/server.

set -euo pipefail

BACKUP_DIR=/var/backups/voiceagent
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT="$BACKUP_DIR/voiceagent-$TS.sql.gz"

# Дамп через сам контейнер postgres (без необходимости иметь pg_dump на хосте)
docker exec voiceagent-postgres pg_dump -U voiceagent -d voiceagent --no-owner --no-acl \
    | gzip -9 > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"
chmod 600 "$OUT"

# Ротация 30 дней
find "$BACKUP_DIR" -type f -name 'voiceagent-*.sql.gz' -mtime +30 -delete

# Лог
echo "$(date -u +%FT%TZ) backup OK: $OUT ($(du -h "$OUT" | cut -f1))" >> "$BACKUP_DIR/backup.log"
