#!/usr/bin/env bash
# Поднять стек на VPS клиента.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose --env-file ../.env up -d --build
docker compose ps
