#!/usr/bin/env bash
set -euo pipefail

# ── docker_restart.sh ──
#
# Clean restart of the entire re-ddns Docker stack.
#
# Order:
#   1. Stop all containers & remove volumes (clean stale registry/nginx configs)
#   2. Start re-ddns and wait until its API is ready
#   3. Start testapp, testapp2, testapp3
#
# Usage:
#   ./docker_restart.sh                # full clean restart
#   ./docker_restart.sh --keep-volumes # restart without clearing volumes

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[restart]${NC} $*"; }
ok()   { echo -e "${GREEN}[restart]${NC} $*"; }
warn() { echo -e "${YELLOW}[restart]${NC} $*"; }
err()  { echo -e "${RED}[restart]${NC} $*" >&2; }

COMPOSE_FILE="docker-compose.test.yml"
KEEP_VOLUMES=false

if [[ "${1:-}" == "--keep-volumes" ]]; then
    KEEP_VOLUMES=true
fi

# ──────────────────────────────────────────────
# Auto-detect Mac LAN IP for DNS A records
# ──────────────────────────────────────────────
if [[ -z "${EXTERNAL_IP:-}" ]]; then
    EXTERNAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")
fi
export EXTERNAL_IP
log "DNS A records will point to: ${EXTERNAL_IP}"

# ──────────────────────────────────────────────
# 1. Stop everything
# ──────────────────────────────────────────────
log "Stopping all containers ..."
if $KEEP_VOLUMES; then
    docker compose -f "$COMPOSE_FILE" down
    log "Containers removed (volumes kept)"
else
    docker compose -f "$COMPOSE_FILE" down -v
    log "Containers and volumes removed"
fi

# Also stop smart-app services (each has its own compose file)
for f in docker-compose.smart-app-*.yml; do
    [[ -f "$f" ]] || continue
    warn "Stopping smart-app from $f ..."
    docker compose -f "$f" down -v 2>/dev/null || true
done

# Remove any leftover smart-app containers not managed by compose
for c in $(docker ps -a --format '{{.Names}}' | grep '^smart-app' || true); do
    warn "Removing leftover container: $c"
    docker rm -f "$c" 2>/dev/null || true
done

# ──────────────────────────────────────────────
# 2. Start re-ddns first, wait for API
# ──────────────────────────────────────────────
log "Starting re-ddns ..."
docker compose -f "$COMPOSE_FILE" up -d --build re-ddns

log "Waiting for re-ddns API to be ready ..."
MAX_WAIT=180
for i in $(seq 1 $MAX_WAIT); do
    STATUS=$(docker exec re-ddns curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/dns/status 2>/dev/null || echo "000")
    if [[ "$STATUS" == "200" ]]; then
        ok "re-ddns API is ready (attempt $i)"
        break
    fi
    if [[ $i -eq $MAX_WAIT ]]; then
        err "re-ddns API did not become ready after ${MAX_WAIT}s"
        err "Check logs: docker logs re-ddns"
        exit 1
    fi
    sleep 1
done

# ──────────────────────────────────────────────
# 3. Start testapp, testapp2, testapp3
# ──────────────────────────────────────────────
log "Starting testapp, testapp2, testapp3 ..."
docker compose -f "$COMPOSE_FILE" up -d --build test-app test-app2 test-app3

# ──────────────────────────────────────────────
# 4. Wait for all apps to be healthy
# ──────────────────────────────────────────────
# Each app must respond HTTP 200 on its frontend (port 3000 inside the
# container) AND be reachable through the nginx proxy (HTTPS from host).

APP_TIMEOUT=300   # Reflex apps can take a while to compile

check_app_ready() {
    local container="$1"
    local label="$2"
    local url="$3"

    log "Waiting for ${label} to be ready ..."
    for i in $(seq 1 $APP_TIMEOUT); do
        # 1) Check if container is still running
        if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
            err "${label}: container '${container}' is not running!"
            return 1
        fi

        # 2) Check internal port 3000
        INTERNAL=$(docker exec "$container" curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/ 2>/dev/null || echo "000")

        # 3) Check external HTTPS through nginx
        EXTERNAL=$(curl -sk -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")

        if [[ "$INTERNAL" == "200" && "$EXTERNAL" == "200" ]]; then
            ok "${label} is ready! (internal=200, HTTPS=200, ${i}s)"
            return 0
        fi

        # Progress every 15 seconds
        if (( i % 15 == 0 )); then
            warn "${label}: still waiting ... (internal=${INTERNAL}, HTTPS=${EXTERNAL}, ${i}s/${APP_TIMEOUT}s)"
        fi
        sleep 1
    done

    err "${label} did not become ready after ${APP_TIMEOUT}s (internal=${INTERNAL}, HTTPS=${EXTERNAL})"
    err "  Check logs: docker logs ${container}"
    return 1
}

FAILED=0
check_app_ready "test-app"  "testapp"  "https://testapp.reflex-ddns.com/"  || FAILED=$((FAILED+1))
check_app_ready "test-app2" "testapp2" "https://testapp2.reflex-ddns.com/" || FAILED=$((FAILED+1))
check_app_ready "test-app3" "testapp3" "https://testapp3.reflex-ddns.com/" || FAILED=$((FAILED+1))

echo ""
if [[ $FAILED -gt 0 ]]; then
    err "=========================================="
    err " ${FAILED} app(s) failed health check!"
    err "=========================================="
    exit 1
fi

ok "=========================================="
ok " All services started and healthy!"
ok ""
ok "  re-ddns:   https://home.reflex-ddns.com"
ok "  testapp:   https://testapp.reflex-ddns.com"
ok "  testapp2:  https://testapp2.reflex-ddns.com"
ok "  testapp3:  https://testapp3.reflex-ddns.com"
ok "  noVNC:     http://localhost:6080/vnc.html"
ok ""
ok " To launch smart apps:"
ok "  ./smart_launch.sh <REPO> <APP_NAME> <SUBDOMAIN>"
ok ""
ok " Example:"
ok "  ./smart_launch.sh https://github.com/milochen0418/codoc_in_vecdraw.git codoc_in_vecdraw vecdraw"
ok "=========================================="
