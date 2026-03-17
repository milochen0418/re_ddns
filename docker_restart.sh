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

echo ""
ok "=========================================="
ok " All services started!"
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
