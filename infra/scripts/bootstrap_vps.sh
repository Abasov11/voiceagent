#!/usr/bin/env bash
# Базовая установка на чистом Ubuntu 24.04 VPS клиента.
# Запуск: bash bootstrap_vps.sh

set -euo pipefail

echo "==> Обновление apt"
apt-get update -y
apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg lsb-release \
    ufw fail2ban \
    python3-venv build-essential \
    htop tmux jq

echo "==> Установка Docker (official)"
install -m 0755 -d /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/docker.asc ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
fi
ARCH=$(dpkg --print-architecture)
CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")
echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker

echo "==> Создаём app-юзера и каталог /opt/voiceagent"
id app >/dev/null 2>&1 || useradd -m -s /bin/bash -G docker app
mkdir -p /opt/voiceagent
chown -R app:app /opt/voiceagent

echo "==> Swap 2GiB (RAM 3.8 GiB маловато для всего стека)"
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> UFW (SSH + HTTP + HTTPS)"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'ssh'
ufw allow 80/tcp comment 'http'
ufw allow 443/tcp comment 'https'
ufw --force enable

echo "==> fail2ban (sshd jail)"
systemctl enable --now fail2ban

echo "==> Готово. Версии:"
docker --version
docker compose version
echo "Swap:"
swapon --show
echo "UFW:"
ufw status
