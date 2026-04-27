#!/usr/bin/env bash
# deploy.sh — Deploy or update the coaching stack on TrueNAS.
#
# Usage:
#   bash infra/scripts/deploy.sh                   # git pull + image pull + up
#   bash infra/scripts/deploy.sh --no-pull         # skip git pull
#   bash infra/scripts/deploy.sh --no-image-pull   # skip docker compose pull
#   bash infra/scripts/deploy.sh --restart-only    # restart containers, no pulls

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

DO_GIT_PULL=true
DO_IMAGE_PULL=true
RESTART_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-pull)        DO_GIT_PULL=false; shift ;;
        --no-image-pull)  DO_IMAGE_PULL=false; shift ;;
        --restart-only)   DO_GIT_PULL=false; DO_IMAGE_PULL=false; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# Load .env.prod — required for credentials
ENV_FILE="$PROJECT_ROOT/.env.prod"
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Copy from .env.prod.example and fill in credentials."
    exit 1
fi
set -a
# shellcheck disable=SC1091
source "$ENV_FILE"
set +a

COMPOSE="docker compose -f $PROJECT_ROOT/docker-compose.yml --env-file $ENV_FILE"

echo "=== Coaching Stack Deploy ==="
echo "Project root: $PROJECT_ROOT"
echo "Env:          $ENV_FILE"

# 1. Git pull — run as the invoking user, not root, so SSH keys work
if [ "$DO_GIT_PULL" = true ]; then
    echo ""
    echo "--- Pulling latest code ---"
    cd "$PROJECT_ROOT"
    if [ -n "${SUDO_USER:-}" ]; then
        sudo -u "$SUDO_USER" git pull origin main
    else
        git pull origin main
    fi
    echo "Now at: $(git log --oneline -1)"
fi

# 2. Pre-flight
echo ""
echo "--- Pre-flight ---"
bash "$SCRIPT_DIR/preflight.sh" --data-root "${COACHING_DATA_ROOT:-/mnt/tank/coaching}" || {
    echo "Pre-flight failed. Fix issues before deploying."
    exit 1
}

# 3. Pull latest images from GHCR
if [ "$DO_IMAGE_PULL" = true ]; then
    echo ""
    echo "--- Pulling latest images from GHCR ---"
    $COMPOSE pull
fi

# 4. Start/restart stack
echo ""
echo "--- Starting stack ---"
$COMPOSE up -d

# 5. Wait for health checks
echo ""
echo "--- Waiting for services (up to 90s) ---"
TIMEOUT=90
ELAPSED=0
while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
    UNHEALTHY=$(docker ps --filter name=coaching_ --format '{{.Names}} {{.Status}}' | grep "unhealthy" || true)
    if [ -z "$UNHEALTHY" ]; then
        break
    fi
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    echo "  Waiting... (${ELAPSED}s) — unhealthy: $UNHEALTHY"
done

echo ""
echo "--- Service Status ---"
$COMPOSE ps

echo ""
echo "=== Deploy complete ==="
echo "  Config UI: http://${TRUENAS_IP:-localhost}:8080"
echo "  Grafana:   http://${TRUENAS_IP:-localhost}:3000"
echo "  InfluxDB:  http://${TRUENAS_IP:-localhost}:8086"
