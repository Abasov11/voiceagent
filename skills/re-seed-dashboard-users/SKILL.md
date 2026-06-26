---
name: re-seed-dashboard-users
description: Пересоздать учётки дашборда (Аскар/Бекзат/Данияр/Камила). Триггеры — «не пускает в дашборд», «после ребилда docker», «забыл пароль», «таблица dashboard_users пуста».
---

# Re-seed dashboard users

## Когда использовать
- Пользователь жалуется «не входит в дашборд», «401 / Invalid credentials»
- После `docker compose down -v` или ребилда стэка
- При первичной установке или восстановлении из pg_dump без сидов
- Когда `/opt/voiceagent/seed-passwords.txt` потерян/устарел

## Pre-checks
1. SSH на VPS клиента: `ssh app-user@203.0.113.10` (доступы в memory `project_ip_ashat_credentials.md`)
2. Контейнер живой: `docker ps | grep voiceagent-backend` → должен быть `Up`
3. БД отвечает: `docker exec voiceagent-backend python -c "from shared.db import engine; print(engine.connect())"`

## Steps
```bash
# 1. Сделать снэпшот текущего состояния (на случай отката)
docker exec voiceagent-postgres pg_dump -U voiceagent voiceagent | gzip > /opt/voiceagent/backups/manual-before-reseed-$(date +%Y%m%d-%H%M%S).sql.gz

# 2. Запустить seed
docker exec voiceagent-backend python -m shared.seed

# 3. Скопировать новые пароли в безопасное место
docker exec voiceagent-backend cat /tmp/seed-passwords.txt | sudo tee /opt/voiceagent/seed-passwords.txt > /dev/null
sudo chmod 600 /opt/voiceagent/seed-passwords.txt

# 4. Распечатать пароли в текущий чат для команды (НЕ логировать в Telegram)
sudo cat /opt/voiceagent/seed-passwords.txt
```

## Verify
- 4 строки emails в `/opt/voiceagent/seed-passwords.txt`: ashat@, alisher@, sanzhar@, ayaulym@
- Логин `owner@example.com` с новым паролем проходит через UI или curl
- Записать новые пароли в memory `project_ip_ashat_session_<дата>.md` (не в общий MEMORY.md index)

## Rollback
Если seed сломал что-то:
```bash
gunzip < /opt/voiceagent/backups/manual-before-reseed-YYYYMMDD-HHMMSS.sql.gz | docker exec -i voiceagent-postgres psql -U voiceagent voiceagent
```

## Связано
- `project_ip_ashat_credentials.md` — VPS креды
