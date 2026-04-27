#!/usr/bin/env bash
# preflight.sh — Pre-flight validation for coaching stack deployment.
#
# Usage:  bash infra/scripts/preflight.sh
#         bash infra/scripts/preflight.sh --data-root /mnt/tank/coaching

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
WARN=0
FAIL=0

pass()  { PASS=$((PASS+1)); echo -e "  ${GREEN}✓${NC} $1"; }
warn()  { WARN=$((WARN+1)); echo -e "  ${YELLOW}!${NC} $1"; }
fail()  { FAIL=$((FAIL+1)); echo -e "  ${RED}✗${NC} $1"; }

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
DATA_ROOT="${COACHING_DATA_ROOT:-/mnt/tank/coaching}"
while [[ $# -gt 0 ]]; do
    case $1 in
        --data-root) DATA_ROOT="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

echo ""
echo "Coaching Stack Pre-flight Check"
echo "================================"
echo "Data root: $DATA_ROOT"
echo ""

# ---------------------------------------------------------------------------
# 1. Docker & Compose
# ---------------------------------------------------------------------------
echo "Docker:"
if command -v docker &>/dev/null; then
    pass "docker CLI found ($(docker --version | head -c 40))"
else
    fail "docker CLI not found"
fi

if docker compose version &>/dev/null; then
    pass "docker compose plugin found"
else
    fail "docker compose plugin not found"
fi

if docker info &>/dev/null 2>&1; then
    pass "Docker daemon running"
else
    fail "Docker daemon not running or no permissions"
fi

# ---------------------------------------------------------------------------
# 2. TrueNAS dataset directories
# ---------------------------------------------------------------------------
echo ""
echo "TrueNAS Datasets ($DATA_ROOT):"
DATASETS=("influxdb" "postgres" "chromadb" "grafana" "garmin" "garth" "logs" "config" "workout_imports")
for ds in "${DATASETS[@]}"; do
    dir="$DATA_ROOT/$ds"
    if [ -d "$dir" ]; then
        pass "$ds dataset exists"
    else
        fail "$ds dataset missing: $dir"
        echo -e "       Create with: ${YELLOW}mkdir -p $dir${NC}"
    fi
done

# ---------------------------------------------------------------------------
# 3. Environment file and required variables
# ---------------------------------------------------------------------------
echo ""
echo "Configuration:"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ -f "$PROJECT_ROOT/.env.prod" ]; then
    pass ".env.prod exists"

    check_var() {
        local var="$1"
        local val
        val=$(grep "^${var}=" "$PROJECT_ROOT/.env.prod" | cut -d= -f2-)
        if [ -z "$val" ] || [ "$val" = "CHANGE_ME" ]; then
            fail "$var is not set in .env.prod"
        else
            pass "$var is set"
        fi
    }

    check_var "POSTGRES_PASSWORD"
    check_var "INFLUXDB_PASSWORD"
    check_var "INFLUXDB_TOKEN"
    check_var "GRAFANA_PASSWORD"
    check_var "CONFIG_API_KEY"
    check_var "GARMIN_USERNAME"
    check_var "GARMIN_PASSWORD"
    check_var "GHCR_TOKEN"
else
    fail ".env.prod not found — copy from .env.prod.example and fill in credentials"
fi

# ---------------------------------------------------------------------------
# 4. Compose config validation
# ---------------------------------------------------------------------------
echo ""
echo "Compose Config:"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
if [ -f "$COMPOSE_FILE" ]; then
    if docker compose -f "$COMPOSE_FILE" config --quiet 2>/dev/null; then
        pass "docker-compose.yml is valid"
    else
        fail "docker-compose.yml has errors"
    fi
else
    fail "docker-compose.yml not found"
fi

# ---------------------------------------------------------------------------
# 5. Port conflicts
# ---------------------------------------------------------------------------
echo ""
echo "Ports:"
for port in 8080 8086 3000 8001 5433; do
    if ss -tlnp 2>/dev/null | grep -q ":${port} " || \
       netstat -tlnp 2>/dev/null | grep -q ":${port} "; then
        warn "Port $port already in use"
    else
        pass "Port $port available"
    fi
done

# ---------------------------------------------------------------------------
# 6. Disk space
# ---------------------------------------------------------------------------
echo ""
echo "Disk Space:"
if command -v df &>/dev/null && [ -d "$DATA_ROOT" ]; then
    AVAIL_KB=$(df -k "$DATA_ROOT" 2>/dev/null | tail -1 | awk '{print $4}')
    if [ -n "$AVAIL_KB" ] && [ "$AVAIL_KB" -gt 0 ] 2>/dev/null; then
        AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
        if [ "$AVAIL_GB" -ge 20 ]; then
            pass "${AVAIL_GB}GB available on $DATA_ROOT"
        elif [ "$AVAIL_GB" -ge 10 ]; then
            warn "${AVAIL_GB}GB available — 20GB+ recommended"
        else
            fail "${AVAIL_GB}GB available — need at least 10GB"
        fi
    else
        warn "Could not determine available disk space"
    fi
else
    warn "Could not check disk space (data root doesn't exist yet)"
fi

# ---------------------------------------------------------------------------
# 7. Ollama reachability
# ---------------------------------------------------------------------------
echo ""
echo "Ollama:"
OLLAMA_URL="${OLLAMA_PRIMARY_URL:-http://192.168.50.46:11434}"
if curl -sf --max-time 3 "${OLLAMA_URL}/api/tags" &>/dev/null; then
    pass "Ollama reachable at $OLLAMA_URL"
else
    warn "Ollama not reachable at $OLLAMA_URL — coaching pipeline will fail without it"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "================================"
echo -e "Results: ${GREEN}${PASS} passed${NC}, ${YELLOW}${WARN} warnings${NC}, ${RED}${FAIL} failed${NC}"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo -e "${RED}Fix the failures above before deploying.${NC}"
    exit 1
elif [ "$WARN" -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}Warnings present — deployment will work but review them.${NC}"
    exit 0
else
    echo ""
    echo -e "${GREEN}All checks passed — ready to deploy.${NC}"
    exit 0
fi
