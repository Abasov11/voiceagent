#!/usr/bin/env bash
# Создаёт/обновляет htpasswd для /recordings/ и кладёт в nginx-контейнер.
# Запуск на VPS клиента:
#   ./infra/scripts/recordings_htpasswd.sh <user> <password>
# По умолчанию: user=voiceagent, password случайный (печатается).

set -euo pipefail

USER="${1:-voiceagent}"
PASS="${2:-}"

if [[ -z "$PASS" ]]; then
    PASS="$(openssl rand -base64 18 | tr -d '=+/')"
    echo "Сгенерирован пароль (запомните, он больше не показывается):"
    echo "  $USER : $PASS"
fi

# Создаём htpasswd через openssl без зависимости на apache2-utils
HASH="$(openssl passwd -apr1 "$PASS")"
sudo bash -c "echo '$USER:$HASH' > /opt/voiceagent/infra/nginx/recordings.htpasswd"
sudo chmod 644 /opt/voiceagent/infra/nginx/recordings.htpasswd
sudo docker cp /opt/voiceagent/infra/nginx/recordings.htpasswd voiceagent-nginx:/etc/nginx/recordings.htpasswd
sudo docker exec voiceagent-nginx nginx -s reload
echo "OK: /recordings/ now requires basic-auth ($USER)"
