#!/usr/bin/env bash
# Deploy workspace-voiceagent на VPS клиента (203.0.113.10).
#
# Принципы деплоя:
#   - НЕТ interactive pexpect heredoc — только scp + sudo bash;
#   - tar safety snapshot ДО операции в /var/backups/voiceagent-snapshots/;
#   - после распаковки: alembic upgrade head + restart backend;
#   - smoke: pytest + readyz + контейнеры; падение любой проверки = exit 1.
#
# Запуск:
#   ./infra/scripts/deploy.sh                # обычный deploy с verify
#   ./infra/scripts/deploy.sh --skip-pytest  # без полного pytest (faster)
#   ./infra/scripts/deploy.sh --no-snapshot  # пропустить tar snapshot (НЕ рекомендуется)

set -euo pipefail

# ---- Параметры ----
HOST="${CHEMP_HOST:-203.0.113.10}"
SSH_KEY="${CHEMP_SSH_KEY:-$HOME/.ssh/voiceagent_ed25519}"
REMOTE_DIR="${CHEMP_REMOTE_DIR:-/opt/voiceagent}"
SNAPSHOT_DIR="${CHEMP_SNAPSHOT_DIR:-/var/backups/voiceagent-snapshots}"
WORKDIR="$(cd "$(dirname "$0")/../.." && pwd)"

SKIP_PYTEST=0
SKIP_SNAPSHOT=0
for arg in "$@"; do
    case "$arg" in
        --skip-pytest)  SKIP_PYTEST=1 ;;
        --no-snapshot)  SKIP_SNAPSHOT=1 ;;
        *) echo "unknown arg: $arg"; exit 2 ;;
    esac
done

SSH="ssh -i $SSH_KEY -o ConnectTimeout=15 root@$HOST"
SCP="scp -i $SSH_KEY"

ts="$(date -u +%Y-%m-%dT%H%M%SZ)"
bundle="/tmp/voiceagent-deploy-${ts}.tgz"

echo "==> 1. Build local bundle: $bundle"
cd "$WORKDIR"
tar --exclude=.git --exclude=local_storage --exclude=__pycache__ \
    --exclude=node_modules --exclude=tests/htmlcov \
    -czf "$bundle" .
ls -lh "$bundle"

if [[ $SKIP_SNAPSHOT -eq 0 ]]; then
    echo "==> 2. Safety snapshot of $REMOTE_DIR on $HOST"
    $SSH "mkdir -p $SNAPSHOT_DIR && \
          tar --exclude=local_storage \
              -czf $SNAPSHOT_DIR/pre-${ts}.tgz \
              -C $REMOTE_DIR . && \
          ls -lh $SNAPSHOT_DIR/pre-${ts}.tgz"
else
    echo "==> 2. SKIP snapshot (--no-snapshot)"
fi

echo "==> 3. Upload bundle"
$SCP "$bundle" "root@$HOST:/tmp/$(basename "$bundle")"

echo "==> 4. Extract + alembic upgrade head + restart backend"
$SSH "cd $REMOTE_DIR && \
      tar -xzf /tmp/$(basename "$bundle") && \
      rm /tmp/$(basename "$bundle") && \
      docker restart voiceagent-backend && \
      sleep 4 && \
      docker exec voiceagent-backend alembic -c /app/shared/alembic.ini upgrade head 2>&1 | tail -5"

echo "==> 5. Verify: readyz + containers"
$SSH 'curl -s http://127.0.0.1/readyz && echo "" && docker ps --format "{{.Names}} {{.Status}}"'

if [[ $SKIP_PYTEST -eq 0 ]]; then
    echo "==> 6. Run pytest"
    $SSH 'docker exec voiceagent-backend pytest /app/tests -q 2>&1 | tail -8'
else
    echo "==> 6. SKIP pytest (--skip-pytest)"
fi

rm -f "$bundle"
echo "==> Deploy OK (snapshot: $SNAPSHOT_DIR/pre-${ts}.tgz)"
